
import os
import json
import re
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai


# ==========================================
# FILE PATHS
# ==========================================

QUESTIONS_FILE = Path("questions.txt")
TRANSCRIPT_FILE = Path("transcript.txt")
REPORT_FILE = Path("ai_report.txt")


# ==========================================
# GEMINI CONFIGURATION
# ==========================================

MODEL_NAME = "gemini-3.8-flash"
CHUNK_SIZE = 12000

MAX_RETRIES = 3
INITIAL_RETRY_DELAY = 5


# ==========================================
# TRANSCRIPT LINE FORMAT
# [12.4s] [SPEAKER_00] Hello everyone.
# ==========================================

TRANSCRIPT_PATTERN = re.compile(
    r"^\[(\d+(?:\.\d+)?)s\]\s+\[([^\]]+)\]\s*(.*)$"
)


# ==========================================
# JSON RESPONSE SCHEMA
# ==========================================

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "answers": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "question": {"type": "STRING"},
                    "found": {"type": "BOOLEAN"},
                    "answer": {"type": "STRING"},
                    "evidence": {"type": "STRING"},
                    "timestamp": {
                        "type": ["STRING", "NULL"]
                    },
                    "speaker": {"type": "STRING"},
                    "confidence": {
                        "type": "STRING",
                        "enum": ["high", "medium", "low"]
                    }
                },
                "required": [
                    "question",
                    "found",
                    "answer",
                    "evidence",
                    "timestamp",
                    "speaker",
                    "confidence"
                ]
            }
        }
    },
    "required": ["answers"]
}


# ==========================================
# FILE LOADER
# ==========================================

def load_file(path):
    """Load a text file."""

    if not path.exists():
        raise FileNotFoundError(
            f"File not found: {path}"
        )

    return path.read_text(encoding="utf-8")


# ==========================================
# TRANSCRIPT SPLITTER
# ==========================================

def split_transcript(transcript):
    """Split transcript into chunks while preserving lines."""

    lines = transcript.splitlines()

    chunks = []
    current_chunk = []
    current_length = 0

    for line in lines:

        if (
            current_length + len(line) > CHUNK_SIZE
            and current_chunk
        ):
            chunks.append("\n".join(current_chunk))

            current_chunk = []
            current_length = 0

        current_chunk.append(line)
        current_length += len(line) + 1

    if current_chunk:
        chunks.append("\n".join(current_chunk))

    return chunks


# ==========================================
# GEMINI RETRY SYSTEM
# ==========================================

def call_gemini_with_retry(client, prompt, chunk_number):
    """Retry Gemini requests after temporary API errors."""

    for attempt in range(1, MAX_RETRIES + 1):

        try:

            return client.interactions.create(
                model=MODEL_NAME,
                input=prompt,
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": RESPONSE_SCHEMA
                }
            )

        except Exception as error:

            error_message = str(error).lower()

            retryable_errors = [
                "429",
                "500",
                "502",
                "503",
                "504",
                "service_unavailable",
                "temporarily unavailable",
                "timeout",
                "rate limit"
            ]

            should_retry = any(
                code in error_message
                for code in retryable_errors
            )

            if not should_retry or attempt == MAX_RETRIES:
                raise

            wait_time = INITIAL_RETRY_DELAY * (2 ** (attempt - 1))

            print(
                f"\nGemini temporary error: {error}"
            )

            print(
                f"Retrying chunk {chunk_number} "
                f"in {wait_time} seconds "
                f"(attempt {attempt}/{MAX_RETRIES})..."
            )

            time.sleep(wait_time)


# ==========================================
# CHUNK ANALYZER
# ==========================================

def analyze_chunk(client, chunk, questions, chunk_number):
    """Analyze one transcript chunk using Gemini."""

    question_list = "\n".join(
        f"- {question}" for question in questions
    )

    prompt = f"""
You are an AI meeting analysis assistant called MeetWithMe.

YOUR TASK:

Analyze the provided meeting transcript and answer
the questions using only information from this transcript.

STRICT RULES:

1. Never invent information.
2. Use only facts explicitly supported by the transcript.
3. If an answer cannot be found, set found to false.
4. Provide a short, relevant, verbatim quote as evidence.
5. Evidence must be copied exactly from the transcript.
6. Only use timestamps that actually appear in the transcript.
7. The timestamp must belong to the line containing the evidence.
8. Return the timestamp without brackets or trailing "s".
   Example: "12.4"
9. Never create or estimate timestamps.
10. Identify the speaker using the label on the evidence line.
11. Copy the speaker label exactly, such as SPEAKER_00.
12. Never guess a speaker's identity.
13. If the speaker cannot be identified, use "Unknown".
14. Distinguish confirmed facts from possibilities or opinions.
15. Use high, medium, or low confidence appropriately.
16. Answer in the same language as the relevant conversation.
17. Evaluate every question independently.
18. Do not use outside knowledge.
19. If the transcript only partially answers a question,
    clearly explain the limitation.
20. Only use evidence from the current transcript chunk.

QUESTIONS:

{question_list}

TRANSCRIPT CHUNK {chunk_number}:

{chunk}
"""

    response = call_gemini_with_retry(
        client,
        prompt,
        chunk_number
    )

    if not response.output_text:
        raise ValueError(
            f"Empty response from Gemini for chunk {chunk_number}."
        )

    try:

        result = json.loads(response.output_text)

    except json.JSONDecodeError as error:

        raise ValueError(
            f"Invalid JSON response in chunk {chunk_number}."
        ) from error

    if not isinstance(result.get("answers"), list):
        raise ValueError(
            f"Invalid answers structure in chunk {chunk_number}."
        )

    return result


# ==========================================
# ANSWER VALIDATION
# ==========================================

def validate_answers(result, transcript):
    """Verify evidence, timestamps and speaker labels."""

    verified_answers = []

    for item in result.get("answers", []):

        if not isinstance(item, dict):
            continue

        if not item.get("found"):
            continue

        evidence = item.get("evidence", "").strip()
        answer = item.get("answer", "").strip()
        timestamp = item.get("timestamp")
        reported_speaker = item.get("speaker", "").strip()

        if not evidence or not answer or timestamp is None:
            continue

        timestamp = str(timestamp).strip()

        matching_lines = [
            line
            for line in transcript.splitlines()
            if evidence in line
        ]

        if not matching_lines:
            print(
                "WARNING: Unsupported evidence rejected."
            )
            continue

        verified_match = None

        for line in matching_lines:

            parsed = TRANSCRIPT_PATTERN.match(line)

            if not parsed:
                continue

            actual_timestamp = parsed.group(1)
            actual_speaker = parsed.group(2)

            if timestamp != actual_timestamp:
                continue

            if reported_speaker != actual_speaker:
                continue

            verified_match = {
                "timestamp": actual_timestamp,
                "speaker": actual_speaker
            }

            break

        if verified_match is None:

            print(
                "WARNING: Timestamp or speaker verification failed."
            )

            continue

        confidence = item.get("confidence", "low")

        if confidence not in {"high", "medium", "low"}:
            confidence = "low"

        verified_answers.append({
            "question": item.get("question", "").strip(),
            "answer": answer,
            "evidence": evidence,
            "timestamp": verified_match["timestamp"],
            "speaker": verified_match["speaker"],
            "confidence": confidence
        })

    return verified_answers


# ==========================================
# ANSWER COLLECTOR
# ==========================================

def collect_answers(all_results):
    """Combine and deduplicate verified answers."""

    collected = {}

    for result in all_results:

        for item in result:

            question = item["question"].strip().lower()

            if question not in collected:
                collected[question] = []

            if not any(
                existing["evidence"] == item["evidence"]
                and existing["speaker"] == item["speaker"]
                for existing in collected[question]
            ):

                collected[question].append(item)

    return collected


# ==========================================
# REPORT GENERATOR
# ==========================================

def generate_report(all_results, questions, failed_chunks=0):
    """Generate the final AI analysis report."""

    collected = collect_answers(all_results)

    report = [
        "MEETWITHME",
        "AI MEETING ANALYSIS REPORT",
        "=" * 50,
        ""
    ]

    if failed_chunks:

        report.extend([
            f"WARNING: {failed_chunks} transcript chunk(s) "
            "could not be analyzed.",
            ""
        ])

    for question in questions:

        report.append(f"QUESTION: {question}")
        report.append("-" * 50)

        matches = collected.get(
            question.strip().lower(),
            []
        )

        if not matches:

            if failed_chunks == 0:

                report.append(
                    "No verified answer was found in the transcript."
                )

            else:

                report.append(
                    "No verified answer available. "
                    "Some transcript sections could not be analyzed."
                )

            report.append("")
            continue

        confidence_order = {
            "high": 3,
            "medium": 2,
            "low": 1
        }

        matches.sort(
            key=lambda item: confidence_order[item["confidence"]],
            reverse=True
        )

        for match in matches[:3]:

            report.append(
                f"Answer: {match['answer']}"
            )

            report.append(
                f"Speaker: {match['speaker']}"
            )

            report.append(
                f'Evidence: "{match["evidence"]}"'
            )

            report.append(
                f"Timestamp: {match['timestamp']}s"
            )

            report.append(
                f"Confidence: {match['confidence'].upper()}"
            )

            report.append("")

    REPORT_FILE.write_text(
        "\n".join(report),
        encoding="utf-8"
    )

    print(f"\nAI report saved: {REPORT_FILE}")


# ==========================================
# MAIN
# ==========================================

def main():
    """Main AI analysis entry point."""

    print("\n=== MEETWITHME AI ANALYZER ===\n")

    load_dotenv()

    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY was not found in the environment."
        )

    questions = [
        line.strip()
        for line in load_file(QUESTIONS_FILE).splitlines()
        if line.strip()
    ]

    transcript = load_file(TRANSCRIPT_FILE)

    if not questions:
        raise ValueError("No questions were found.")

    if not transcript.strip():
        raise ValueError("The transcript is empty.")

    client = genai.Client(api_key=api_key)

    try:

        chunks = split_transcript(transcript)

        all_results = []
        failed_chunks = 0

        print(
            f"Total transcript chunks: {len(chunks)}"
        )

        for index, chunk in enumerate(chunks, start=1):

            print(
                f"\nAnalyzing chunk {index}/{len(chunks)}..."
            )

            try:

                result = analyze_chunk(
                    client,
                    chunk,
                    questions,
                    index
                )

                verified = validate_answers(
                    result,
                    chunk
                )

                all_results.append(verified)

                print(
                    f"Verified answers: {len(verified)}"
                )

            except Exception as error:

                failed_chunks += 1

                print(
                    f"Chunk {index} failed: {error}"
                )

                continue

        print("\nGenerating final report...")

        generate_report(
            all_results,
            questions,
            failed_chunks
        )

        print("\nMEETWITHME ANALYSIS COMPLETED!")

        print(
            f"Generated file: {REPORT_FILE}"
        )

    finally:

        client.close()


if __name__ == "__main__":
    main()
