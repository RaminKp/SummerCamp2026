"""
narration.py
============

Runtime loader for cached robot narration.

Usage
-----
    from narration import Narration
    N = Narration("narration_cache.json")
    qt.say(N.pick("welcome", name="house"))

How it behaves
--------------
  * Loads narration_cache.json once at construction. If the file is missing or
    malformed, prints a warning and falls back to the hardcoded DEFAULTS so
    the game always runs (just without variety).
  * Each key may be EITHER a list of variations (the format the generator
    writes) OR a single string (legacy). Both are accepted - lists give random
    choice on every pick(), strings are used as-is.
  * pick() never raises. If a key is missing, or a placeholder value isn't
    supplied, it falls back through: cache -> hardcoded default -> generic
    line. The robot keeps talking even if the cache is half-broken.
"""
import json
import os
import random
from typing import Dict, List

from narration_prompts import DEFAULTS

_GENERIC_FALLBACK = "Let's keep building!"


class Narration:
    def __init__(self, path: str = "narration_cache.json",
                 verbose: bool = True):
        self.path = path
        self._cache: Dict[str, List[str]] = {}
        self._load(verbose)

    # ------------------------------------------------------------------
    #  Loading
    # ------------------------------------------------------------------
    def _load(self, verbose: bool) -> None:
        if not os.path.exists(self.path):
            if verbose:
                print(f"[Narration] No cache at '{self.path}'; using "
                      f"hardcoded defaults only. Run "
                      f"generate_narration_cache.py to create one.")
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception as e:
            if verbose:
                print(f"[Narration] Could not read '{self.path}': {e}; using "
                      f"hardcoded defaults.")
            return
        if not isinstance(raw, dict):
            if verbose:
                print(f"[Narration] '{self.path}' is not a JSON object; "
                      f"using hardcoded defaults.")
            return

        # Accept both list-of-variations (current format) and single-string
        # (legacy format). Skip anything else silently.
        for key, val in raw.items():
            if isinstance(val, list):
                vs = [str(v) for v in val
                      if isinstance(v, str) and v.strip()]
            elif isinstance(val, str) and val.strip():
                vs = [val]                                # backward-compat
            else:
                continue
            if vs:
                self._cache[key] = vs

        if verbose:
            total = sum(len(v) for v in self._cache.values())
            unknown = [k for k in self._cache if k not in DEFAULTS]
            print(f"[Narration] Loaded {total} variations across "
                  f"{len(self._cache)} keys from '{self.path}'.")
            if unknown:
                print(f"[Narration] Cache has extra keys not used by the "
                      f"game (harmless): {sorted(unknown)}")
            missing = [k for k in DEFAULTS if k not in self._cache]
            if missing:
                print(f"[Narration] Cache is missing {len(missing)} keys "
                      f"(will use defaults): {sorted(missing)}")

    # ------------------------------------------------------------------
    #  Lookup
    # ------------------------------------------------------------------
    def pick(self, key: str, **kwargs) -> str:
        """Return ONE variation for `key`, formatted with kwargs.

        Fallback chain: cache variation -> hardcoded default for the key ->
        generic line. Format errors (e.g. a missing placeholder value) drop
        through to the default and finally the generic line, never raising.
        """
        choices = self._cache.get(key)
        if choices:
            text = random.choice(choices)
        else:
            text = DEFAULTS.get(key, _GENERIC_FALLBACK)
        try:
            return text.format(**kwargs) if kwargs else text
        except (KeyError, IndexError, ValueError):
            # Cached variation referenced a placeholder we weren't given,
            # or the cache entry is malformed. Try the hardcoded default.
            default = DEFAULTS.get(key, _GENERIC_FALLBACK)
            try:
                return default.format(**kwargs) if kwargs else default
            except Exception:
                return _GENERIC_FALLBACK

    # ------------------------------------------------------------------
    #  Diagnostics
    # ------------------------------------------------------------------
    def stats(self) -> Dict[str, int]:
        """Return {key: variation_count}. Useful for sanity-checking on
        startup or in tests."""
        return {k: len(v) for k, v in self._cache.items()}
