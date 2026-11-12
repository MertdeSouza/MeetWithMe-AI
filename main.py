from pathlib import Path
from faster_whisper import WhisperModel
import re
import ai_analyzer
import speaker_detector
import os
from ffmpeg_setup import setup_ffmpeg

FFMPEG_BIN = r"C:\Users\Mehmet Mert Arslan\Downloads\ffmpeg-9.0.2-essentials_build\ffmpeg-9.0.2-essentials_build\bin"

os.environ["PATH"] = FFMPEG_BIN + os.pathsep + os.environ["PATH"]

if hasattr(os, "add_dll_directory"):
    os.add_dll_directory(FFMPEG_BIN)

# FILE PATHS
QUESTIONS_FILE = Path("questions.txt")
TRANSCRIPT_FILE = Path("transcript.txt")
REPORT_FILE = Path("report.txt")
AI_REPORT_FILE = Path("ai_report.txt")


def load_questions():
    """Load questions from questions.txt."""

    if not QUESTIONS_FILE.exists():
        print("ERROR: questions.txt was not found!")
        return []

    return [
        line.strip()
        for line in QUESTIONS_FILE.read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]


def extract_keywords(text):
    """Extract meaningful keywords from text."""

    stop_words = {
        "and", "or", "with", "for", "the",
        "this", "that", "what", "how", "are",
        "does", "can", "was", "were", "you",
        "your", "have", "has", "not", "but",
        "bir", "ve", "veya", "ile", "icin",
        "için", "bu", "şu", "ne", "nasıl",
        "mi", "mı", "mu", "mü", "da", "de"
    }

    words = re.findall(r"\w+", text.lower())

    return {
        word for word in words
        if len(word) > 2 and word not in stop_words
    }


def find_relevant_answers(segments, questions):
    """Find transcript segments related to each question."""

    results = []

    for question in questions:
        question_keywords = extract_keywords(question)
        matches = []

        if not question_keywords:
            results.append((question, matches))
            continue

        for segment in segments:
            segment_keywords = extract_keywords(
                segment["text"]
            )

            common_keywords = (
                question_keywords & segment_keywords
            )

            score = (
                len(common_keywords) /
                len(question_keywords)
            )

            if score >= 0.25:
                matches.append({
                    "timestamp": segment["timestamp"],
                    "text": segment["text"],
                    "score": score,
                    "speaker": segment.get("speaker", "Unknown")
                })

        matches.sort(
            key=lambda item: item["score"],
            reverse=True
        )

        results.append((question, matches))

    return results


def generate_report(results):
    """Generate a basic transcript-based report."""

    lines = [
        "MEETWITHME",
        "MEETING ANALYSIS REPORT",
        "=" * 40
    ]

    for question, answers in results:
        lines.append(f"\nQUESTION: {question}")
        lines.append("-" * 40)

        if not answers:
            lines.append(
                "No keyword matches were found."
            )
            continue

        for answer in answers[:5]:
            minutes = int(answer["timestamp"] // 60)
            seconds = int(answer["timestamp"] % 60)

            lines.append(
                f"[{minutes:02d}:{seconds:02d}] "
                f"[{answer.get('speaker', 'Unknown')}] {answer['text']}"
            )

    REPORT_FILE.write_text(
        "\n".join(lines),
        encoding="utf-8"
    )

    print("\nBasic report saved.")

    # Run AI analysis
    print("\nStarting Gemini AI analysis...")

    try:
        ai_analyzer.main()

        if AI_REPORT_FILE.exists():
            print("AI report generated successfully!")
        else:
            print("WARNING: AI report was not generated.")

    except Exception as error:
        print(f"Gemini analysis failed: {error}")
        print("The basic report is still available.")


def main():
    """Main application entry point."""

    print("\n=== MEETWITHME AI ===")

    setup_ffmpeg()
    
    audio_path = input(
        "Enter the audio file path: "
    ).strip().strip('"')

    if not Path(audio_path).is_file():
        print("ERROR: Audio file not found!")
        return

    questions = load_questions()

    if not questions:
        print("No questions found for analysis!")
        return

    print("\nLoading Whisper model...")

    model = WhisperModel(
        "small",
        device="cpu",
        compute_type="int8"
    )

    print("\nTranscribing audio...")
    print("Language detection: automatic\n")

    segments, info = model.transcribe(
        audio_path,
        language=None,
        task="transcribe",
        beam_size=5,
        vad_filter=True
    )

    transcript_segments = []

    for segment in segments:
        text = segment.text.strip()

        if not text:
            continue

        transcript_segments.append({
            "timestamp": segment.start,
            "end": segment.end,
            "text": text
        })

        print(
            f"[{segment.start:.1f}s] {text}"
        )


    print("\nStarting speaker diarization...")

    speaker_segments = speaker_detector.detect_speakers(
        audio_path
    )

    transcript_segments = speaker_detector.assign_speakers(
        transcript_segments,
        speaker_segments
    )

    if not transcript_segments:
        print("ERROR: No speech was detected!")
        return

    print(f"\nDetected language: {info.language}")
    print("\nSaving transcript...")

    transcript = "\n".join(
        f"[{item['timestamp']:.1f}s] "
        f"[{item['speaker']}] "
        f"{item['text']}"
        for item in transcript_segments
    )

    TRANSCRIPT_FILE.write_text(
        transcript,
        encoding="utf-8"
    )

    print("Transcript saved successfully.")

    print("\nSearching for relevant answers...")

    results = find_relevant_answers(
        transcript_segments,
        questions
    )

    generate_report(results)

    print("\n" + "=" * 40)
    print("ANALYSIS COMPLETED!")
    print("=" * 40)

    print("\nGenerated files:")
    print("- transcript.txt")
    print("- report.txt")
    print("- ai_report.txt")


if __name__ == "__main__":
    main()
