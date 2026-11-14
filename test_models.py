"""Find out which Gemini text models answer right now.

Put this file in the project folder and run:

    python test_models.py

It sends a tiny test prompt (no meeting data) to every Flash text model
your key can see, using BOTH calls:
  - generate_content    (standard call)
  - interactions.create (the call ai_analyzer.py uses)
All requests run at the same time, so it finishes in about a minute.
"""

import os
import threading
import time

from dotenv import load_dotenv
from google import genai

TIMEOUT_SECONDS = 45
SKIP_WORDS = ("image", "omni", "preview", "live", "tts", "audio", "embedding")


def timed_call(func, results, key):
    """Run func and store a short status string in results[key]."""
    started = time.time()
    try:
        func()
        results[key] = f"OK ({time.time() - started:.1f}s)"
    except Exception as error:  # noqa: BLE001
        code = getattr(error, "code", None)
        results[key] = f"ERROR {code or type(error).__name__}"


def main():
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY was not found in your .env file.")
        return

    client = genai.Client(api_key=api_key)

    models = sorted(
        m.name.replace("models/", "")
        for m in client.models.list()
        if "flash" in m.name.lower()
        and not any(word in m.name.lower() for word in SKIP_WORDS)
    )
    print(f"Testing {len(models)} models (up to {TIMEOUT_SECONDS}s)...\n")

    results = {}
    threads = []
    prompt = "Reply with the single word OK."

    for name in models:
        calls = {
            "generate": lambda n=name: client.models.generate_content(
                model=n, contents=prompt
            ),
            "interactions": lambda n=name: client.interactions.create(
                model=n, input=prompt
            ),
        }
        for kind, func in calls.items():
            key = (name, kind)
            thread = threading.Thread(
                target=timed_call, args=(func, results, key), daemon=True
            )
            thread.start()
            threads.append(thread)

    deadline = time.time() + TIMEOUT_SECONDS
    for thread in threads:
        thread.join(max(0.0, deadline - time.time()))

    print(f"{'MODEL':<28}{'generate_content':<22}{'interactions.create'}")
    print("-" * 70)
    for name in models:
        generate = results.get((name, "generate"), "NO RESPONSE")
        interactions = results.get((name, "interactions"), "NO RESPONSE")
        print(f"{name:<28}{generate:<22}{interactions}")

    print("\nA model with OK in the last column works with the project as-is.")
    os._exit(0)  # do not wait for requests that are still hanging


if __name__ == "__main__":
    main()
