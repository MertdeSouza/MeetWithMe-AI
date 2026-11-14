
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import torch
from dotenv import load_dotenv
from pyannote.audio import Pipeline


MODEL_NAME = "pyannote/speaker-diarization-community-1"
SAMPLE_RATE = 16000


def load_diarization_model():
    """Load the pretrained speaker diarization model."""

    load_dotenv()

    hf_token = os.getenv("HF_TOKEN")

    if not hf_token:
        raise ValueError("HF_TOKEN was not found in the environment.")

    pipeline = Pipeline.from_pretrained(
        MODEL_NAME,
        token=hf_token
    )

    if pipeline is None:
        raise RuntimeError("Failed to load the diarization model.")

    device = (
        torch.device("cuda")
        if torch.cuda.is_available()
        else torch.device("cpu")
    )

    pipeline.to(device)

    print(f"Diarization model loaded on: {device}")

    return pipeline


def load_audio_with_ffmpeg(audio_path):
    """Decode audio using FFmpeg instead of TorchCodec."""

    ffmpeg_path = shutil.which("ffmpeg")

    if not ffmpeg_path:
        raise RuntimeError("FFmpeg was not found in PATH.")

    command = [
        ffmpeg_path,
        "-nostdin",
        "-v", "error",
        "-i", str(audio_path),
        "-map", "0:a:0",
        "-vn",
        "-f", "f32le",
        "-acodec", "pcm_f32le",
        "-ac", "1",
        "-ar", str(SAMPLE_RATE),
        "pipe:1"
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        check=False
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"FFmpeg audio decoding failed: "
            f"{result.stderr.decode(errors='replace')}"
        )

    audio_array = np.frombuffer(
        result.stdout,
        dtype=np.float32
    ).copy()

    if audio_array.size == 0:
        raise RuntimeError("FFmpeg returned empty audio.")

    waveform = torch.from_numpy(
        audio_array
    ).unsqueeze(0)

    return {
        "waveform": waveform,
        "sample_rate": SAMPLE_RATE
    }


def detect_speakers(audio_path):
    """Detect speakers and their speaking intervals."""

    audio_path = Path(audio_path)

    if not audio_path.is_file():
        raise FileNotFoundError(
            f"Audio file not found: {audio_path}"
        )

    print("Loading audio with FFmpeg...")

    audio = load_audio_with_ffmpeg(audio_path)

    pipeline = load_diarization_model()

    print("Detecting speakers...")

    output = pipeline(audio)

    diarization = getattr(
        output,
        "speaker_diarization",
        output
    )

    speaker_segments = []

    for turn, _, speaker in diarization.itertracks(
        yield_label=True
    ):
        speaker_segments.append({
            "start": float(turn.start),
            "end": float(turn.end),
            "speaker": str(speaker)
        })

    speaker_segments.sort(
        key=lambda item: item["start"]
    )

    unique_speakers = len({
        item["speaker"] for item in speaker_segments
    })

    print(f"Detected {unique_speakers} unique speakers.")

    return speaker_segments


def assign_speakers(transcript_segments, speaker_segments):
    """Assign speaker labels to Whisper transcript segments."""

    for transcript in transcript_segments:

        transcript_start = transcript["timestamp"]
        transcript_end = transcript["end"]

        best_speaker = "Unknown"
        best_overlap = 0.0

        for speaker in speaker_segments:

            overlap_start = max(
                transcript_start,
                speaker["start"]
            )

            overlap_end = min(
                transcript_end,
                speaker["end"]
            )

            overlap = max(
                0.0,
                overlap_end - overlap_start
            )

            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = speaker["speaker"]

        transcript["speaker"] = best_speaker

    return transcript_segments
