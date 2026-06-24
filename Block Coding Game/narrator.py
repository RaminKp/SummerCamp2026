"""
narrator.py — Ollama-powered natural language for game checkpoints.
Call pre_generate() once at startup; all messages are ready before the game begins.
"""

import requests

OLLAMA_URL   = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "qwen2.5:1.5b"

SYSTEM_PROMPT = (
    "You are Misty, a small friendly robot talking to a child playing a navigation game. "
    "You speak in short, warm, enthusiastic sentences — 1 to 2 sentences maximum. "
    "You are speaking out loud so keep it simple and fun."
)


def _ask(prompt: str) -> str:
    try:
        r = requests.post(OLLAMA_URL, json={
            "model":   OLLAMA_MODEL,
            "messages": [
                {"role": "system",  "content": SYSTEM_PROMPT},
                {"role": "user",    "content": prompt},
            ],
            "stream": False,
        }, timeout=30)
        r.raise_for_status()
        return r.json()["message"]["content"].strip()
    except Exception as e:
        return None   # caller falls back to static hint


def _generate_for(phase: int, total: int, location: str) -> dict:
    loc = location.lower()
    return {
        "hint": _ask(
            f"It's leg {phase} of {total}. Tell the child you need their help navigating to the {loc}. "
            f"Mention they need to arrange cards in the right order."
        ),
        "success": _ask(
            f"The child got the card sequence right! You're now heading to the {loc}. "
            f"Say something excited and encouraging."
        ),
        "wrong_order": _ask(
            f"The child placed the right cards but in the wrong order to get to the {loc}. "
            f"Gently tell them to rearrange and try again."
        ),
        "wrong_ids": _ask(
            f"The child used the wrong cards entirely for navigating to the {loc}. "
            f"Encourage them to try different cards."
        ),
        "returning": _ask(
            f"You successfully visited the {loc} and now you're heading back home. "
            f"Say something brief and happy about the trip."
        ),
    }


def _ollama_reachable() -> bool:
    """Return True if the Ollama server responds."""
    try:
        r = requests.get(OLLAMA_URL.replace("/api/chat", "/api/tags"), timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def pre_generate(checkpoints: list) -> list[dict]:
    """
    Generate narration for every checkpoint before the game starts.
    Returns a list of dicts indexed the same as checkpoints.
    Falls back to static messages if Ollama is unavailable.
    """
    total   = len(checkpoints)
    results = []

    # ── Connectivity check ────────────────────────────────────────────────────
    if not _ollama_reachable():
        print()
        print("  ⚠  WARNING: Ollama is not running (localhost:11434 unreachable).")
        print("  ⚠  Narration will use static fallback lines for all phases.")
        print("  ⚠  To enable AI narration: run  ollama serve  in another terminal.")
        print()
        # Build results immediately from static fallbacks
        for i, cp in enumerate(checkpoints, 1):
            location = getattr(cp, "location", "destination")
            results.append({
                "hint":        cp.hint,
                "success":     _default("success",     location),
                "wrong_order": _default("wrong_order", location),
                "wrong_ids":   _default("wrong_ids",   location),
                "returning":   _default("returning",   location),
            })
        return results

    print(f"  ✓  Ollama reachable — generating narration with {OLLAMA_MODEL}...")
    for i, cp in enumerate(checkpoints, 1):
        location = getattr(cp, "location", "destination")
        print(f"  Generating narration for leg {i} ({location})...", end=" ", flush=True)
        msgs = _generate_for(i, total, location)

        # Fall back to static lines for any individual message that failed
        if not msgs["hint"]:
            msgs["hint"] = cp.hint
        for key in ("success", "wrong_order", "wrong_ids", "returning"):
            if not msgs[key]:
                msgs[key] = _default(key, location)

        print("done")
        results.append(msgs)

    return results


def _default(key: str, location: str) -> str:
    return {
        "success":     f"Great job! Now heading to the {location}!",
        "wrong_order": "Right cards, wrong order — give it another go!",
        "wrong_ids":   "Those aren't quite the right cards. Try again!",
        "returning":   f"Trip to the {location} complete — heading home!",
    }[key]
