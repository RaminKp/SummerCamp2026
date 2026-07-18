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
import signal
import atexit
import threading
from pathlib import Path

# ── Module-level stdin reader (started once, avoids per-call thread races) ────
# Each run_detector() registers its press_queue here; keypresses are dispatched
# to whichever queue is currently active. Only one thread ever owns stdin.
_active_press_queue: queue.Queue | None = None
_active_press_queue_lock = threading.Lock()
_stdin_thread_started    = False
_term_fd: int | None     = None
_term_old                = None


def _restore_terminal():
    """Restore terminal to cooked mode — called on exit and Ctrl+C."""
    global _term_old, _term_fd
    if _term_old is not None and _term_fd is not None:
        try:
            import termios
            termios.tcsetattr(_term_fd, termios.TCSADRAIN, _term_old)
        except Exception:
            pass
        _term_old = None


atexit.register(_restore_terminal)


def _start_stdin_thread():
    global _stdin_thread_started, _term_fd, _term_old
    if _stdin_thread_started:
        return
    _stdin_thread_started = True

    def _reader():
        global _term_fd, _term_old
        import tty, termios
        _term_fd  = sys.stdin.fileno()
        _term_old = termios.tcgetattr(_term_fd)
        tty.setraw(_term_fd)
        try:
            while True:
                ch = sys.stdin.read(1)
                if ch == '\x03':          # Ctrl+C in raw mode
                    _restore_terminal()
                    signal.raise_signal(signal.SIGINT)
                    return
                if ch == '\x1c':          # Ctrl+\ — hard kill fallback
                    _restore_terminal()
                    signal.raise_signal(signal.SIGTERM)
                    return
                if ch in (' ', '\r', '\n'):
                    with _active_press_queue_lock:
                        q = _active_press_queue
                    if q is not None:
                        q.put('press')
        finally:
            _restore_terminal()

    threading.Thread(target=_reader, daemon=True).start()

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

# Movement gate — set while Misty is driving so SPI polling never competes
# with drive commands for CPU/GIL time.
_polling_paused = threading.Event()


def pause_rfid_polling():
    _polling_paused.set()


def resume_rfid_polling():
    _polling_paused.clear()


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
        if _polling_paused.is_set():
            time.sleep(0.2)
            continue
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

    _say("Let's remove all cards from the slot!")
    if _wait_clear(30.0):
        return "ok"

    _say("Cards still in the slots! Let's take them all off right now!")
    if _wait_clear(15.0):
        return "ok"

    _say("Cards left on too long. Ending this game session.")
    return "powerdown"


def wait_for_button(game_over_event: threading.Event | None = None) -> bool:
    """Block until the green button (space/enter) is pressed once.

    Returns True if the button was pressed, False if game_over fired first.
    Safe to call between run_detector() calls — uses the same stdin dispatcher.
    """
    global _active_press_queue
    q: queue.Queue = queue.Queue()
    _start_stdin_thread()
    with _active_press_queue_lock:
        _active_press_queue = q

    if game_over_event is not None:
        def _watch():
            game_over_event.wait()
            q.put("game_over")
        threading.Thread(target=_watch, daemon=True).start()

    event = q.get()
    with _active_press_queue_lock:
        _active_press_queue = None
    return event != "game_over"


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

    # Register this call's press_queue with the global stdin dispatcher
    global _active_press_queue
    _start_stdin_thread()
    with _active_press_queue_lock:
        _active_press_queue = press_queue

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
                if _polling_paused.is_set():
                    time.sleep(0.2)
                    continue
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
            with _active_press_queue_lock:
                _active_press_queue = None
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
            with _active_press_queue_lock:
                _active_press_queue = None
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

    # Deregister queue so stray keypresses don't reach the next round
    with _active_press_queue_lock:
        _active_press_queue = None

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
