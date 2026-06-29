#!/usr/bin/env python3
"""
generate_narration.py — Pre-generate narration via Ollama and cache to JSON.

Run this script ONCE (offline) whenever you change maps or want fresh dialogue.
The game will then load narration_cache.json instantly at startup.

Usage:
    python3 generate_narration.py                     # use default model
    python3 generate_narration.py --model gemma3:4b   # specify model
    python3 generate_narration.py --force              # overwrite existing cache
"""

import argparse
import json
import os
import sys
import time
import requests

# ── Import maps so we know what to generate for ──────────────────────────────
# We avoid importing misty (which needs network) by patching the import
# maps.py imports misty.turn_180 at module level, so we stub it out
import types
_stub = types.ModuleType("misty")
_stub.turn_180 = lambda: None
sys.modules["misty"] = _stub

from maps import MAPS, ACTIVE_MAP_ID

# ── Config ────────────────────────────────────────────────────────────────────

OLLAMA_URL         = "http://localhost:11434/api/chat"
DEFAULT_MODEL      = "gemma3:4b"
DEFAULT_VARIATIONS = 10
CACHE_FILE         = os.path.join(os.path.dirname(os.path.abspath(__file__)), "narration_cache.json")

SYSTEM_PROMPT = (
    "You are Misty, a small friendly robot talking to a child (age 6-12) "
    "playing a navigation card game. You speak in short, warm, enthusiastic "
    "sentences - 1 to 2 sentences maximum. Keep language simple and fun. "
    "Do NOT use emojis, markdown, or special formatting - plain spoken text only."
)

# ── Message types to generate per phase ──────────────────────────────────────

MESSAGE_KEYS = ["hint", "success", "wrong_order", "wrong_ids", "returning"]

PROMPT_TEMPLATES = {
    "hint": (
        "It's leg {phase} of {total}. The child needs to navigate me to the {location}. "
        "The path requires these moves: {moves}. "
        "Tell them what cards to place — be encouraging and give a gentle clue about the directions."
    ),
    "success": (
        "The child got the card sequence right for leg {phase}! I'm now heading to the {location}. "
        "Say something excited and encouraging — 1-2 short sentences."
    ),
    "wrong_order": (
        "The child placed the right cards but in the wrong order for getting to the {location} on leg {phase}. "
        "Gently tell them the cards are correct but need rearranging — be encouraging."
    ),
    "wrong_ids": (
        "The child used the wrong cards entirely for navigating to the {location} on leg {phase}. "
        "Encourage them warmly to try different cards — don't make them feel bad."
    ),
    "returning": (
        "I successfully visited the {location} on leg {phase} and now I'm heading back home. "
        "Say something brief and happy about the trip — 1 sentence."
    ),
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _sequence_to_moves(sequence: list[int]) -> str:
    """Convert a card sequence like [1, 2, 1, 3, 1] to human-readable moves."""
    CARD_NAMES = {1: "forward", 2: "left turn", 3: "right turn"}
    return ", ".join(CARD_NAMES.get(c, f"card {c}") for c in sequence)


def _ollama_reachable() -> bool:
    """Return True if the Ollama server is running."""
    try:
        r = requests.get(
            OLLAMA_URL.replace("/api/chat", "/api/tags"), timeout=5
        )
        return r.status_code == 200
    except Exception:
        return False


def _ask(prompt: str, model: str, max_retries: int = 3) -> str:
    """Send a single prompt to Ollama and return the response text.

    Retries on 500 errors with exponential backoff — Ollama often returns 500
    while a model is still loading into GPU/RAM memory.
    """
    import re

    payload = {
        "model":    model,
        "messages": [
            {"role": "system",  "content": SYSTEM_PROMPT},
            {"role": "user",    "content": prompt},
        ],
        "stream": False,
        "options": {
            "temperature": 0.8,
            "num_predict": 80,     # keep responses short
        },
    }

    for attempt in range(1, max_retries + 1):
        try:
            r = requests.post(OLLAMA_URL, json=payload, timeout=180)
            r.raise_for_status()
            text = r.json()["message"]["content"].strip()
            # Strip any <think>...</think> tags some models produce
            text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
            return text
        except requests.exceptions.HTTPError as e:
            if r.status_code == 500 and attempt < max_retries:
                wait = 5 * (2 ** (attempt - 1))   # 5s, 10s, 20s
                print(f"\n      [WAIT] Ollama 500 error (model may still be loading). "
                      f"Retrying in {wait}s... (attempt {attempt}/{max_retries})")
                time.sleep(wait)
            else:
                raise


def generate_for_map(map_id: int, model: str, variations: int = DEFAULT_VARIATIONS) -> dict:
    """Generate narration for all checkpoints in a map.

    Each message key gets `variations` unique lines stored as a list.
    """
    game_map = MAPS[map_id]
    total    = len(game_map.checkpoints)
    result   = {
        "map_id":   map_id,
        "map_name": game_map.name,
        "model":    model,
        "variations_per_key": variations,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "phases":   [],
    }

    for i, cp in enumerate(game_map.checkpoints):
        phase    = i + 1
        location = cp.location
        moves    = _sequence_to_moves(cp.sequence)
        msgs     = {}   # key -> list of variation strings

        print(f"\n  Phase {phase}/{total} -- {location}")

        for key in MESSAGE_KEYS:
            base_prompt = PROMPT_TEMPLATES[key].format(
                phase=phase, total=total, location=location, moves=moves,
            )
            msgs[key] = []
            print(f"    '{key}' [{variations} variations]:", flush=True)

            for v in range(1, variations + 1):
                # Ask for a unique variation each time
                prompt = (
                    base_prompt + f" This is variation {v} of {variations} "
                    f"-- make it sound different from any previous attempts. "
                    f"Be creative and use different words."
                )
                print(f"      {v}/{variations}...", end=" ", flush=True)
                start = time.time()
                try:
                    text = _ask(prompt, model)
                    elapsed = time.time() - start
                    msgs[key].append(text)
                    preview = text[:50] + "..." if len(text) > 50 else text
                    print(f"OK ({elapsed:.1f}s) \"{preview}\"")
                except Exception as e:
                    print(f"FAIL Error: {e}")
                    msgs[key].append(None)

        result["phases"].append({
            "phase":    phase,
            "location": location,
            "sequence": cp.sequence,
            "messages": msgs,
        })

    return result


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Pre-generate game narration via Ollama and cache to JSON."
    )
    parser.add_argument(
        "--model", default=DEFAULT_MODEL,
        help=f"Ollama model to use (default: {DEFAULT_MODEL})"
    )
    parser.add_argument(
        "--map", type=int, default=None,
        help=f"Map ID to generate for (default: all maps with checkpoints)"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite existing cache file"
    )
    parser.add_argument(
        "--variations", type=int, default=DEFAULT_VARIATIONS,
        help=f"Number of variations per message (default: {DEFAULT_VARIATIONS})"
    )
    args = parser.parse_args()

    # -- Pre-flight checks ----------------------------------------------------
    if os.path.exists(CACHE_FILE) and not args.force:
        print(f"Cache file already exists: {CACHE_FILE}")
        print("Use --force to overwrite, or delete it manually.")
        sys.exit(1)

    if not _ollama_reachable():
        print("ERROR: Ollama is not running or not reachable at localhost:11434")
        print("Start it with:  ollama serve")
        sys.exit(1)

    print(f"{'='*60}")
    print(f"  NARRATION PRE-GENERATOR")
    print(f"  Model      : {args.model}")
    print(f"  Variations : {args.variations} per message")
    print(f"  Output     : {CACHE_FILE}")
    print(f"{'='*60}")

    # ── Determine which maps to generate ─────────────────────────────────
    if args.map is not None:
        if args.map not in MAPS:
            print(f"ERROR: Map ID {args.map} not found. Available: {list(MAPS.keys())}")
            sys.exit(1)
        map_ids = [args.map]
    else:
        # Generate for all maps that have checkpoints
        map_ids = [mid for mid, m in MAPS.items() if len(m.checkpoints) > 0]

    # ── Generate ─────────────────────────────────────────────────────────
    all_maps = {}
    total_start = time.time()

    for map_id in map_ids:
        game_map = MAPS[map_id]
        print(f"\n{'-'*60}")
        print(f"  Map {map_id}: {game_map.name} ({len(game_map.checkpoints)} phases)")
        print(f"{'-'*60}")

        map_data = generate_for_map(map_id, args.model, args.variations)
        all_maps[str(map_id)] = map_data

    total_elapsed = time.time() - total_start

    # ── Save cache ───────────────────────────────────────────────────────
    with open(CACHE_FILE, "w") as f:
        json.dump(all_maps, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*60}")
    print(f"  DONE in {total_elapsed:.1f}s")
    print(f"  Saved to: {CACHE_FILE}")
    print(f"{'='*60}")
    print(f"\nThe game will now load narration from the cache instantly.")


if __name__ == "__main__":
    main()
