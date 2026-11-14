"""Step 2a: test system-audio (speaker loopback) capture on Windows.

Setup (once):
    pip install PyAudioWPatch numpy

Usage:
    1. Start playing any sound (a YouTube video, music, a Zoom call...).
    2. Run:  python test_loopback.py
    3. It records 10 seconds of what comes out of your speakers and saves
       test_loopback.wav in this folder.

Optional: python test_loopback.py 20   (records 20 seconds)
"""

import sys
import time
import wave

import numpy as np
import pyaudiowpatch as pyaudio

OUTPUT_FILE = "test_loopback.wav"
DEFAULT_SECONDS = 10


def find_default_loopback(p):
    """Return the loopback device that mirrors the default speakers."""
    wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
    speakers = p.get_device_info_by_index(wasapi["defaultOutputDevice"])

    if speakers.get("isLoopbackDevice"):
        return speakers

    for loopback in p.get_loopback_device_info_generator():
        if speakers["name"] in loopback["name"]:
            return loopback

    raise RuntimeError(
        "No loopback device was found for your default speakers. "
        "Make sure your speakers/headphones are the Windows default output."
    )


def main():
    seconds = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SECONDS
    frames = []

    with pyaudio.PyAudio() as p:
        device = find_default_loopback(p)
        channels = int(device["maxInputChannels"])
        rate = int(device["defaultSampleRate"])

        print(f"Device : {device['name']}")
        print(f"Format : {channels} channel(s), {rate} Hz")
        print(f"Recording {seconds} seconds... (make sure sound is playing)")

        # Callback mode: loopback delivers nothing during total silence,
        # so a blocking read could wait forever.
        def callback(in_data, frame_count, time_info, status):
            frames.append(in_data)
            return (None, pyaudio.paContinue)

        with p.open(
            format=pyaudio.paInt16,
            channels=channels,
            rate=rate,
            input=True,
            input_device_index=device["index"],
            frames_per_buffer=1024,
            stream_callback=callback,
        ):
            time.sleep(seconds)

    audio = b"".join(frames)

    if not audio:
        print("\nNo audio data was received. Is anything playing?")
        return

    with wave.open(OUTPUT_FILE, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)  # 16-bit
        wav.setframerate(rate)
        wav.writeframes(audio)

    samples = np.frombuffer(audio, dtype=np.int16)
    peak = float(np.abs(samples).max()) / 32768.0

    print(f"\nSaved: {OUTPUT_FILE}  ({len(samples) / channels / rate:.1f} s)")
    print(f"Peak level: {peak:.2f}  (0.00 = silence, 1.00 = maximum)")

    if peak < 0.01:
        print("The recording is almost silent. Play something louder and retry.")
    else:
        print("Sound was captured. You can now open the file to check it.")


if __name__ == "__main__":
    main()
