#!/usr/bin/env python3
"""
generate_narration_cache.py
===========================

Offline generator for narration_cache.json.

Run this ONCE (or whenever you change game dialogue / want fresh wording) on a
machine that has Ollama installed and the chosen model pulled. The game itself
never calls Ollama at runtime - it just loads the JSON and picks a random
variation per key, so child-facing latency stays at zero.

Quick start
-----------
    # First time - pull the model, then generate 10 variations per key
    ollama pull gemma3:4b
    python3 generate_narration_cache.py

    # Faster cache for testing
    python3 generate_narration_cache.py --variations 3

    # Throw away the cache and regenerate everything
    python3 generate_narration_cache.py --force

    # Refresh only a few keys (comma-separated, no spaces)
    python3 generate_narration_cache.py --force --keys welcome,goodbye,nudge

    # Try a different local model
    python3 generate_narration_cache.py --model llama3.2:3b

Behaviour
---------
  * Endpoint: http://localhost:11434/api/chat, non-streaming, temperature 0.8,
    num_predict 80.
  * Retries 500s with exponential backoff (5s, 10s, 20s) because Ollama needs
    a moment to load the model on the first call.
  * Strips <think>...</think> reasoning blocks from any model that emits them.
  * Rejects variations that drop required placeholders (e.g. {name}) or
    duplicate something already in the list, and re-asks the model.
  * Writes the cache incrementally after each key, so a crash mid-run keeps
    the work already done.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

from narration_prompts import (
    DEFAULTS, PLACEHOLDERS, SYSTEM_PROMPT, build_user_prompt,
)

OLLAMA_URL    = "http://localhost:11434/api/chat"
RETRY_DELAYS  = (5, 10, 20)                            # seconds, exponential
THINK_RE      = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
PREAMBLE_RE   = re.compile(
    r"^(here'?s?\b[^:]*:|your line:|your version:|new version:|rephrased:|"
    r"variation\s*\d*\s*:?)\s*",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------
#  Output cleanup
# --------------------------------------------------------------------------
def _clean(text: str) -> str:
    """Strip <think> reasoning, surrounding quotes, common preambles."""
    text = THINK_RE.sub("", text or "").strip()
    # Some models wrap the answer in quotes despite instructions.
    for q in ('"""', "'''", '"', "'", "`"):
        if text.startswith(q) and text.endswith(q) and len(text) > 2 * len(q):
            text = text[len(q):-len(q)].strip()
    text = PREAMBLE_RE.sub("", text).strip()
    # Collapse internal newlines - the line is meant to be spoken in one go.
    text = re.sub(r"\s*\n+\s*", " ", text).strip()
    return text


def _placeholders_ok(key: str, text: str) -> bool:
    """Every required placeholder for this key must survive verbatim."""
    return all(ph in text for ph in PLACEHOLDERS.get(key, []))


# --------------------------------------------------------------------------
#  Ollama HTTP call with retry/backoff
# --------------------------------------------------------------------------
def _call_ollama(model: str, system: str, user: str,
                 timeout_s: float = 90.0) -> str:
    """POST one chat completion to local Ollama and return the assistant text.

    Retries HTTP 500 and connection errors with exponential backoff because
    Ollama returns 500 while it's still warming the model on the first call.
    """
    payload = json.dumps({
        "model":   model,
        "stream":  False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "options": {
            "temperature": 0.8,
            "num_predict": 80,
        },
    }).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL, data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )

    delays = [0, *RETRY_DELAYS]                       # 0 = first try, no wait
    last_err = None
    for attempt, delay in enumerate(delays):
        if delay:
            print(f"        retrying in {delay}s ...")
            time.sleep(delay)
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data.get("message", {}).get("content", "") or ""
        except urllib.error.HTTPError as e:
            last_err = e
            # Only retry transient 500s; surface 4xx (bad model name etc).
            if e.code != 500 or attempt == len(delays) - 1:
                raise
            print(f"        HTTP {e.code} (model still loading?)")
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = e
            if attempt == len(delays) - 1:
                raise
            print(f"        connection error: {e}")
    raise last_err                                    # pragma: no cover


# --------------------------------------------------------------------------
#  Per-key generation
# --------------------------------------------------------------------------
def generate_for_key(model: str, key: str, n_variations: int,
                     max_attempts_per_var: int = 4) -> list:
    """Generate up to n_variations distinct child-friendly variations for one
    key. Always returns at least one entry (falls back to the hardcoded
    default if the model fails completely)."""
    variations: list = []
    seen: set = set()
    print(f"  [{key}] generating up to {n_variations} variations ...")
    for i in range(n_variations):
        for attempt in range(max_attempts_per_var):
            prompt = build_user_prompt(key, n_so_far=len(variations))
            try:
                raw = _call_ollama(model, SYSTEM_PROMPT, prompt)
            except Exception as e:
                print(f"      attempt {attempt + 1}: error {e}")
                continue
            cleaned = _clean(raw)
            if not cleaned:
                print(f"      attempt {attempt + 1}: empty response")
                continue
            if not _placeholders_ok(key, cleaned):
                missing = [p for p in PLACEHOLDERS.get(key, [])
                           if p not in cleaned]
                print(f"      attempt {attempt + 1}: dropped placeholder(s) "
                      f"{missing}; got {cleaned!r}")
                continue
            # case- and trailing-punctuation-insensitive duplicate check
            norm = re.sub(r"[\s.!?,]+$", "", cleaned.lower())
            if norm in seen:
                print(f"      attempt {attempt + 1}: duplicate of an existing "
                      f"variation; retrying")
                continue
            seen.add(norm)
            variations.append(cleaned)
            print(f"      [{len(variations)}/{n_variations}] {cleaned}")
            break
        else:
            print(f"      gave up on variation {i + 1} after "
                  f"{max_attempts_per_var} attempts")

    if not variations:
        print(f"  [{key}] WARNING: 0 usable variations; using hardcoded "
              f"default so the cache still has at least one entry.")
        variations = [DEFAULTS[key]]
    return variations


# --------------------------------------------------------------------------
#  Main
# --------------------------------------------------------------------------
def main() -> int:
    p = argparse.ArgumentParser(
        description="Generate narration_cache.json for Tangram Quest.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--model", default="gemma3:4b",
                   help="Ollama model tag (default: gemma3:4b).")
    p.add_argument("--variations", type=int, default=10,
                   help="How many variations per key (default: 10).")
    p.add_argument("--force", action="store_true",
                   help="Regenerate even keys that already have enough "
                        "variations in the existing cache file.")
    p.add_argument("--keys", default=None,
                   help="Comma-separated subset of keys to regenerate "
                        "(default: all keys).")
    p.add_argument("--output", default="narration_cache.json",
                   help="Output JSON path (default: narration_cache.json).")
    args = p.parse_args()

    if args.variations < 1:
        p.error("--variations must be >= 1")

    requested = (set(s.strip() for s in args.keys.split(",") if s.strip())
                 if args.keys else set(DEFAULTS))
    unknown = requested - set(DEFAULTS)
    if unknown:
        p.error(f"Unknown keys: {sorted(unknown)}. "
                f"Valid keys: {sorted(DEFAULTS)}")

    # Load existing cache so partial runs are incremental.
    cache: dict = {}
    if os.path.exists(args.output):
        try:
            with open(args.output, "r", encoding="utf-8") as f:
                cache = json.load(f)
            # Normalise legacy single-string entries to list form.
            for k, v in list(cache.items()):
                if isinstance(v, str):
                    cache[k] = [v]
            total = sum(len(v) for v in cache.values()
                        if isinstance(v, list))
            print(f"[Cache] Loaded existing '{args.output}' "
                  f"({total} variations across {len(cache)} keys).")
        except Exception as e:
            print(f"[Cache] Could not read '{args.output}': {e} "
                  f"(starting fresh).")
            cache = {}

    to_run = sorted(requested)
    print(f"[Cache] Model={args.model}, variations/key={args.variations}, "
          f"keys={len(to_run)}, force={args.force}")
    t0 = time.time()

    for key in to_run:
        existing = cache.get(key) or []
        if (not args.force) and len(existing) >= args.variations:
            print(f"  [{key}] already has {len(existing)} variations; "
                  f"skipping (use --force to regenerate).")
            continue
        cache[key] = generate_for_key(args.model, key, args.variations)
        # Save incrementally so a crash doesn't lose progress.
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
        print(f"  [{key}] saved.")

    dt = time.time() - t0
    total = sum(len(v) for v in cache.values() if isinstance(v, list))
    print(f"\n[Cache] Done in {dt:.1f}s. Wrote '{args.output}' "
          f"({total} variations across {len(cache)} keys).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
