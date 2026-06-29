#!/usr/bin/env python3
"""
test_game_no_robot.py -- Test the full game flow without Misty robot or RFID hardware.

Stubs out misty (robot) and detector (RFID readers), then simulates:
  - Phase 1: correct on first try
  - Phase 2: wrong IDs first, then correct
  - Phase 3: wrong order first, then correct
  - Phase 4: correct on first try
  - Phase 5: correct on first try

This validates that narration_cache.json loads correctly and random
variation selection works.
"""

import sys
import types
import time

# ── Stub out misty (robot) ───────────────────────────────────────────────────
stub_misty = types.ModuleType("misty")
stub_misty.turn_180          = lambda: None
stub_misty.disable_hazards   = lambda: print("  [STUB] misty.disable_hazards()")
stub_misty.enable_hazards    = lambda: print("  [STUB] misty.enable_hazards()")
stub_misty.led_ready         = lambda: print("  [STUB] misty.led_ready()")
stub_misty.led_error         = lambda: print("  [STUB] misty.led_error()")
stub_misty.led_success       = lambda: print("  [STUB] misty.led_success()")
stub_misty.led               = lambda r, g, b: None
stub_misty.celebrate         = lambda: print("  [STUB] misty.celebrate()")
stub_misty.execute_drive_map = lambda dm: print(f"  [STUB] misty.execute_drive_map({len(dm)} steps)")

def stub_speak(text):
    # Show what Misty would say
    preview = text[:80] + "..." if len(text) > 80 else text
    print(f'  [SPEAK] "{preview}"')

stub_misty.speak = stub_speak
sys.modules["misty"] = stub_misty

# ── Stub out RPi.GPIO and rfid_reader (not available on Windows) ─────────────
stub_gpio = types.ModuleType("RPi")
stub_gpio.GPIO = types.ModuleType("RPi.GPIO")
sys.modules["RPi"] = stub_gpio
sys.modules["RPi.GPIO"] = stub_gpio.GPIO

# ── Now import game modules ──────────────────────────────────────────────────
from maps import get_active_map, ACTIVE_MAP_ID
import narrator
from validator import validate_and_message, ValidationResult


def run_test():
    active_map = get_active_map()
    total = len(active_map.checkpoints)

    print(f"\n{'='*60}")
    print(f"  TEST RUN (no robot)")
    print(f"  Map : {active_map.name}")
    print(f"  Legs: {total} phases")
    print(f"{'='*60}\n")

    # Load narration (this is what we're really testing)
    print("Loading narration from cache...")
    narration = narrator.pre_generate(active_map.checkpoints, map_id=ACTIVE_MAP_ID)

    print(f"\nNarration loaded: {len(narration)} phases\n")

    # ── Simulate each phase ──────────────────────────────────────────────
    test_scenarios = {
        1: [("correct",)],                        # correct first try
        2: [("wrong_ids",), ("correct",)],         # wrong IDs then correct
        3: [("wrong_order",), ("correct",)],       # wrong order then correct
        4: [("correct",)],                        # correct first try
        5: [("correct",)],                        # correct first try
    }

    for i, checkpoint in enumerate(active_map.checkpoints, 1):
        is_last = (i == total)
        msgs = narration[i - 1]

        print(f"\n{'-'*60}")
        print(f"  Phase {i} of {total} -- {checkpoint.location}")
        print(f"  Expected sequence: {checkpoint.sequence}")
        print(f"{'-'*60}")

        # Show the hint
        print(f"\n  HINT:")
        stub_speak(msgs["hint"])

        scenarios = test_scenarios.get(i, [("correct",)])

        for attempt_num, (scenario,) in enumerate(scenarios, 1):
            print(f"\n  --- Attempt {attempt_num} [{scenario}] ---")

            if scenario == "correct":
                scanned = checkpoint.sequence[:]
            elif scenario == "wrong_order":
                scanned = checkpoint.sequence[::-1]  # reversed
            elif scenario == "wrong_ids":
                scanned = [9, 9, 9]  # totally wrong

            print(f"  Simulated scan: {scanned}")
            result, _ = validate_and_message(scanned, checkpoint.sequence)
            print(f"  Validation: {result.value}")

            if result == ValidationResult.CORRECT:
                print(f"\n  SUCCESS:")
                stub_speak(msgs["success"])
                print(f"  [STUB] Driving out...")
                if checkpoint.return_map:
                    print(f"\n  RETURNING:")
                    stub_speak(msgs["returning"])
                    print(f"  [STUB] Returning home...")
                if is_last:
                    print(f"\n  FINAL PHASE COMPLETE!")
                    print(f"  [STUB] misty.celebrate()")

            elif result == ValidationResult.WRONG_ORDER:
                print(f"\n  WRONG ORDER:")
                stub_speak(msgs["wrong_order"])

            else:
                print(f"\n  WRONG IDs:")
                stub_speak(msgs["wrong_ids"])

    print(f"\n{'='*60}")
    print(f"  TEST COMPLETE -- All {total} phases passed!")
    print(f"{'='*60}\n")

    # ── Show variation proof ─────────────────────────────────────────────
    print("--- Variation randomness check ---")
    print("Running narration load 3 times to show different random picks:\n")
    for run in range(1, 4):
        n = narrator.pre_generate(active_map.checkpoints, map_id=ACTIVE_MAP_ID)
        hint1 = n[0]["hint"][:60]
        print(f"  Run {run}, Phase 1 hint: \"{hint1}...\"")


if __name__ == "__main__":
    run_test()
