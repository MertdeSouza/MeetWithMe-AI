"""Step 3: question sets and continuous analysis while the meeting runs.

Reuses the verified-answer logic that already exists in ai_analyzer.py
(strict JSON schema, evidence must appear word for word in the transcript,
timestamp and speaker must match the evidence line).
"""

import difflib
import queue
import threading
from pathlib import Path

import ai_analyzer

# ==========================================
# SETTINGS
# ==========================================

DEFAULT_QUESTIONS_FILE = Path("questions.txt")
QUESTIONS_DIR = Path("questions")

ANALYSIS_INTERVAL_SECONDS = 180   # how often new speech is analyzed
OVERLAP_LINES = 3                 # lines repeated so a split answer is not lost
FUZZY_MATCH_CUTOFF = 0.8          # how close a rephrased question must be
                                  # (strict on purpose: a dropped answer is
                                  # better than one filed under the wrong question)


# ==========================================
# QUESTION SETS
# ==========================================

def load_questions(path):
    """Read one question per line (blank lines and #comments are ignored)."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [
        line.strip()
        for line in lines
        if line.strip() and not line.strip().startswith("#")
    ]


def list_question_files():
    """questions.txt plus every .txt file inside the questions/ folder."""
    files = []
    if DEFAULT_QUESTIONS_FILE.is_file():
        files.append(DEFAULT_QUESTIONS_FILE)
    if QUESTIONS_DIR.is_dir():
        files.extend(sorted(QUESTIONS_DIR.glob("*.txt")))
    return files


def choose_questions(input_func=input):
    """Pick a question set. Returns (file, list_of_questions)."""
    files = list_question_files()

    if not files:
        raise FileNotFoundError(
            "No questions found. Create questions.txt "
            "(one question per line)."
        )

    if len(files) == 1:
        chosen = files[0]
    else:
        print("Question sets:")
        for number, file in enumerate(files, start=1):
            count = len(load_questions(file))
            print(f"  {number}) {file}  ({count} questions)")

        answer = input_func("Choose a set [1]: ").strip()
        index = 0
        if answer.isdigit() and 1 <= int(answer) <= len(files):
            index = int(answer) - 1
        chosen = files[index]

    questions = load_questions(chosen)
    if not questions:
        raise ValueError(f"{chosen} does not contain any questions.")

    return chosen, questions


def match_question(text, questions):
    """Map the question text returned by Gemini back to one of ours.

    Gemini sometimes rephrases a question slightly. Matching by exact text
    would silently lose the answer, so we also accept a close match.
    """
    key = text.strip().lower()
    lowered = [question.strip().lower() for question in questions]

    if key in lowered:
        return questions[lowered.index(key)]

    close = difflib.get_close_matches(
        key, lowered, n=1, cutoff=FUZZY_MATCH_CUTOFF
    )
    if close:
        return questions[lowered.index(close[0])]

    return None


def format_notification(question, item):
    return (
        f"NEW ANSWER | {question}\n"
        f"  {item['answer']}\n"
        f"  [{item['timestamp']}s] {item['speaker']}: "
        f"\"{item['evidence']}\" ({item['confidence']})"
    )


# ==========================================
# CONTINUOUS ANALYSIS
# ==========================================

class LiveAnalyzer(threading.Thread):
    """Analyzes only the new part of the transcript every few minutes.

    Questions can be added or removed while it runs. A newly added question
    is checked against everything said so far, right away.
    """

    def __init__(
        self,
        client,
        questions,
        transcript_path,
        report_path,
        interval=ANALYSIS_INTERVAL_SECONDS,
        overlap_lines=OVERLAP_LINES,
    ):
        super().__init__(daemon=True)
        self.client = client
        self.questions = list(questions)
        self.transcript_path = Path(transcript_path)
        self.report_path = Path(report_path)
        self.interval = interval
        self.overlap_lines = overlap_lines

        self.notifications = queue.Queue()
        self.last_error = None

        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._wake = threading.Event()
        self._cursor = 0              # transcript lines already analyzed
        self._answers = []            # verified answers found so far
        self._pending_rescan = []     # questions added during the meeting
        self._last_run_failures = 0

    # ---- public API (safe to call from other threads) ---------------

    @property
    def answer_count(self):
        with self._lock:
            return len(self._answers)

    def answers_snapshot(self):
        with self._lock:
            return [dict(answer) for answer in self._answers]

    def question_list(self):
        with self._lock:
            return list(self.questions)

    def add_question(self, question):
        """Add a question; it is checked against the whole transcript."""
        question = question.strip()
        with self._lock:
            if not question or question in self.questions:
                return False
            self.questions.append(question)
            self._pending_rescan.append(question)
        self._wake.set()
        return True

    def remove_question(self, question):
        """Remove a question together with its answers."""
        with self._lock:
            if question not in self.questions:
                return False
            self.questions.remove(question)
            self._pending_rescan = [
                q for q in self._pending_rescan if q != question
            ]
            self._answers = [
                a for a in self._answers if a["question"] != question
            ]
        return True

    def stop(self):
        """Ask the thread to do one final pass and finish."""
        self._stop_event.set()
        self._wake.set()

    def run(self):
        while True:
            # Sleeps for the interval, or wakes early when a question is
            # added or stop() is called.
            self._wake.wait(self.interval)
            self._wake.clear()

            if self._stop_event.is_set():
                break

            self.analyze_new_lines()

        self.analyze_new_lines()   # final pass over the remaining speech
        self.write_report()

    # ---- internals --------------------------------------------------

    def _read_lines(self):
        if not self.transcript_path.exists():
            return []

        text = self.transcript_path.read_text(encoding="utf-8")
        lines = text.splitlines()

        # The last line may still be half written.
        if text and not text.endswith("\n"):
            lines = lines[:-1]

        return [line for line in lines if line.strip()]

    def _add(self, item):
        with self._lock:
            question = match_question(item["question"], self.questions)
            if question is None:
                return 0   # an answer to a question we did not ask

            for existing in self._answers:
                if (
                    existing["question"] == question
                    and existing["evidence"] == item["evidence"]
                    and existing["speaker"] == item["speaker"]
                ):
                    return 0

            stored = dict(item, question=question)
            self._answers.append(stored)
            self.notifications.put((question, stored))
            return 1

    def _analyze_text(self, text, questions):
        """Ask Gemini about one block of transcript.

        Returns (new_answers, failed_chunks).
        """
        if not questions:
            return 0, 0

        new_answers = 0
        failures = 0

        for number, chunk in enumerate(
            ai_analyzer.split_transcript(text), start=1
        ):
            try:
                result = ai_analyzer.analyze_chunk(
                    self.client, chunk, questions, number
                )
                verified = ai_analyzer.validate_answers(result, chunk)
            except Exception as error:
                failures += 1
                self.last_error = f"{type(error).__name__}: {error}"
                continue

            for item in verified:
                new_answers += self._add(item)

        return new_answers, failures

    def analyze_new_lines(self):
        """Run one analysis pass. Returns the number of new answers."""
        lines = self._read_lines()
        new_answers = 0
        failures = 0

        # 1) Questions added during the meeting: check everything so far.
        with self._lock:
            pending = self._pending_rescan
            self._pending_rescan = []

        if pending and lines:
            found, failed = self._analyze_text("\n".join(lines), pending)
            new_answers += found
            failures += failed

            if failed:   # try again at the next pass
                with self._lock:
                    for question in pending:
                        if (
                            question in self.questions
                            and question not in self._pending_rescan
                        ):
                            self._pending_rescan.append(question)

        # 2) Speech added since the last pass, for all questions.
        if len(lines) > self._cursor:
            start = max(0, self._cursor - self.overlap_lines)
            found, failed = self._analyze_text(
                "\n".join(lines[start:]), self.question_list()
            )
            new_answers += found
            failures += failed

            # Move forward only if everything worked; otherwise the same
            # lines are tried again at the next pass.
            if failed == 0:
                self._cursor = len(lines)

        self._last_run_failures = failures
        return new_answers

    def write_report(self):
        """Write the full report using the existing report generator."""
        ai_analyzer.REPORT_FILE = self.report_path
        ai_analyzer.generate_report(
            [self.answers_snapshot()],
            self.question_list(),
            self._last_run_failures,
        )
