"""
narrator.py -- Narration for the Misty Maze game.

INTRO  (pre-generated, from narration_cache.json):
    welcome, how_to_play, good_luck — spoken once at game start.
    Generate with:  python3 generate_narration.py

PER-CHECKPOINT  (generated live via Ollama qwen3:0.6b):
    hint, success, wrong_order, wrong_ids, returning — generated on demand.
    Prefetching runs in background while Misty is driving so the next
    message is usually ready by the time it's needed.
    Falls back to hardcoded strings if Ollama is unavailable or too slow.
"""

import json
import os
import random
import re
import threading
import time

try:
    import requests as _req
except ImportError:
    _req = None

# ── Config ────────────────────────────────────────────────────────────────────

CACHE_FILE   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "narration_cache.json")
OLLAMA_URL   = "http://localhost:11434/api/chat"
LIVE_MODEL   = "qwen3:0.6b"
LIVE_TIMEOUT = 6.0   # seconds to wait for Ollama before using fallback

_SYSTEM = (
    "You are Misty, a small friendly robot talking to a child aged 6 to 12 "
    "who is playing a navigation card game. "
    "Reply with ONE short sentence only — under 12 words. "
    "Simple words, warm and fun. No emojis, no lists, no markdown."
)

_LIVE_PROMPTS = {
    "hint": (
        "Round {phase} of {total}. Destination: {location}. Moves: {moves}. "
        "Give ONE short clue under 12 words."
    ),
    "success": (
        "Child solved round {phase} — heading to {location}. "
        "One excited sentence under 10 words."
    ),
    "wrong_order": (
        "Right cards, wrong order, round {phase} to {location}. "
        "One gentle nudge under 10 words."
    ),
    "wrong_ids": (
        "Wrong cards, round {phase} to {location}. "
        "One warm encourage under 10 words."
    ),
    "returning": (
        "Visited {location}, round {phase}, now heading back. "
        "One happy sentence under 8 words."
    ),
}

# ── Hardcoded fallbacks (used when Ollama is unavailable / too slow) ──────────

_HARDCODED = [
    {
        "hint":        "Alright, here we go! Place your cards to send me in the right direction!",
        "success":     "Woohoo, you got it! Off I go!",
        "wrong_order": "Right cards, wrong order — try swapping them around!",
        "wrong_ids":   "Oops, those are not quite right — let's try different cards!",
        "returning":   "That was fun! Heading back now!",
    },
    {
        "hint":        "Time for leg two! Watch out for the turns on this one!",
        "success":     "Yes! Nailed it! On my way to the supermarket!",
        "wrong_order": "So close! Right cards, just mix up the order a little!",
        "wrong_ids":   "Hmm, those cards will not get me there — try a different combo!",
        "returning":   "Got what I need! Heading back home!",
    },
    {
        "hint":        "Leg three — there is a left turn AND a right turn. You can do it!",
        "success":     "Amazing! That was tricky and you crushed it!",
        "wrong_order": "Right cards, wrong order! Think about which turn comes first!",
        "wrong_ids":   "Those are not the right cards for this path — try some different ones!",
        "returning":   "What an adventure! Zooming back now!",
    },
    {
        "hint":        "Leg four — heading to school! Watch for the double forward in the middle!",
        "success":     "Wooo, perfect! Off to school we go!",
        "wrong_order": "Almost! The cards are right but the order is jumbled — rearrange and try again!",
        "wrong_ids":   "Oops, wrong cards! Think about the path to school!",
        "returning":   "School visit done! Racing back home!",
    },
    {
        "hint":        "Last leg! Double forward then a right turn — you have got this!",
        "success":     "You did it! Final stretch, here I come!",
        "wrong_order": "So close to the finish! Right cards, wrong order — one more try!",
        "wrong_ids":   "Not quite right for the final leg — try some different cards!",
        "returning":   "We made it! Heading home one last time!",
    },
]

_INTRO_FALLBACK = {
    "welcome":     "Hello friends! Welcome to the Misty Maze!",
    "how_to_play": (
        "Card one means forward, card two means turn left, card three means turn right. "
        "Place your cards in order and press the button to send me!"
    ),
    "good_luck":   "Good luck — you have got this!",
}


# ── Pre-fetch cache ───────────────────────────────────────────────────────────

_cache: dict = {}          # (phase, key) -> str
_cache_lock  = threading.Lock()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sequence_to_moves(sequence: list) -> str:
    names = {1: "forward", 2: "left turn", 3: "right turn"}
    return ", ".join(names.get(c, f"card {c}") for c in sequence)


def _call_ollama(prompt: str, timeout: float) -> str | None:
    if _req is None:
        return None
    payload = {
        "model":   LIVE_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user",   "content": prompt},
        ],
        "stream": False,
        "think":  False,
        "options": {"temperature": 0.8, "num_predict": 80},
    }
    try:
        r = _req.post(OLLAMA_URL, json=payload, timeout=timeout)
        r.raise_for_status()
        text = r.json()["message"]["content"].strip()
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        return text or None
    except Exception as e:
        print(f"  [narrator] Ollama error: {e}")
        return None


def _fallback(key: str, phase: int, location: str) -> str:
    idx = phase - 1
    if 0 <= idx < len(_HARDCODED):
        return _HARDCODED[idx].get(key, "")
    return {
        "hint":        f"Place your cards to navigate me to the {location}!",
        "success":     f"Great job! Heading to the {location}!",
        "wrong_order": "Right cards, wrong order — try rearranging!",
        "wrong_ids":   "Those are not quite right — try different cards!",
        "returning":   f"Trip to the {location} done — heading back!",
    }[key]


def _fetch_and_store(phase: int, total: int, location: str, moves: str, key: str):
    prompt = _LIVE_PROMPTS[key].format(
        phase=phase, total=total, location=location, moves=moves
    )
    text = _call_ollama(prompt, timeout=LIVE_TIMEOUT)
    if text:
        with _cache_lock:
            _cache[(phase, key)] = text


# ── Public API ────────────────────────────────────────────────────────────────

def load_intro() -> dict:
    """Return {welcome, how_to_play, good_luck} strings from cache (or fallback)."""
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            msgs = data.get("intro", {}).get("messages", {})
            result = {}
            for key in ("welcome", "how_to_play", "good_luck"):
                val = msgs.get(key)
                if isinstance(val, list):
                    valid = [v for v in val if v]
                    result[key] = random.choice(valid) if valid else _INTRO_FALLBACK[key]
                elif isinstance(val, str) and val:
                    result[key] = val
                else:
                    result[key] = _INTRO_FALLBACK[key]
            print("  [OK] Loaded intro narration from cache.")
            return result
    except Exception as e:
        print(f"  [narrator] Cache load failed: {e} — using fallbacks.")
    print("  [narrator] No intro cache — using hardcoded fallbacks.")
    print("     Run 'python3 generate_narration.py' to generate intro narration.")
    return dict(_INTRO_FALLBACK)


def prefetch(phase: int, total: int, location: str, sequence: list):
    """Start background generation for all message types of an upcoming checkpoint.
    Call this while Misty is driving so messages are ready when needed.
    """
    moves = _sequence_to_moves(sequence)
    for key in _LIVE_PROMPTS:
        threading.Thread(
            target=_fetch_and_store,
            args=(phase, total, location, moves, key),
            daemon=True,
        ).start()


def live(phase: int, total: int, location: str, sequence: list, key: str) -> str:
    """Return a narration string for the given key.

    Checks prefetch cache first (waits up to 2s), then generates synchronously,
    then falls back to a hardcoded string.
    """
    # Wait briefly for a prefetched result
    deadline = time.time() + 2.0
    while time.time() < deadline:
        with _cache_lock:
            if (phase, key) in _cache:
                return _cache.pop((phase, key))
        time.sleep(0.1)

    # Generate synchronously with a short timeout
    moves  = _sequence_to_moves(sequence)
    prompt = _LIVE_PROMPTS[key].format(
        phase=phase, total=total, location=location, moves=moves
    )
    text = _call_ollama(prompt, timeout=3.0)
    return text or _fallback(key, phase, location)
