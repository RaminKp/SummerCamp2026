#!/usr/bin/env python3
"""
generate_narration.py -- Pre-generate INTRO narration via Ollama and cache it.

Only generates the welcome / how-to-play / good-luck messages spoken once at
game start.  Per-checkpoint messages (hint, success, wrong, returning) are
generated live during the game by narrator.py using the same model.

Usage:
    python3 generate_narration.py
    python3 generate_narration.py --force
    python3 generate_narration.py --model qwen3:0.6b --variations 5 --force
"""

import argparse
import json
import os
import re
import sys
import time
import requests

# ── Config ────────────────────────────────────────────────────────────────────

DEFAULT_MODEL  = "qwen3:0.6b"
VARIATIONS     = 3
CACHE_FILE     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "narration_cache.json")
OLLAMA_URL     = "http://localhost:11434/api/chat"

SYSTEM_PROMPT = (
    "You are Misty, a small friendly robot talking to a child aged 6 to 12. "
    "Reply with ONE sentence only — under 12 words. "
    "Simple words, warm and fun. No emojis, no lists, no markdown."
)

# Messages spoken once at the very start of the game.
INTRO_PROMPTS = {
    "welcome": (
        "Welcome the children to Misty Maze. One excited sentence, under 10 words."
    ),
    "how_to_play": (
        "Explain: card 1 forward, card 2 left, card 3 right, then press the button. "
        "One sentence, under 15 words."
    ),
    "good_luck": (
        "Say good luck to start the game. One sentence, under 8 words."
    ),
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ollama_reachable() -> bool:
    try:
        r = requests.get(OLLAMA_URL.replace("/api/chat", "/api/tags"), timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def _ask(prompt: str, model: str, max_retries: int = 3) -> str:
    payload = {
        "model":   model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
        "stream": False,
        "think":  False,   # skip chain-of-thought for qwen3 models
        "options": {
            "temperature": 0.8,
            "num_predict": 80,
        },
    }
    for attempt in range(1, max_retries + 1):
        try:
            r = requests.post(OLLAMA_URL, json=payload, timeout=60)
            r.raise_for_status()
            text = r.json()["message"]["content"].strip()
            # Strip any <think>...</think> blocks some models produce
            text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
            return text
        except requests.exceptions.HTTPError as e:
            if r.status_code == 500 and attempt < max_retries:
                wait = 5 * (2 ** (attempt - 1))
                print(f"      [WAIT] 500 error — retrying in {wait}s... "
                      f"(attempt {attempt}/{max_retries})")
                time.sleep(wait)
            else:
                raise


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Pre-generate intro narration via Ollama and cache to JSON."
    )
    parser.add_argument("--model",      default=DEFAULT_MODEL,
                        help=f"Ollama model (default: {DEFAULT_MODEL})")
    parser.add_argument("--variations", type=int, default=VARIATIONS,
                        help=f"Variations per message (default: {VARIATIONS})")
    parser.add_argument("--force",      action="store_true",
                        help="Overwrite the existing intro section in the cache.")
    args = parser.parse_args()

    # Check if intro already exists
    existing = {}
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass

    if "intro" in existing and not args.force:
        print(f"Intro narration already cached in {CACHE_FILE}.")
        print("Use --force to regenerate it.")
        sys.exit(1)

    if not _ollama_reachable():
        print("ERROR: Ollama not reachable at localhost:11434.")
        print("Start it with:  ollama serve")
        sys.exit(1)

    print(f"{'='*55}")
    print(f"  INTRO NARRATION GENERATOR")
    print(f"  Model      : {args.model}")
    print(f"  Variations : {args.variations} per message")
    print(f"  Output     : {CACHE_FILE}")
    print(f"{'='*55}\n")

    messages = {}
    total_start = time.time()

    for key, prompt in INTRO_PROMPTS.items():
        messages[key] = []
        print(f"  '{key}'  [{args.variations} variations]:")
        for v in range(1, args.variations + 1):
            full_prompt = (
                prompt +
                f" This is variation {v} of {args.variations} — "
                "use different words from any previous attempts."
            )
            print(f"    {v}/{args.variations}...", end=" ", flush=True)
            t0 = time.time()
            try:
                text = _ask(full_prompt, args.model)
                elapsed = time.time() - t0
                preview = text[:55] + "..." if len(text) > 55 else text
                print(f"OK ({elapsed:.1f}s)  \"{preview}\"")
                messages[key].append(text)
            except Exception as e:
                print(f"FAIL ({e})")
                messages[key].append(None)

    existing["intro"] = {
        "model":        args.model,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "messages":     messages,
    }

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    elapsed = time.time() - total_start
    print(f"\n  Done in {elapsed:.1f}s — saved to {CACHE_FILE}")
    print("  The game will speak intro narration from the cache at startup.")
    print("  Per-checkpoint messages are generated live during the game.")


if __name__ == "__main__":
    main()
