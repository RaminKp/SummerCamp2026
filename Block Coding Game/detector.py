"""
detector.py  (RFID edition)
---------------------------
Replaces the ArUco/webcam detector with six MFRC522 RFID readers.

Interface is identical to the original:
    run_detector() -> list[int] | None

        Returns an ordered list of game-integer IDs (one per reader slot)
        when the player presses ENTER/SPACE to submit,
        or None if the player submits with no cards placed (abort).

Physical interaction
--------------------
  • Reader 1 = slot 1 (first step), … Reader 6 = slot 6 (sixth step).
  • The player taps cards onto whichever readers correspond to their intended
    sequence; each slot "locks in" on first tap and is shown in the terminal.
  • When ready, the player presses ENTER (or SPACE then ENTER) in the terminal
    to submit whatever is currently locked in.
  • Submitting with ZERO slots filled quits the game (like pressing Q
    with ArUco).

Configuration
-------------
  CARD_MAP_PATH  – JSON file produced by enrol_cards.py
  N_READERS      – how many readers to poll (set to sequence length or 6)

Run standalone to test outside the game:
    python detector.py
"""

import sys
import json
import time
import threading
from pathlib import Path

import RPi.GPIO as GPIO

# ── Allow importing rfid_reader from the RFID sensor folder ───────────────────
sys.path.insert(0, "/home/unbcroboticslab/Desktop/Sensors/RFID")
import rfid_reader

# ── Config ────────────────────────────────────────────────────────────────────

CARD_MAP_PATH = Path(__file__).parent / "card_map.json"
N_READERS     = 6          # poll all six readers every round
POLL_INTERVAL = 0.05       # seconds between full scan cycles


# ── Module-level state (initialised lazily on first call) ─────────────────────
_readers: list | None = None   # list of (name, SoftCSReader)
_card_map: dict[str, int] = {}


def _load_card_map() -> dict[str, int]:
    """Load the UID→game-ID mapping produced by enrol_cards.py."""
    if not CARD_MAP_PATH.exists():
        raise FileNotFoundError(
            f"Card map not found at {CARD_MAP_PATH}.\n"
            "Run  python enrol_cards.py  first to enrol your RFID cards."
        )
    return json.loads(CARD_MAP_PATH.read_text())


def _ensure_init():
    """Lazy initialisation — called once on the first run_detector() call."""
    global _readers, _card_map
    if _readers is None:
        print("[RFID] Initialising six readers...")
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        _readers = rfid_reader.build_readers()
        print("[RFID] Readers ready.")
    _card_map = _load_card_map()


# ── Core scanning loop ────────────────────────────────────────────────────────

def _scan_loop(slots: list, done_event: threading.Event):
    """Background thread: poll all readers and lock in UIDs as cards are tapped."""
    while not done_event.is_set():
        for idx in range(N_READERS):
            if slots[idx] is not None:
                continue   # already locked
            name, reader = _readers[idx]
            uid = rfid_reader.scan_once(name, reader)
            if uid:
                slots[idx] = uid
                game_id = _card_map.get(uid)
                label = f"Game ID {game_id}" if game_id else f"UNKNOWN UID ({uid})"
                filled = sum(1 for s in slots if s is not None)
                print(f"  [Reader {idx+1}] {label}  ({filled}/{N_READERS} slots filled)")
        time.sleep(POLL_INTERVAL)


# ── Public API ────────────────────────────────────────────────────────────────

def run_detector(n_slots: int = N_READERS) -> list[int] | None:
    """
    Wait for the player to tap RFID cards onto the readers, then submit with
    the physical button.

    Args:
        n_slots: how many reader slots to monitor (default: all 6).
                 Pass checkpoint.sequence length for tighter validation.

    Returns:
        Ordered list of game-integer IDs (one per slot, 0 if a slot was left
        empty), or None if the button was pressed with zero cards placed
        (player aborts the game).
    """
    _ensure_init()

    slots: list[str | None] = [None] * n_slots
    done_event = threading.Event()
    submitted_event = threading.Event()

    # Start background scanning thread
    scan_thread = threading.Thread(target=_scan_loop,
                                   args=(slots, done_event),
                                   daemon=True)
    scan_thread.start()

    # Start a thread that waits for the user to press Enter
    def _wait_for_enter():
        input()   # blocks until Enter is pressed
        submitted_event.set()

    key_thread = threading.Thread(target=_wait_for_enter, daemon=True)
    key_thread.start()

    print()
    print("  Tap your RFID cards onto the readers (Reader 1 = step 1, etc.).")
    print("  Press ENTER to submit.")
    print()

    # Block until Enter pressed
    submitted_event.wait()

    # Stop scan thread
    done_event.set()
    scan_thread.join(timeout=1.0)

    # If zero cards placed → abort (equivalent to pressing Q in ArUco version)
    if all(s is None for s in slots):
        print("[RFID] No cards detected — aborting game.")
        return None

    # Translate UIDs → game integers (0 for empty / unknown slots)
    result: list[int] = []
    for idx, uid in enumerate(slots):
        if uid is None:
            game_id = 0
        else:
            game_id = _card_map.get(uid, 0)
            if game_id == 0:
                print(f"  ⚠  Reader {idx+1}: UID {uid} not in card map — treating as 0.")
        result.append(game_id)

    # Trim trailing zeros (empty trailing slots don't count as part of the sequence)
    while result and result[-1] == 0:
        result.pop()

    print(f"[RFID] Submitted sequence: {result}")
    return result


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("  detector.py — standalone RFID test")
    print("  Tap cards, then press the submit button.")
    print("=" * 50)

    result = run_detector()
    if result is not None:
        print(f"\nFinal sequence: {result}")
    else:
        print("\nAborted (no cards placed).")

    GPIO.cleanup()