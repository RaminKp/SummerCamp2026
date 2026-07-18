"""
narrator.py -- Narration for the Misty Maze game.

INTRO  (from narration_cache.json or hardcoded fallback):
    welcome, how_to_play, good_luck — spoken once at game start.

PER-CHECKPOINT (Ollama qwen3:0.6b, pre-generated at game start):
    hint, success, wrong_order, wrong_ids, returning — all pre-generated
    during intro speech via prefetch_all(), so narration is ready with no
    delay during gameplay. Falls back to location-aware strings if Ollama
    is unavailable or a message was already consumed.
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

CACHE_FILE       = os.path.join(os.path.dirname(os.path.abspath(__file__)), "narration_cache.json")
OLLAMA_URL       = "http://localhost:11434/api/chat"
LIVE_MODEL       = "qwen3:0.6b"
LIVE_TIMEOUT     = 6.0    # seconds for sync fallback generation
PREFETCH_TIMEOUT = 12.0   # generous timeout for game-start pre-generation

_SYSTEM = (
    "You are Misty, a small friendly robot talking to children aged 6 to 12 "
    "who are playing a navigation card game called Mission Maze. "
    "Reply with ONE short sentence only — under 12 words. "
    "Simple words, warm and fun. No emojis, no lists, no markdown. "
    "IMPORTANT: Always use the exact destination name given to you — never invent "
    "synonyms or alternative names for it (e.g. never say 'kitchen' instead of 'Restaurant')."
)

_LIVE_PROMPTS = {
    "hint": (
        "Mission {phase} of {total}. Destination is the {location}. Moves needed: {moves}. "
        "Give ONE excited clue that mentions '{location}' by name — under 12 words. "
        "Be energetic and fun for kids."
    ),
    "success": (
        "Children solved mission {phase} — Misty is heading to the {location} now. "
        "React with HIGH excitement. Say '{location}' in your thrilled sentence — under 10 words. "
        "Use words like YESSS, WOOHOO, AMAZING."
    ),
    "wrong_order": (
        "Right cards but wrong order, mission {phase} going to {location}. Moves are: {moves}. "
        "Encourage kids warmly, mention '{location}', hint which move comes first — under 12 words."
    ),
    "wrong_ids": (
        "Wrong cards chosen, mission {phase} going to {location}. Correct moves are: {moves}. "
        "Encourage kids warmly, mention '{location}', hint card types needed — under 12 words."
    ),
    "returning": (
        "Misty just arrived at {location} on mission {phase}! React with MAXIMUM excitement. "
        "Say '{location}' — one thrilled sentence under 10 words, "
        "like 'YESSSSS! I am at the {location}! WE DID IT!'"
    ),
}

# ── Fallbacks (location-aware, used when Ollama result unavailable) ───────────

def _fallback(key: str, phase: int, location: str, total: int = 3,
              sequence: list | None = None) -> str:
    is_last = (phase == total)
    _move_names = {1: "Straight", 2: "Turn Left", 3: "Turn Right"}
    first_move = _move_names.get((sequence or [0])[0], "Straight") if sequence else "Straight"
    return {
        "hint": (
            f"Ooooh, Mission {phase}! We need to reach the {location} — "
            f"think carefully and choose the best cards!"
        ),
        "success": (
            f"YESSS! I am zooming to the {location} right now — AMAZING teamwork!"
        ),
        "wrong_order": (
            f"Ooooh, so close! You have the right cards! "
            f"Try starting with {first_move} in slot one!"
        ),
        "wrong_ids": (
            f"Hmm, those cards won't get me to the {location}! "
            f"Think about how many Straights and turns you need!"
        ),
        "returning": (
            "YESSSSS! I AM BACK HOME! WE DID IT, MISSION TEAM — INCREDIBLE!"
            if is_last
            else f"YESSSSS! I am at the {location}! We completed the mission — WOOHOO!"
        ),
    }[key]


_INTRO_FALLBACK = {
    "welcome": "Hello friends! Welcome to Mission Maze!",
    "how_to_play": (
        "You have six card slots in front of you. "
        "The Straight card moves me ahead one step. "
        "The Left card turns me to my left. "
        "The Right card turns me to my right. "
        "Place your cards in order from slot one to six to build a path, "
        "then press the green button to send me on my way!"
    ),
    "good_luck": "I am so excited — let's go and explore together!",
}


# ── Pre-fetch cache ───────────────────────────────────────────────────────────

_cache: dict = {}
_cache_lock  = threading.Lock()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sequence_to_moves(sequence: list) -> str:
    names = {1: "Straight", 2: "Turn Left", 3: "Turn Right"}
    return ", ".join(names.get(c, f"move {c}") for c in sequence)


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


def _fetch_and_store(phase: int, total: int, location: str, moves: str,
                     key: str, timeout: float = LIVE_TIMEOUT):
    prompt = _LIVE_PROMPTS[key].format(
        phase=phase, total=total, location=location, moves=moves
    )
    text = _call_ollama(prompt, timeout=timeout)
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
    return dict(_INTRO_FALLBACK)


def prefetch_all(checkpoints: list) -> None:
    """Pre-generate narration for ALL checkpoints at game start.

    Runs a single background thread that generates messages one at a time so
    Ollama is never flooded with concurrent requests. Priority order: hint
    first for each round (needed before the player submits), then the rest.
    Clears any stale cache from a previous game first.
    """
    with _cache_lock:
        _cache.clear()
    total = len(checkpoints)
    print(f"  [narrator] Pre-generating narration for {total} checkpoints…")

    # hint first for all rounds, then the rest — so Round 1 hint is ready soonest
    priority_order = ["hint", "success", "wrong_order", "wrong_ids", "returning"]
    work = [
        (i, cp, key)
        for key in priority_order
        for i, cp in enumerate(checkpoints, 1)
    ]

    def _run_all():
        for phase, cp, key in work:
            moves = _sequence_to_moves(cp.sequence)
            _fetch_and_store(phase, total, cp.location, moves, key, PREFETCH_TIMEOUT)

    threading.Thread(target=_run_all, daemon=True).start()


def prefetch(phase: int, total: int, location: str, sequence: list):
    """Start background generation for one checkpoint (legacy single-round call).
    Still useful as a top-up if a cached message was already consumed.
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

    Checks prefetch cache first (waits up to 4s), then generates synchronously,
    then falls back to a location-aware hardcoded string.
    """
    deadline = time.time() + 4.0
    while time.time() < deadline:
        with _cache_lock:
            if (phase, key) in _cache:
                return _cache.pop((phase, key))
        time.sleep(0.1)

    # Cache miss — generate synchronously
    moves  = _sequence_to_moves(sequence)
    prompt = _LIVE_PROMPTS[key].format(
        phase=phase, total=total, location=location, moves=moves
    )
    text = _call_ollama(prompt, timeout=LIVE_TIMEOUT)
    return text or _fallback(key, phase, location, total, sequence)
