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
BUZZER_PIN    = 18         # BCM GPIO for piezo buzzer (active HIGH)


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
        _readers = rfid_reader.build_readers()
        print("[RFID] Readers ready.")
    _card_map = _load_card_map()


def _buzz(duration: float = 0.1):
    """Beep the physical buzzer for `duration` seconds."""
    try:
        GPIO.output(BUZZER_PIN, GPIO.HIGH)
        time.sleep(duration)
        GPIO.output(BUZZER_PIN, GPIO.LOW)
    except Exception:
        pass


# ── Background first-tag watcher ──────────────────────────────────────────────

def _first_tag_watcher(done_event: threading.Event,
                       first_tag_event: threading.Event):
    """Lightweight background thread — only watches for the very first card tap
    so the game timer can start. Stops as soon as first_tag_event is set."""
    while not done_event.is_set() and not first_tag_event.is_set():
        for name, reader in _readers:
            if rfid_reader.scan_once(name, reader):
                first_tag_event.set()
                return
        time.sleep(POLL_INTERVAL)


# ── Snapshot read ─────────────────────────────────────────────────────────────

def _read_snapshot() -> list[str | None]:
    """Read all readers once and return their current UIDs (or None)."""
    result = []
    for name, reader in _readers:
        uid = rfid_reader.scan_once(name, reader)
        result.append(uid if uid else None)
    return result


# ── Tag-removal gate ──────────────────────────────────────────────────────────

def _wait_clear(timeout: float, clear_seconds: float = 1.5) -> bool:
    """Return True once all readers are empty for clear_seconds in a row."""
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
                return True
        else:
            clear_since = None
        time.sleep(POLL_INTERVAL)
    return False


def wait_for_tags_removed(speak_fn=None) -> str:
    """Block until all RFID readers are empty, with escalating warnings.

    Args:
        speak_fn: optional callable(text) for audio output (e.g. misty.speak).

    Returns:
        'ok'        — all tags removed within the allowed window.
        'powerdown' — tags remained after two warnings; caller should end session.
    """
    _ensure_init()

    def _say(text: str):
        print(f"  [RFID] {text}")
        if speak_fn:
            speak_fn(text)

    _say("Please remove all your cards from the slots.")
    if _wait_clear(30.0):
        return "ok"

    _say("Cards still in the slots! Please take them all off now!")
    if _wait_clear(60.0):
        return "ok"

    _say("Cards left on too long. Ending this game session.")
    return "powerdown"


# ── Public API ────────────────────────────────────────────────────────────────

def run_detector(n_slots: int = N_READERS,
                 first_tag_event: threading.Event | None = None,
                 game_over_event: threading.Event | None = None,
                 inactivity_callback=None,
                 inactivity_secs: float = 30.0,
                 card_placed_callback=None) -> list[int] | None:
    """
    Wait for the player to place RFID cards in the slots, then submit with
    the green button.

    Args:
        n_slots:               how many slots to monitor (default: all 6).
        first_tag_event:       set the moment the first card is detected (starts timer).
        game_over_event:       when set externally (timer expired), returns None immediately.
        card_placed_callback:  called as callback(slot_index, game_id) whenever a new
                               card appears in a slot — use for live per-card feedback.

    Returns:
        Ordered list of game-integer IDs, or None if aborted / game over.
        Check game_over_event.is_set() after None to distinguish the two cases.
    """
    _ensure_init()

    done_event      = threading.Event()
    submitted_event = threading.Event()

    # Background thread only watches for first card (starts game timer)
    if first_tag_event is not None and not first_tag_event.is_set():
        threading.Thread(target=_first_tag_watcher,
                         args=(done_event, first_tag_event),
                         daemon=True).start()

    # Unblock submitted_event when Space / green button is pressed
    def _wait_for_space():
        import tty, termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            while True:
                ch = sys.stdin.read(1)
                if ch in (' ', '\r', '\n'):
                    break
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        submitted_event.set()

    threading.Thread(target=_wait_for_space, daemon=True).start()

    # Also unblock if the game-over timer fires
    def _watch_game_over():
        if game_over_event is not None:
            game_over_event.wait()
            submitted_event.set()

    threading.Thread(target=_watch_game_over, daemon=True).start()

    # After inactivity_secs with no submission, fire the reminder callback
    if inactivity_callback is not None:
        def _inactivity_timer():
            if not submitted_event.wait(timeout=inactivity_secs):
                if game_over_event is None or not game_over_event.is_set():
                    inactivity_callback()
        threading.Thread(target=_inactivity_timer, daemon=True).start()

    # Per-card live feedback — detect new cards as they are placed
    if card_placed_callback is not None:
        def _card_watcher():
            prev = [None] * n_slots
            while not done_event.is_set():
                current = _read_snapshot()
                for idx, (old_uid, new_uid) in enumerate(zip(prev, current)):
                    if old_uid is None and new_uid is not None:
                        game_id = _card_map.get(new_uid, 0)
                        card_placed_callback(idx, game_id)
                prev = current
                time.sleep(0.2)
        threading.Thread(target=_card_watcher, daemon=True).start()

    print()
    print("  Place your cards in the slots — slot 1 is step 1.")
    print("  Press the green button when ready.")
    print()

    submitted_event.wait()
    done_event.set()

    # Snapshot: read all readers at the moment Space was pressed
    snapshot = _read_snapshot()
    print(f"  [RFID] Snapshot: {snapshot}")

    # If zero cards present → abort
    if all(uid is None for uid in snapshot):
        print("[RFID] No cards detected — aborting game.")
        return None

    # Translate UIDs → game integers
    result: list[int] = []
    for idx, uid in enumerate(snapshot):
        if uid is None:
            game_id = 0
        else:
            game_id = _card_map.get(uid, 0)
            if game_id == 0:
                print(f"  ⚠  Slot {idx+1}: UID {uid} not in card map — treating as 0.")
        result.append(game_id)

    # Trim trailing zeros
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