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

def _scan_loop(slots: list, done_event: threading.Event,
               first_tag_event: threading.Event | None = None):
    """Background thread: continuously poll readers.

    Slots are always live — placing a new card on a reader replaces whatever
    was there before, and removing a card clears the slot.
    Sets first_tag_event the moment any card is first detected.
    """
    first_seen = False
    while not done_event.is_set():
        for idx in range(N_READERS):
            name, reader = _readers[idx]
            uid = rfid_reader.scan_once(name, reader)
            prev = slots[idx]

            if uid and uid != prev:
                slots[idx] = uid
                game_id = _card_map.get(uid)
                label = f"Game ID {game_id}" if game_id else f"UNKNOWN UID ({uid})"
                filled = sum(1 for s in slots if s is not None)
                action = "replaced" if prev else "placed"
                print(f"  [Reader {idx+1}] {label} ({action})  ({filled}/{N_READERS} slots filled)")
                if not first_seen and first_tag_event is not None:
                    first_seen = True
                    first_tag_event.set()
            elif not uid and prev:
                slots[idx] = None
                filled = sum(1 for s in slots if s is not None)
                print(f"  [Reader {idx+1}] cleared  ({filled}/{N_READERS} slots filled)")

        time.sleep(POLL_INTERVAL)


# ── Tag-removal gate ──────────────────────────────────────────────────────────

def wait_for_tags_removed(timeout: float = 60.0, clear_seconds: float = 1.5):
    """Block until all readers report empty for `clear_seconds` in a row.

    Gives players time to physically remove all RFID cards before the next
    round starts. Times out after `timeout` seconds regardless.
    """
    _ensure_init()
    print("\n  [RFID] Waiting for all tags to be removed...")
    deadline    = time.time() + timeout
    clear_since = None

    while time.time() < deadline:
        all_empty = all(
            rfid_reader.scan_once(name, reader) is None
            for name, reader in _readers
        )
        if all_empty:
            if clear_since is None:
                clear_since = time.time()
            elif time.time() - clear_since >= clear_seconds:
                print("  [RFID] All tags removed — continuing.")
                return
        else:
            clear_since = None
        time.sleep(POLL_INTERVAL)

    print("  [RFID] Timeout waiting for tag removal — continuing anyway.")


# ── Public API ────────────────────────────────────────────────────────────────

def run_detector(n_slots: int = N_READERS,
                 first_tag_event: threading.Event | None = None,
                 game_over_event: threading.Event | None = None) -> list[int] | None:
    """
    Wait for the player to tap RFID cards onto the readers, then submit with
    the physical button.

    Args:
        n_slots:          how many reader slots to monitor (default: all 6).
        first_tag_event:  set the moment the first card is detected (starts timer).
        game_over_event:  when set externally (timer expired), returns None immediately.

    Returns:
        Ordered list of game-integer IDs, or None if aborted / game over.
        Check game_over_event.is_set() after None to distinguish the two cases.
    """
    _ensure_init()

    slots: list[str | None] = [None] * n_slots
    done_event      = threading.Event()
    submitted_event = threading.Event()

    # Start background scanning thread
    scan_thread = threading.Thread(target=_scan_loop,
                                   args=(slots, done_event, first_tag_event),
                                   daemon=True)
    scan_thread.start()

    # Unblock submitted_event when Enter is pressed
    def _wait_for_enter():
        input()
        submitted_event.set()

    key_thread = threading.Thread(target=_wait_for_enter, daemon=True)
    key_thread.start()

    # Also unblock if the game-over timer fires
    def _watch_game_over():
        if game_over_event is not None:
            game_over_event.wait()
            submitted_event.set()

    threading.Thread(target=_watch_game_over, daemon=True).start()

    print()
    print("  Tap your RFID cards onto the readers (Reader 1 = step 1, etc.).")
    print("  Press ENTER to submit.")
    print()

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