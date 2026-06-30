"""
narrator.py -- Narration for game checkpoints.

Loads pre-generated narration from narration_cache.json (created by
generate_narration.py).  Each message key may contain a list of
variations -- one is chosen at random each game run.
Falls back to hardcoded defaults if the cache is missing or incomplete.
"""

import json
import os
import random

# ── Cache file path ──────────────────────────────────────────────────────────

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "narration_cache.json")


# ── Hardcoded fallback narration ─────────────────────────────────────────────
# Used when the cache doesn't exist or is missing entries.

HARDCODED_NARRATION = [
    # Phase 1 — destination (forward, forward)
    {
        "hint":        "Alright, here we go! Place two cards to send me straight ahead!",
        "success":     "Woohoo, you got it! Off I go, zooming forward!",
        "wrong_order": "Hmm, you have the right cards but they're a little mixed up. Try swapping them around!",
        "wrong_ids":   "Oops, those aren't quite the right cards. Let's pick different ones!",
        "returning":   "That was fun! Heading back home now!",
    },
    # Phase 2 — supermarket
    {
        "hint":        "Time for leg two! I need to get to the supermarket. Five cards this time — watch out for the left turns!",
        "success":     "Yes! Nailed it! I'm on my way to the supermarket!",
        "wrong_order": "So close! You picked the right cards, but the order is a little off. Give it another try!",
        "wrong_ids":   "Hmm, those cards won't get me to the supermarket. Try a different combination!",
        "returning":   "Got my groceries! Heading back home from the supermarket!",
    },
    # Phase 3 — destination (left then right)
    {
        "hint":        "Leg three! Five cards again — this time there's a left turn AND a right turn. You can do it!",
        "success":     "Amazing! That was a tricky one and you crushed it! Let's roll!",
        "wrong_order": "Right cards, wrong order! Think about which turn comes first and try again!",
        "wrong_ids":   "Those aren't the right cards for this path. Try picking some different ones!",
        "returning":   "What an adventure! Zooming back home now!",
    },
    # Phase 4 — school
    {
        "hint":        "Leg four — heading to school! Six cards this time. Watch for the double forward in the middle!",
        "success":     "Wooo, perfect! Off to school we go!",
        "wrong_order": "Almost! The cards are right but the sequence is jumbled. Rearrange and try again!",
        "wrong_ids":   "Oops, wrong cards! Think about the path to school and try different ones!",
        "returning":   "School visit done! Racing back home!",
    },
    # Phase 5 — destination (final leg)
    {
        "hint":        "Last leg! Six cards — double forward then a right turn. You've got this!",
        "success":     "You did it! Final stretch, here I come!",
        "wrong_order": "So close to the finish! Right cards, wrong order. One more try!",
        "wrong_ids":   "Not quite the right cards for the final leg. Pick some different ones!",
        "returning":   "We made it! Heading home one last time — what a journey!",
    },
]


# ── Public API ───────────────────────────────────────────────────────────────

def pre_generate(checkpoints: list, map_id: int = 1) -> list[dict]:
    """
    Return narration for every checkpoint.

    Priority:
      1. narration_cache.json  (AI-generated, pre-cached)
      2. HARDCODED_NARRATION   (static fallback)
      3. _default()            (generic fallback for extra phases)
    """
    total   = len(checkpoints)
    results = []

    # ── Try to load the cache ────────────────────────────────────────────
    cached_phases = _load_cache(map_id)

    if cached_phases:
        print(f"  [OK] Loaded AI narration from cache ({len(cached_phases)} phases).")
    else:
        print("  [INFO] No narration cache found -- using hardcoded fallbacks.")
        print(f"     Run 'python3 generate_narration.py' to generate AI narration.")

    # ── Build narration list ─────────────────────────────────────────────
    for i, cp in enumerate(checkpoints):
        location = getattr(cp, "location", "destination")
        msgs     = {}

        # Source 1: cache (values may be lists of variations or single strings)
        if cached_phases and i < len(cached_phases):
            cached_msgs = cached_phases[i].get("messages", {})
            for key in ("hint", "success", "wrong_order", "wrong_ids", "returning"):
                msgs[key] = _pick_random(cached_msgs.get(key))

        # Source 2: hardcoded fallback for any missing keys
        if i < len(HARDCODED_NARRATION):
            hardcoded = HARDCODED_NARRATION[i]
            for key in ("hint", "success", "wrong_order", "wrong_ids", "returning"):
                if not msgs.get(key):
                    msgs[key] = hardcoded[key]

        # Source 3: generic default for any still-missing keys
        for key in ("success", "wrong_order", "wrong_ids", "returning"):
            if not msgs.get(key):
                msgs[key] = _default(key, location)
        if not msgs.get("hint"):
            msgs["hint"] = cp.hint

        results.append(msgs)

    return results


# ── Private helpers ──────────────────────────────────────────────────────────

def _load_cache(map_id: int) -> list | None:
    """Load cached narration phases for a given map ID, or None."""
    if not os.path.exists(CACHE_FILE):
        return None
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        map_data = data.get(str(map_id))
        if map_data and "phases" in map_data:
            return map_data["phases"]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        print(f"  [WARN] Cache file corrupt or unreadable: {e}")
    return None


def _pick_random(value) -> str | None:
    """Pick a random variation from a cached value.

    Handles both formats:
      - list of strings  (new multi-variation format) -> random.choice
      - single string    (old format / backward compat) -> return as-is
      - None / empty     -> None (triggers fallback)
    """
    if isinstance(value, list):
        # Filter out None entries (failed generations)
        valid = [v for v in value if v]
        return random.choice(valid) if valid else None
    if isinstance(value, str) and value:
        return value
    return None


def _default(key: str, location: str) -> str:
    return {
        "success":     f"Great job! Now heading to the {location}!",
        "wrong_order": "Right cards, wrong order -- give it another go!",
        "wrong_ids":   "Those aren't quite the right cards. Try again!",
        "returning":   f"Trip to the {location} complete -- heading home!",
    }[key]
