"""Live listening (steps 2b + 3).

Captures what comes out of your speakers (e.g. a Zoom meeting), cuts it into
short pieces at natural pauses, transcribes each piece with Faster-Whisper
and appends the lines to a text file while the meeting is running.

While you listen, every few minutes the NEW speech is checked against your
questions with Gemini. When an answer is found (and verified word for word
against the transcript) it is announced in the terminal. When you stop, a
full report is written.

Usage:
    python live_listen.py

Stop with Ctrl+C. Files created in this folder:
    live_transcript_<date>_<time>.txt   the transcript (speaker = "Unknown")
    live_report_<date>_<time>.txt       the question report

No audio is saved. The transcript is not printed to the terminal.
"""

import os
import queue
import sys
import threading
import time
from pathlib import Path

import numpy as np

from live_analysis import (
    LiveAnalyzer,
    choose_questions,
    format_notification,
)

# ==========================================
# SETTINGS
# ==========================================

TARGET_RATE = 16000            # Whisper expects 16 kHz mono

WHISPER_MODEL = "small"
WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE_TYPE = "int8"
LANGUAGE = None                # None = detect automatically for every piece
BEAM_SIZE = 1                  # 1 = fastest; raise to 5 for slightly better text

MIN_CHUNK_SECONDS = 6.0        # do not cut before this much audio
MAX_CHUNK_SECONDS = 25.0       # always cut at this length
SILENCE_SECONDS = 0.6          # a pause this long ends a piece
SILENCE_RMS = 0.01             # below this level = pause (raise if cuts never happen)
SPEECH_RMS = 0.003             # a whole piece quieter than this is skipped
IDLE_FLUSH_SECONDS = 1.0       # no audio arriving this long = flush what we have

ENABLE_LIVE_ANALYSIS = True    # False = transcription only, no Gemini


# ==========================================
# AUDIO HELPERS (no hardware needed)
# ==========================================

def rms(audio):
    """Root-mean-square level of float audio (0.0 = silence)."""
    if len(audio) == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(audio))))


def to_mono_16k(raw, channels, rate):
    """Convert raw 16-bit PCM bytes to mono float32 at 16 kHz."""
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

    usable = len(samples) - len(samples) % channels
    samples = samples[:usable].reshape(-1, channels).mean(axis=1)

    if rate == TARGET_RATE:
        return samples

    if rate % TARGET_RATE == 0:
        # Exact ratio (e.g. 48000 -> 16000): average groups of samples.
        factor = rate // TARGET_RATE
        usable = len(samples) - len(samples) % factor
        return samples[:usable].reshape(-1, factor).mean(axis=1)

    target_length = int(len(samples) * TARGET_RATE / rate)
    if target_length == 0:
        return np.zeros(0, dtype=np.float32)

    positions = np.linspace(0, len(samples) - 1, target_length)
    return np.interp(
        positions, np.arange(len(samples)), samples
    ).astype(np.float32)


class ChunkBuffer:
    """Collects audio and releases a piece at a natural pause."""

    def __init__(self):
        self._parts = []
        self._sample_count = 0
        self._start = None

    @property
    def seconds(self):
        return self._sample_count / TARGET_RATE

    def add(self, start_time, samples):
        """Add audio. Returns (start_time, audio) when a piece is ready."""
        if len(samples) == 0:
            return None

        if self._start is None:
            self._start = start_time

        self._parts.append(samples)
        self._sample_count += len(samples)

        if self._is_ready():
            return self._take()
        return None

    def flush(self):
        """Release whatever is buffered (or None if empty)."""
        if not self._parts:
            return None
        return self._take()

    def _tail_is_silent(self):
        needed = int(SILENCE_SECONDS * TARGET_RATE)
        tail = []
        count = 0

        for part in reversed(self._parts):
            tail.append(part)
            count += len(part)
            if count >= needed:
                break

        if count < needed:
            return False

        audio = np.concatenate(tail[::-1])[-needed:]
        return rms(audio) < SILENCE_RMS

    def _is_ready(self):
        if self.seconds >= MAX_CHUNK_SECONDS:
            return True
        return self.seconds >= MIN_CHUNK_SECONDS and self._tail_is_silent()

    def _take(self):
        audio = np.concatenate(self._parts)
        start = self._start
        self._parts = []
        self._sample_count = 0
        self._start = None
        return start, audio


# ==========================================
# TRANSCRIPTION WORKER
# ==========================================

class TranscriptionWorker(threading.Thread):
    """Transcribes pieces in the background so capture never stalls."""

    def __init__(self, model, output_path, language=LANGUAGE):
        super().__init__(daemon=True)
        self.model = model
        self.output_path = Path(output_path)
        self.language = language
        self._jobs = queue.Queue()
        self.line_count = 0
        self.error_count = 0
        self.last_error = None

    @property
    def pending(self):
        return self._jobs.qsize()

    def submit(self, start_time, audio):
        self._jobs.put((start_time, audio))

    def finish(self):
        """Ask the worker to stop after the queued pieces."""
        self._jobs.put(None)

    def run(self):
        while True:
            job = self._jobs.get()
            if job is None:
                break
            start_time, audio = job
            try:
                self._transcribe(start_time, audio)
            except Exception as error:  # keep listening whatever happens
                self.error_count += 1
                self.last_error = f"{type(error).__name__}: {error}"

    def _transcribe(self, offset, audio):
        if rms(audio) < SPEECH_RMS:
            return  # nothing but silence

        segments, _info = self.model.transcribe(
            audio,
            language=self.language,
            beam_size=BEAM_SIZE,
            vad_filter=True,
        )

        lines = []
        for segment in segments:
            text = " ".join(segment.text.split())
            if text:
                lines.append(
                    f"[{offset + segment.start:.1f}s] [Unknown] {text}"
                )

        if lines:
            with self.output_path.open("a", encoding="utf-8") as file:
                file.write("\n".join(lines) + "\n")
            self.line_count += len(lines)


# ==========================================
# CAPTURE (Windows only)
# ==========================================

def find_default_loopback(p, pyaudio):
    """Return the loopback device that mirrors the default speakers."""
    wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
    speakers = p.get_device_info_by_index(wasapi["defaultOutputDevice"])

    if speakers.get("isLoopbackDevice"):
        return speakers

    for loopback in p.get_loopback_device_info_generator():
        if speakers["name"] in loopback["name"]:
            return loopback

    raise RuntimeError(
        "No loopback device was found for your default speakers."
    )


def format_clock(seconds):
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes:02d}:{secs:02d}"


def show_status(started, buffer, worker, analyzer):
    answers = analyzer.answer_count if analyzer else "-"
    sys.stdout.write(
        f"\rListening {format_clock(time.monotonic() - started)}"
        f" | buffered {buffer.seconds:4.1f}s"
        f" | waiting {worker.pending}"
        f" | lines {worker.line_count}"
        f" | answers {answers}"
        f" | errors {worker.error_count}   "
    )
    sys.stdout.flush()


def print_notifications(analyzer):
    """Show answers found by the background analysis."""
    if analyzer is None:
        return

    while True:
        try:
            question, item = analyzer.notifications.get_nowait()
        except queue.Empty:
            break
        sys.stdout.write("\r" + " " * 100 + "\r")
        print(format_notification(question, item) + "\n")


def start_analyzer(questions, transcript_path, report_path):
    """Create the Gemini client and start the background analysis."""
    from dotenv import load_dotenv

    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        print(
            "GEMINI_API_KEY was not found: live answers are turned off "
            "(transcription still works).\n"
        )
        return None, None

    from google import genai

    client = genai.Client(api_key=api_key)
    analyzer = LiveAnalyzer(client, questions, transcript_path, report_path)
    analyzer.start()
    return client, analyzer


def main():
    questions = []
    if ENABLE_LIVE_ANALYSIS:
        questions_file, questions = choose_questions()
        print(f"Questions: {questions_file} ({len(questions)} questions)\n")

    import pyaudiowpatch as pyaudio
    from faster_whisper import WhisperModel

    print("Loading Whisper model (first run may download it)...")
    model = WhisperModel(
        WHISPER_MODEL,
        device=WHISPER_DEVICE,
        compute_type=WHISPER_COMPUTE_TYPE,
    )

    stamp = time.strftime("%Y%m%d_%H%M%S")
    output_path = Path(f"live_transcript_{stamp}.txt")
    report_path = Path(f"live_report_{stamp}.txt")
    output_path.write_text("", encoding="utf-8")

    worker = TranscriptionWorker(model, output_path)
    worker.start()

    client, analyzer = None, None
    if ENABLE_LIVE_ANALYSIS:
        client, analyzer = start_analyzer(questions, output_path, report_path)

    buffer = ChunkBuffer()
    raw_chunks = queue.Queue()

    with pyaudio.PyAudio() as p:
        device = find_default_loopback(p, pyaudio)
        channels = int(device["maxInputChannels"])
        rate = int(device["defaultSampleRate"])

        print(f"Device : {device['name']} ({channels} ch, {rate} Hz)")
        print(f"Saving : {output_path}")
        print("Listening... press Ctrl+C to stop.\n")

        def callback(in_data, frame_count, time_info, status):
            raw_chunks.put((time.monotonic(), in_data))
            return (None, pyaudio.paContinue)

        started = time.monotonic()
        last_data = started
        last_status = 0.0

        stream = p.open(
            format=pyaudio.paInt16,
            channels=channels,
            rate=rate,
            input=True,
            input_device_index=device["index"],
            frames_per_buffer=960,
            stream_callback=callback,
        )

        try:
            while True:
                try:
                    arrival, data = raw_chunks.get(timeout=0.5)
                except queue.Empty:
                    # Loopback sends nothing during total silence.
                    idle = time.monotonic() - last_data
                    if idle >= IDLE_FLUSH_SECONDS:
                        leftover = buffer.flush()
                        if leftover:
                            worker.submit(*leftover)
                    arrival = None

                if arrival is not None:
                    last_data = arrival
                    samples = to_mono_16k(data, channels, rate)
                    start = max(
                        0.0,
                        arrival - started - len(samples) / TARGET_RATE,
                    )
                    ready = buffer.add(start, samples)
                    if ready:
                        worker.submit(*ready)

                print_notifications(analyzer)

                now = time.monotonic()
                if now - last_status >= 1.0:
                    show_status(started, buffer, worker, analyzer)
                    last_status = now

        except KeyboardInterrupt:
            pass
        finally:
            stream.stop_stream()
            stream.close()

    print("\n\nStopping... finishing the remaining pieces.")

    leftover = buffer.flush()
    if leftover:
        worker.submit(*leftover)
    worker.finish()

    try:
        while worker.is_alive():
            worker.join(timeout=1.0)
            print(f"  waiting for {worker.pending} piece(s)...", end="\r")
    except KeyboardInterrupt:
        print("\nStopped early; some audio was not transcribed.")

    print(f"\nTranscript: {output_path} ({worker.line_count} lines)")
    if worker.error_count:
        print(
            f"{worker.error_count} piece(s) failed. "
            f"Last error: {worker.last_error}"
        )

    if analyzer is not None:
        print("\nRunning the final analysis (Ctrl+C skips it)...")
        analyzer.stop()
        try:
            analyzer.join()
        except KeyboardInterrupt:
            print("Skipped; writing the report with what was found so far.")
            analyzer.write_report()

        print_notifications(analyzer)
        print(f"\nReport: {report_path} ({analyzer.answer_count} answers)")
        if analyzer.last_error:
            print(f"Some analysis steps failed. Last error: {analyzer.last_error}")
        client.close()


if __name__ == "__main__":
    main()
