"""A live listening session that can be started and stopped from the web UI.

Does the same job as the terminal version in live_listen.py (and reuses its
building blocks), but is controlled through methods instead of the keyboard.
live_listen.py itself is not changed and keeps working.
"""

import os
import queue
import threading
import time
from pathlib import Path

import live_listen as LL
from live_analysis import LiveAnalyzer

IDLE = "idle"
LOADING = "loading"
LISTENING = "listening"
STOPPING = "stopping"
ANALYZING = "analyzing"

RECENT_LINES = 5


# ==========================================
# DEFAULT PARTS (replaced by fakes in tests)
# ==========================================

_MODEL = None
_MODEL_LOCK = threading.Lock()


def load_whisper_model():
    """Load Faster-Whisper once and reuse it for later sessions."""
    global _MODEL
    with _MODEL_LOCK:
        if _MODEL is None:
            from faster_whisper import WhisperModel

            _MODEL = WhisperModel(
                LL.WHISPER_MODEL,
                device=LL.WHISPER_DEVICE,
                compute_type=LL.WHISPER_COMPUTE_TYPE,
            )
        return _MODEL


def create_gemini_client():
    """Return a Gemini client, or None when no API key is configured."""
    from dotenv import load_dotenv

    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None

    from google import genai

    return genai.Client(api_key=api_key)


class WasapiCapture:
    """Captures the speaker output (Windows WASAPI loopback)."""

    def __init__(self, raw_queue):
        self.raw_queue = raw_queue
        self.channels = 0
        self.rate = 0
        self.device_name = ""
        self._audio = None
        self._stream = None

    def open(self):
        import pyaudiowpatch as pyaudio

        self._audio = pyaudio.PyAudio()
        try:
            device = LL.find_default_loopback(self._audio, pyaudio)
            self.channels = int(device["maxInputChannels"])
            self.rate = int(device["defaultSampleRate"])
            self.device_name = device["name"]

            def callback(in_data, frame_count, time_info, status):
                self.raw_queue.put((time.monotonic(), in_data))
                return (None, pyaudio.paContinue)

            self._stream = self._audio.open(
                format=pyaudio.paInt16,
                channels=self.channels,
                rate=self.rate,
                input=True,
                input_device_index=device["index"],
                frames_per_buffer=960,
                stream_callback=callback,
            )
        except Exception:
            self.close()
            raise

    def close(self):
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

        if self._audio is not None:
            try:
                self._audio.terminate()
            except Exception:
                pass
            self._audio = None


# ==========================================
# SESSION
# ==========================================

class LiveSession:
    def __init__(
        self,
        questions=None,
        model_loader=load_whisper_model,
        capture_factory=WasapiCapture,
        client_factory=create_gemini_client,
        analysis_interval=None,
        output_dir=".",
    ):
        self._model_loader = model_loader
        self._capture_factory = capture_factory
        self._client_factory = client_factory
        self._analysis_interval = analysis_interval
        self._output_dir = Path(output_dir)

        self._lock = threading.RLock()
        self.state = IDLE
        self.questions = list(questions or [])
        self.error = None
        self.warning = None
        self.transcript_path = None
        self.report_path = None

        self._worker = None
        self._analyzer = None
        self._client = None
        self._buffer = None
        self._capture_thread = None
        self._stop_capture = threading.Event()
        self._cancel_requested = False
        self._started_at = None
        self._elapsed_final = 0.0

    # ---- questions ----------------------------------------------------

    def add_question(self, question):
        question = question.strip()
        with self._lock:
            if not question or question in self.questions:
                return False
            self.questions.append(question)
            analyzer = self._analyzer if self._is_running() else None
        if analyzer is not None:
            analyzer.add_question(question)
        return True

    def remove_question(self, question):
        with self._lock:
            if question not in self.questions:
                return False
            self.questions.remove(question)
            analyzer = self._analyzer if self._is_running() else None
        if analyzer is not None:
            analyzer.remove_question(question)
        return True

    def replace_questions(self, questions):
        """Replace the whole list (only while no session is running)."""
        with self._lock:
            if self.state != IDLE:
                return False
            cleaned = []
            for question in questions:
                question = str(question).strip()
                if question and question not in cleaned:
                    cleaned.append(question)
            self.questions = cleaned
            return True

    def _is_running(self):
        return self.state in (LOADING, LISTENING)

    # ---- start --------------------------------------------------------

    def start(self):
        with self._lock:
            if self.state != IDLE:
                raise RuntimeError("A session is already running.")
            self.state = LOADING
            self.error = None
            self.warning = None
            self._cancel_requested = False
            self._elapsed_final = 0.0
            self._buffer = None
            self._analyzer = None
            self._worker = None

        threading.Thread(target=self._start_worker, daemon=True).start()

    def _start_worker(self):
        worker = analyzer = client = capture = None
        try:
            model = self._model_loader()

            stamp = time.strftime("%Y%m%d_%H%M%S")
            transcript = self._output_dir / f"live_transcript_{stamp}.txt"
            report = self._output_dir / f"live_report_{stamp}.txt"
            transcript.write_text("", encoding="utf-8")

            worker = LL.TranscriptionWorker(model, transcript)
            worker.start()

            client = self._client_factory()
            if client is None:
                self.warning = (
                    "GEMINI_API_KEY bulunamadı: yazıya çevirme çalışır ama "
                    "cevaplar bulunamaz."
                )
            else:
                options = {}
                if self._analysis_interval is not None:
                    options["interval"] = self._analysis_interval
                with self._lock:
                    questions = list(self.questions)
                analyzer = LiveAnalyzer(
                    client, questions, transcript, report, **options
                )
                analyzer.start()

            raw_queue = queue.Queue()
            capture = self._capture_factory(raw_queue)
            capture.open()

        except Exception as error:
            self._abort_start(worker, analyzer, client, capture, error)
            return

        with self._lock:
            self.transcript_path = transcript
            self.report_path = report
            self._worker = worker
            self._analyzer = analyzer
            self._client = client
            self._started_at = time.monotonic()
            self._stop_capture.clear()
            self._capture_thread = threading.Thread(
                target=self._capture_loop,
                args=(capture, raw_queue, worker),
                daemon=True,
            )
            self.state = LISTENING
            cancel = self._cancel_requested

        self._capture_thread.start()

        if cancel:   # Stop was pressed while the model was still loading
            self.stop()

    def _abort_start(self, worker, analyzer, client, capture, error):
        if capture is not None:
            try:
                capture.close()
            except Exception:
                pass
        if worker is not None:
            worker.finish()
        if analyzer is not None:
            analyzer.stop()
            analyzer.join(10)
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

        with self._lock:
            self.state = IDLE
            self.error = f"{type(error).__name__}: {error}"

    # ---- capture loop ---------------------------------------------------

    def _capture_loop(self, capture, raw_queue, worker):
        buffer = LL.ChunkBuffer()
        self._buffer = buffer
        started = self._started_at
        last_data = time.monotonic()

        try:
            while not self._stop_capture.is_set():
                try:
                    arrival, data = raw_queue.get(timeout=0.5)
                except queue.Empty:
                    # Loopback sends nothing during total silence.
                    if time.monotonic() - last_data >= LL.IDLE_FLUSH_SECONDS:
                        leftover = buffer.flush()
                        if leftover:
                            worker.submit(*leftover)
                    continue

                last_data = arrival
                samples = LL.to_mono_16k(
                    data, capture.channels, capture.rate
                )
                start = max(
                    0.0,
                    arrival - started - len(samples) / LL.TARGET_RATE,
                )
                ready = buffer.add(start, samples)
                if ready:
                    worker.submit(*ready)

        except Exception as error:
            with self._lock:
                self.error = f"{type(error).__name__}: {error}"
        finally:
            try:
                capture.close()
            except Exception:
                pass
            leftover = buffer.flush()
            if leftover:
                worker.submit(*leftover)

    # ---- stop -----------------------------------------------------------

    def stop(self):
        """Begin stopping. Returns False if there is nothing to stop."""
        with self._lock:
            if self.state == LOADING:
                self._cancel_requested = True
                return True
            if self.state != LISTENING:
                return False
            self.state = STOPPING

        threading.Thread(target=self._stop_worker, daemon=True).start()
        return True

    def _stop_worker(self):
        try:
            self._stop_capture.set()
            if self._capture_thread is not None:
                self._capture_thread.join(10)

            worker = self._worker
            worker.finish()
            while worker.is_alive():
                worker.join(1.0)

            with self._lock:
                self.state = ANALYZING

            if self._analyzer is not None:
                self._analyzer.stop()
                self._analyzer.join()

        except Exception as error:
            with self._lock:
                self.error = f"{type(error).__name__}: {error}"
        finally:
            if self._client is not None:
                try:
                    self._client.close()
                except Exception:
                    pass
            with self._lock:
                if self._started_at is not None:
                    self._elapsed_final = time.monotonic() - self._started_at
                self.state = IDLE

    # ---- information for the interface ----------------------------------

    def _recent_lines(self):
        if self.transcript_path is None:
            return []
        try:
            text = self.transcript_path.read_text(encoding="utf-8")
        except OSError:
            return []
        lines = [line for line in text.splitlines() if line.strip()]
        return lines[-RECENT_LINES:]

    def snapshot(self):
        with self._lock:
            state = self.state
            worker = self._worker
            analyzer = self._analyzer
            buffer = self._buffer
            questions = list(self.questions)
            error = self.error
            warning = self.warning
            transcript = self.transcript_path
            report = self.report_path

            if state == LISTENING and self._started_at is not None:
                elapsed = time.monotonic() - self._started_at
            elif state in (STOPPING, ANALYZING):
                elapsed = time.monotonic() - (self._started_at or 0)
            else:
                elapsed = self._elapsed_final

        last_error = None
        if worker is not None and worker.last_error:
            last_error = worker.last_error
        if analyzer is not None and analyzer.last_error:
            last_error = analyzer.last_error

        return {
            "state": state,
            "error": error,
            "warning": warning,
            "last_error": last_error,
            "elapsed": round(elapsed, 1),
            "buffered": round(buffer.seconds, 1) if buffer else 0.0,
            "pending": worker.pending if worker else 0,
            "lines": worker.line_count if worker else 0,
            "questions": questions,
            "answers": analyzer.answers_snapshot() if analyzer else [],
            "analysis_enabled": analyzer is not None,
            "recent_lines": self._recent_lines(),
            "transcript_file": transcript.name if transcript else None,
            "report_file": (
                report.name if report and report.exists() else None
            ),
        }

    def report_text(self):
        """Text of the last finished report, or None."""
        with self._lock:
            report = self.report_path
            if self.state != IDLE or report is None or not report.exists():
                return None
        return report.read_text(encoding="utf-8")
