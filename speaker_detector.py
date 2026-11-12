
import os
from pathlib import Path

import torch
from dotenv import load_dotenv
from pyannote.audio import Pipeline


MODEL_NAME = "pyannote/speaker-diarization-community-1"


def load_diarization_model():
    """Load the pretrained speaker diarization model."""

    load_dotenv()

    hf_token = os.getenv("HF_TOKEN")

    if not hf_token:
        raise ValueError(
            "HF_TOKEN was not found in the environment."
        )

    pipeline = Pipeline.from_pretrained(
        MODEL_NAME,
        token=hf_token
    )

    if pipeline is None:
        raise RuntimeError(
            "Failed to load the diarization model."
        )

    device = (
        torch.device("cuda")
        if torch.cuda.is_available()
        else torch.device("cpu")
    )

    pipeline.to(device)

    print(f"Diarization model loaded on: {device}")

    return pipeline


def detect_speakers(audio_path):
    """Detect speakers and their speaking intervals."""

    audio_path = Path(audio_path)

    if not audio_path.is_file():
        raise FileNotFoundError(
            f"Audio file not found: {audio_path}"
        )

    pipeline = load_diarization_model()

    print("Detecting speakers...")

    output = pipeline(str(audio_path))

    # Support both current and older pipeline outputs.
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

    print(
        f"Detected {len(set(item['speaker'] for item in speaker_segments))} "
        "unique speakers."
    )

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
