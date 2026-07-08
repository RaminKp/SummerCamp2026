"""
detector.py  (RFID edition)
---------------------------
Six MFRC522 RFID readers on SPI with software chip-select.

run_detector() -> list[int] | None

    Returns an ordered list of game-integer IDs when the player presses the
    green button, or None if the game was aborted/timed out.

    Pressing the green button with NO cards twice in a row quits the game.
    The first empty press prompts the player to try again.
"""

import sys
import json
import time
import queue
import threading
from pathlib import Path

import RPi.GPIO as GPIO

# ── Allow importing rfid_reader from the RFID sensor folder ───────────────────
sys.path.insert(0, "/home/unbcroboticslab/Desktop/Sensors/RFID")
import rfid_reader

# ── Config ────────────────────────────────────────────────────────────────────

CARD_MAP_PATH = Path(__file__).parent / "card_map.json"
N_READERS     = 6
POLL_INTERVAL = 0.05
BUZZER_PIN    = 18


# ── Module-level state ────────────────────────────────────────────────────────
_readers: list | None = None
_card_map: dict[str, int] = {}
_spi_lock = threading.Lock()   # prevents concurrent scan_once calls from multiple threads


def _load_card_map() -> dict[str, int]:
    if not CARD_MAP_PATH.exists():
        raise FileNotFoundError(
            f"Card map not found at {CARD_MAP_PATH}.\n"
            "Run  python enrol_cards.py  first to enrol your RFID cards."
        )
    return json.loads(CARD_MAP_PATH.read_text())


def _ensure_init():
    global _readers, _card_map
    if _readers is None:
        print("[RFID] Initialising six readers...")
        _readers = rfid_reader.build_readers()
        print("[RFID] Readers ready.")
    _card_map = _load_card_map()


def _buzz(duration: float = 0.1):
    try:
        GPIO.output(BUZZER_PIN, GPIO.HIGH)
        time.sleep(duration)
        GPIO.output(BUZZER_PIN, GPIO.LOW)
    except Exception:
        pass


# ── Background first-tag watcher ──────────────────────────────────────────────

def _first_tag_watcher(done_event: threading.Event,
                       first_tag_event: threading.Event):
    while not done_event.is_set() and not first_tag_event.is_set():
        with _spi_lock:
            for name, reader in _readers:
                if rfid_reader.scan_once(name, reader):
                    first_tag_event.set()
                    return
        time.sleep(POLL_INTERVAL)


# ── Snapshot read ─────────────────────────────────────────────────────────────

def _read_snapshot() -> list[str | None]:
    with _spi_lock:
        result = []
        for name, reader in _readers:
            uid = rfid_reader.scan_once(name, reader)
            result.append(uid if uid else None)
    return result


# ── Tag-removal gate ──────────────────────────────────────────────────────────

def _wait_clear(timeout: float, clear_seconds: float = 1.5) -> bool:
    deadline    = time.time() + timeout
    clear_since = None
    while time.time() < deadline:
        with _spi_lock:
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
                 inactivity_secs: float = 10.0,
                 inactivity_repeat_secs: float = 20.0,
                 card_placed_callback=None,
                 no_cards_callback=None) -> list[int] | None:
    """
    Wait for the player to place cards and press the green button.

    First empty press: calls no_cards_callback and waits for another press.
    Second empty press: returns None (game abort).
    game_over_event set: returns None immediately.
    """
    _ensure_init()

    done_event  = threading.Event()
    press_queue: queue.Queue = queue.Queue()

    # Background thread: watches for first card to start game timer
    if first_tag_event is not None and not first_tag_event.is_set():
        threading.Thread(target=_first_tag_watcher,
                         args=(done_event, first_tag_event),
                         daemon=True).start()

    # Puts 'press' on the queue for every green-button press (loops for retries)
    def _wait_for_space():
        import tty, termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            while not done_event.is_set():
                ch = sys.stdin.read(1)
                if ch in (' ', '\r', '\n'):
                    press_queue.put('press')
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    threading.Thread(target=_wait_for_space, daemon=True).start()

    # Unblocks queue if game-over timer fires
    def _watch_game_over():
        if game_over_event is not None:
            game_over_event.wait()
            press_queue.put('game_over')

    threading.Thread(target=_watch_game_over, daemon=True).start()

    # Fires inactivity reminder after inactivity_secs, then every repeat_secs
    if inactivity_callback is not None:
        def _inactivity_timer():
            time.sleep(inactivity_secs)
            while not done_event.is_set():
                if game_over_event is None or not game_over_event.is_set():
                    inactivity_callback()
                time.sleep(inactivity_repeat_secs)
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

    empty_presses = 0
    while True:
        event = press_queue.get()

        if event == 'game_over' or (game_over_event and game_over_event.is_set()):
            done_event.set()
            return None

        snapshot = _read_snapshot()
        print(f"  [RFID] Snapshot: {snapshot}")

        if all(uid is None for uid in snapshot):
            empty_presses += 1
            if empty_presses < 2:
                print("[RFID] No cards — prompting retry.")
                if no_cards_callback:
                    no_cards_callback()
                continue
            print("[RFID] No cards on second press — aborting.")
            done_event.set()
            return None

        done_event.set()
        break

    # Translate UIDs to game integers
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
    print("  Place cards, then press the green button.")
    print("=" * 50)

    result = run_detector()
    if result is not None:
        print(f"\nFinal sequence: {result}")
    else:
        print("\nAborted (no cards placed).")

    GPIO.cleanup()
