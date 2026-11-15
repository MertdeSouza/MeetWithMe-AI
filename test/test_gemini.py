"""Quick Gemini connectivity test for MeetWithMe AI.

Put this file in the project folder (next to ai_analyzer.py) and run:

    python test_gemini.py

It sends only a tiny test prompt (no meeting data) and tells you:
  1. which Flash model names your API key can use,
  2. whether the model in ai_analyzer.py answers through the same call
     the project uses (client.interactions.create),
  3. whether the same model answers through the standard call
     (client.models.generate_content).

Each request gets 60 seconds. If nothing comes back, the script says so
instead of waiting forever.
"""

import os
import threading
import time

from dotenv import load_dotenv
from google import genai

import ai_analyzer

TIMEOUT_SECONDS = 60


def run_with_timeout(label, func):
    """Run func in a background thread and report what happens."""
    result = {}

    def worker():
        try:
            result["value"] = func()
        except Exception as error:  # noqa: BLE001 - we want to show any error
            result["error"] = error

    started = time.time()
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(TIMEOUT_SECONDS)
    elapsed = time.time() - started

    if thread.is_alive():
        print(f"[{label}] NO RESPONSE after {TIMEOUT_SECONDS}s "
              "(the request is hanging)")
        return None

    if "error" in result:
        error = result["error"]
        print(f"[{label}] FAILED after {elapsed:.1f}s")
        print(f"    type: {type(error).__name__}")
        print(f"    message: {error}")
        print(f"    code attribute: {getattr(error, 'code', None)}")
        return None

    print(f"[{label}] OK in {elapsed:.1f}s")
    return result["value"]


def main():
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        print("GEMINI_API_KEY was not found in your .env file.")
        return

    client = genai.Client(api_key=api_key)
    model = ai_analyzer.MODEL_NAME
    print(f"Model in ai_analyzer.py: {model}\n")

    # 1) Which models can this key see?
    print("--- 1) Flash models available to your key ---")

    def list_models():
        return [m.name for m in client.models.list()]

    names = run_with_timeout("list models", list_models)
    if names:
        flash = sorted(n for n in names if "flash" in n.lower())
        for name in flash:
            print("   ", name)
        if not flash:
            print("    (no model with 'flash' in its name was returned)")
        if not any(model in n for n in names):
            print(f"\n    WARNING: '{model}' is not in the list above.")

    # 2) The call the project uses
    print("\n--- 2) Project call: client.interactions.create ---")

    def project_call():
        return client.interactions.create(
            model=model,
            input="Reply with the single word OK.",
        )

    response = run_with_timeout("interactions.create", project_call)
    if response is not None:
        print("    answer:", getattr(response, "output_text", response))

    # 3) The standard call
    print("\n--- 3) Standard call: client.models.generate_content ---")

    def standard_call():
        return client.models.generate_content(
            model=model,
            contents="Reply with the single word OK.",
        )

    response = run_with_timeout("generate_content", standard_call)
    if response is not None:
        print("    answer:", response.text)

    client.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
