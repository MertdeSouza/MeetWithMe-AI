# MeetWithMe AI

MeetWithMe AI listens to the audio playing on your computer (for example a Zoom meeting), transcribes it live and checks it against questions that you define. Every answer comes with a word-for-word quote from the transcript, a timestamp and a speaker label. If the transcript does not support an answer, there is no answer.

> **Status: early development.** Read the [Status](#status) section to see what is implemented, what has been tested and what is only planned.

## What it does

- **Live listening.** Captures the sound that comes out of your speakers or headphones (Windows WASAPI loopback) and transcribes it in short pieces with [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper). The language is detected automatically.
- **Question tracking.** Every few minutes the new speech is checked against your questions with Google Gemini. An answer is only accepted if the quote really appears in the transcript, on the line with the reported timestamp and speaker.
- **Questions you control.** Add, remove and save questions in a local web interface. A question added during a meeting is checked against everything said so far.
- **Report.** When you stop, a report with all verified answers is written.
- **File mode.** Analyze a recorded audio file, including speaker separation with [pyannote.audio](https://github.com/pyannote/pyannote-audio).

## Important: this is not a Zoom bot

MeetWithMe AI does **not** join a meeting as a participant. It listens to what your computer plays. You join your meeting normally, and the program listens next to it. Joining as a separate participant (Zoom RTMS or Meeting SDK) is not implemented.

## Status

| Feature | State |
|---|---|
| Live capture of speaker output (Windows) | Implemented, tested with audio and videos playing on the computer |
| Live transcription, automatic language detection | Implemented, tested the same way |
| Question tracking with verified answers | Implemented, tested the same way |
| Local web interface (questions, sets, start/stop, answers) | Implemented, tested |
| File mode (`main.py`) with speaker separation | Implemented, tested |
| A real Zoom meeting (about 54 minutes of Turkish speech) | Tested once by the author: transcript and report were produced |
| Transcription speed on slow computers | **Not tested yet** |
| Speaker names in live mode | Not implemented, every line is labelled `Unknown` |
| Your own microphone | Not implemented, only what comes out of the speakers is captured |
| Voice answers in the meeting | Not implemented |
| Joining as a separate participant (RTMS / Meeting SDK) | Not implemented |
| macOS / Linux live capture | Not implemented, live capture is Windows only |

## Requirements

- Windows 10 or 11 (for live mode)
- Python 3.11
- A Google Gemini API key (get one from Google AI Studio)
- Internet access (Gemini, and a one-time download of the Whisper model on first use)
- For file mode only: a Hugging Face token with accepted terms for the pyannote model, and FFmpeg

## Quick start (Windows)

1. Install [Python 3.11](https://www.python.org/downloads/) and tick **Add python.exe to PATH** during setup.
2. Download this repository (**Code → Download ZIP**) and extract it.
3. Double-click `setup.bat`. It creates a virtual environment, installs the packages and opens a `.env` file. Type your key after `GEMINI_API_KEY=` and save.
4. Double-click `start.bat`. The interface opens in your browser.

### Manual install

```
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements-live.txt
```

Create a file named `.env` next to `app.py` containing:

```
GEMINI_API_KEY=your_key_here
```

Never commit this file. It is listed in `.gitignore`.

## Usage

### Web interface

```
python app.py
```

Open http://127.0.0.1:5000 (it opens automatically). To use another port, set the `MEETWITHME_PORT` environment variable.

1. Add your questions, or load a saved set.
2. Press **Başlat** (Start).
3. Join your meeting or play audio. Make sure the sound comes out of your default Windows output device.
4. Answers appear as they are found. The first check happens after about three minutes, and a newly added question is checked right away.
5. Press **Durdur** (Stop). **Always stop before closing the window**, otherwise the report is not written.

The page is only reachable from your own computer.

### Output files

Each session creates two files in the project folder (both are ignored by git):

- `live_transcript_<date>_<time>.txt` – the transcript, one line per utterance: `[12.4s] [Unknown] text`
- `live_report_<date>_<time>.txt` – the question report

No audio is saved.

### Questions

Questions are plain text, one per line. Lines starting with `#` are ignored. `questions.txt` is the default set. Sets saved in the interface are stored in the `questions/` folder.

### Terminal version

```
python live_listen.py
```

Does the same without the browser. Stop it with Ctrl+C.

### File mode

Analyzes a recorded audio file and separates speakers. It needs the full `requirements.txt`, FFmpeg, and `HF_TOKEN` in your `.env`.

```
pip install -r requirements.txt
python main.py
```

## Configuration

| Setting | Where |
|---|---|
| `GEMINI_API_KEY`, `HF_TOKEN` | `.env` |
| Gemini model (`MODEL_NAME`) | `ai_analyzer.py` |
| Whisper model size, device, silence thresholds | top of `live_listen.py` |
| How often new speech is checked (`ANALYSIS_INTERVAL_SECONDS`) | top of `live_analysis.py` |

## Troubleshooting

- **Gemini returns 503 ("high demand").** The model is temporarily overloaded. The program retries with growing pauses. Run `python tests/test_models.py` to see which models answer right now, then set `MODEL_NAME` in `ai_analyzer.py`.
- **Nothing is transcribed.** Check that sound is really playing through your default output device. If the lines pile up ("waiting" keeps growing in the terminal version), the computer is too slow for the `small` Whisper model. Try `base`.
- **A pause never ends a piece.** Background music keeps the level high. Increase `SILENCE_RMS` in `live_listen.py`.

## Privacy and consent

- Audio is processed on your computer and is not saved.
- The **transcript text is sent to Google's Gemini API** for analysis. Check Google's terms and data policy before using confidential material.
- The program does not announce itself in the meeting. **Tell everyone in the meeting that it is being transcribed**, and make sure you are allowed to do so. Laws and company rules differ.
- The transcript and report files contain meeting content. Keep them private.

## Known limitations

- Live capture works on Windows only.
- Your own voice (microphone) is not captured.
- All speakers are labelled `Unknown` in live mode.
- If Gemini rewrites a question heavily, its answer is dropped instead of being filed under the wrong question.
- Transcription quality depends on the audio. Music, echo and overlapping speakers lower it.
- Names and foreign terms are often misheard (for example university names and exam names). The quoted evidence matches the transcript, not necessarily the real spelling.
- Only the quoted evidence is verified word for word. The answer text can say more than the quote shows, and the confidence labels are not reliable. Check important facts against the quote.

## Project structure

| File | Purpose |
|---|---|
| `app.py` | Local web interface |
| `live_session.py` | Start/stop controllable live session |
| `live_listen.py` | Live capture and transcription (also the terminal version) |
| `live_analysis.py` | Question sets and continuous question tracking |
| `ai_analyzer.py` | Gemini calls and answer verification |
| `main.py` | File mode |
| `speaker_detector.py` | Speaker separation (pyannote) for file mode |
| `ffmpeg_setup.py` | FFmpeg detection for file mode |
| `setup.bat`, `start.bat` | Windows setup and start scripts |
| `tests/test_models.py` | Checks which Gemini models answer right now |

## Roadmap

Planned, not implemented:

- Speaker separation in live mode
- Capturing your own microphone
- A participant mode through Zoom's official APIs
- Voice answers
- English/Turkish interface switch
- A packaged `.exe`

## License

See the `LICENSE` file.

## Built with

[Faster-Whisper](https://github.com/SYSTRAN/faster-whisper), [pyannote.audio](https://github.com/pyannote/pyannote-audio), [Google Gemini](https://ai.google.dev/), [Flask](https://flask.palletsprojects.com/) and [PyAudioWPatch](https://github.com/s0d3s/PyAudioWPatch).