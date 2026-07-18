import json
import time
import threading
import requests

try:
    import websocket as _websocket
    _WS_AVAILABLE = True
except ImportError:
    _websocket = None
    _WS_AVAILABLE = False

# ── Config ────────────────────────────────────────────────────────────────────

MISTY_IP = "10.42.0.197"
BASE_URL  = f"http://{MISTY_IP}/api"

# ── ✏️  Calibration ────────────────────────────────────────────────────────────
DRIVE_SPEED    = 35.0
TURN_SPEED     = 20.0
CM_PER_SECOND  = 24.3
DEG_PER_SECOND = 15.17

# ── ✏️  Voice / Audio ─────────────────────────────────────────────────────────
VOICE        = "en-gb-x-gbc-local"  # Android TTS voice installed on this robot
PITCH        = 1.3                   # >1 = higher pitch (clearer for young kids)
SPEECH_RATE  = 0.9                   # slightly faster for energy; still clear
VOLUME       = 65                    # speaker volume 0-100 (set once at startup)

# Separate sessions so drive commands, arm gestures, and general API calls
# never queue behind each other — requests.Session is not thread-safe for
# concurrent use across threads.
_session       = requests.Session()   # head, LED, speech, hazards, etc.
_drive_session = requests.Session()   # drive/time and drive/stop only
_arm_session   = requests.Session()   # wave / bye_gesture only


# ── WebSocket movement-completion tracking ────────────────────────────────────

_ws_app      = None
_ws_moving   = False
_ws_connected = False
_stopped_event = threading.Event()
_stopped_event.set()   # start as "already stopped"
_move_seen   = threading.Event()   # set when the WS reports actual motion

WS_STOP_TIMEOUT = 5.0  # fallback seconds after commanded duration


def _on_ws_message(ws, message):
    global _ws_moving
    try:
        msg = json.loads(message).get("message", {})
        lin = abs(float(msg.get("linearVelocity", 0)))
        ang = abs(float(msg.get("angularVelocity", 0)))
        if lin > 0.5 or ang > 0.5:
            _ws_moving = True
            _move_seen.set()
            _stopped_event.clear()
        elif _ws_moving:
            _ws_moving = False
            _stopped_event.set()
    except Exception:
        pass


def connect_ws():
    """Open a persistent WebSocket to receive LocomotionCommand events.

    Drive functions use this to know when Misty has actually stopped rather
    than guessing with a fixed sleep — eliminates move truncation on slower
    networks or when Misty decelerates longer than expected.
    """
    global _ws_app
    if not _WS_AVAILABLE:
        print("  [WS] websocket-client not installed — using sleep-based timing.")
        print("       Install with:  pip install websocket-client")
        return

    url = f"ws://{MISTY_IP}/pubsub"

    def _on_open(ws):
        ws.send(json.dumps({
            "Operation": "subscribe",
            "Type":      "LocomotionCommand",
            "DebounceMs": 0,
            "EventName": "LocomotionCommand",
            "Message":   "",
        }))
        print("  [WS] Subscribed to LocomotionCommand.")

    def _on_open_full(ws):
        global _ws_connected
        _ws_connected = True
        _on_open(ws)

    def _on_close(ws, c, m):
        global _ws_connected
        _ws_connected = False
        print("  [WS] Disconnected.")

    _ws_app = _websocket.WebSocketApp(
        url,
        on_open    = _on_open_full,
        on_message = _on_ws_message,
        on_error   = lambda ws, e: print(f"  [WS] Error: {e}"),
        on_close   = _on_close,
    )
    threading.Thread(
        target=lambda: _ws_app.run_forever(reconnect=5),
        daemon=True,
    ).start()
    time.sleep(1.0)
    print("  [WS] Connected to Misty.")


def _wait_stopped(fallback_ms: int):
    """Wait for the commanded move to complete using a calibrated sleep.

    WebSocket-based completion is unreliable for forward/back on this robot
    (events are intermittently missed, causing commands to be skipped).
    Using a fixed sleep keeps every command predictable for the demo.
    The WS connection stays open for logging/diagnostics only.
    """
    time.sleep(fallback_ms / 1000 + 0.5)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _post(endpoint: str, payload: dict, retries: int = 5,
          session: requests.Session | None = None) -> requests.Response:
    s = session or _session
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            r = s.post(f"{BASE_URL}/{endpoint}", json=payload, timeout=5)
            r.raise_for_status()
            return r
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.HTTPError) as e:
            last_err = e
            if attempt == retries:
                break
            print(f"    [retry {attempt}/{retries}] {endpoint} failed ({e}), retrying...")
            time.sleep(0.2)

    raise ConnectionError(
        f"Could not reach Misty at {MISTY_IP} after {retries} attempts "
        f"({last_err}). Check her IP and that she's on the same network."
    )


def _cm_to_ms(cm: float) -> int:
    return int((cm / CM_PER_SECOND) * 1000)


def _deg_to_ms(degrees: float) -> int:
    return int((degrees / DEG_PER_SECOND) * 1000)


# ── Drive commands ────────────────────────────────────────────────────────────

def _drive_time(linear: float, angular: float, ms: int):
    """Send one drive/time command and wait it out.

    Verified against the WebSocket: if the command was accepted but the event
    stream saw no actual motion during its window (command accepted, wheels
    never turned), re-send it ONCE. Only trusted while the WS is connected.
    """
    payload = {"linearVelocity": linear, "angularVelocity": angular, "timeMs": ms}
    _stopped_event.clear()
    _move_seen.clear()
    _post("drive/time", payload, session=_drive_session)
    _wait_stopped(ms)

    if _ws_connected and not _move_seen.is_set():
        print("    [drive] command accepted but NO motion seen — re-sending once")
        _stopped_event.clear()
        _move_seen.clear()
        _post("drive/time", payload, session=_drive_session)
        _wait_stopped(ms)


def forward(cm: float):
    ms = _cm_to_ms(cm)
    print(f"    → forward {cm}cm ({ms}ms)")
    _drive_time(DRIVE_SPEED, 0, ms)


def back(cm: float):
    ms = _cm_to_ms(cm)
    print(f"    → back {cm}cm ({ms}ms)")
    _drive_time(-DRIVE_SPEED, 0, ms)


def turn_left(degrees: float):
    ms = _deg_to_ms(degrees)
    print(f"    → turn left {degrees}° ({ms}ms)")
    _drive_time(0, TURN_SPEED, ms)


def turn_right(degrees: float):
    ms = _deg_to_ms(degrees)
    print(f"    → turn right {degrees}° ({ms}ms)")
    _drive_time(0, -TURN_SPEED, ms)


def turn_180():
    ms = _deg_to_ms(180)
    print(f"    → turn 180° ({ms}ms)")
    _drive_time(0, TURN_SPEED, ms)


def head(pitch: float = 0, roll: float = 0, yaw: float = 0, velocity: float = 60):
    """Move Misty's head. Pitch: negative = up, positive = down (range ~-40 to 26)."""
    _post("head", {"pitch": pitch, "roll": roll, "yaw": yaw, "velocity": velocity})
    time.sleep(0.5)


def stop():
    print("    → stop")
    _post("drive/stop", {}, session=_drive_session)


# ── Speech ────────────────────────────────────────────────────────────────────

def speak(text: str, wait: bool = True):
    print(f"    \"{text}\"")
    _post("tts/speak", {
        "Text":       text,
        "Flush":      True,
        "Voice":      VOICE,
        "Pitch":      PITCH,
        "SpeechRate": SPEECH_RATE,
    })
    if wait:
        words = max(1, len(text.split()))
        time.sleep(words / (2.6 * SPEECH_RATE) + 0.8)


# ── LED ───────────────────────────────────────────────────────────────────────

def led(r: int, g: int, b: int):
    _post("led", {"Red": r, "Green": g, "Blue": b})

def led_ready():   led(0, 80, 200)    # blue
def led_error():   led(200, 0, 0)     # red
def led_success(): led(0, 200, 80)    # green
def led_win():     led(255, 180, 0)   # gold


# ── Hazards ───────────────────────────────────────────────────────────────────

def set_volume(level: int = VOLUME):
    _post("audio/volume", {"Volume": level})


def disable_hazards():
    print("  Disabling hazard sensors...")
    _post("hazard/updatebasesettings", {
        "RevertToDefault": False,
        "DisableTimeOfFlights": True,
        "DisableBumpSensors": True
    })

def enable_hazards():
    print("  Re-enabling hazard sensors...")
    _post("hazard/updatebasesettings", {"RevertToDefault": True})


# ── Expressive ────────────────────────────────────────────────────────────────

def _arm(left_pos: float, right_pos: float, velocity: float = 85):
    """Single arm movement — fail fast (1 retry) so gesture failures never block."""
    try:
        _post("arms/set", {
            "leftArmPosition":  left_pos,
            "rightArmPosition": right_pos,
            "leftArmVelocity":  velocity,
            "rightArmVelocity": velocity,
        }, retries=1, session=_arm_session)
    except Exception as e:
        print(f"  [arm] {e}")


def _wave_sync():
    for pos in [-29, 60, -29, 60, -29, 90]:
        _arm(pos, pos)
        time.sleep(0.35)


def wave():
    """Wave both arms in the background — never blocks the drive system."""
    threading.Thread(target=_wave_sync, daemon=True).start()


def bye_gesture():
    """Wave both arms for goodbye (blocking — called when no drive follows)."""
    _wave_sync()


def celebrate():
    """Turn to face kids, wave, then celebrate with speech and a head nod."""
    turn_180()
    head(pitch=-40, yaw=-60)
    led_win()
    wave()
    speak("YESSSSS! All missions complete — you are an INCREDIBLE mission team!")
    # Head nod
    _post("head", {"pitch": -10, "roll": 0, "yaw": -60, "velocity": 60})
    time.sleep(0.4)
    _post("head", {"pitch": 10,  "roll": 0, "yaw": -60, "velocity": 60})
    time.sleep(0.4)
    _post("head", {"pitch": -40, "roll": 0, "yaw": -60, "velocity": 60})
    time.sleep(0.4)
    bye_gesture()




def execute_drive_map(drive_map: list[tuple]):
    for command in drive_map:
        print(f"    Executing: {command}")
        action = command[0]
        if action == "forward":
            forward(command[1])
        elif action == "back":
            back(command[1])
        elif action == "turn_left":
            turn_left(command[1])
        elif action == "turn_right":
            turn_right(command[1])
        elif action == "turn_180":
            turn_180()
        elif action == "stop":
            stop()
        else:
            raise ValueError(f"Unknown drive command: '{action}'")
        # Hard stop + settle between every command so residual momentum from
        # a forward does not carry into the next turn.
        stop()
        time.sleep(0.3)
    stop()   # final halt


# ── Connection test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "disable_hazards":
        disable_hazards()
        print("Hazards disabled.")
    elif len(sys.argv) > 1 and sys.argv[1] == "enable_hazards":
        enable_hazards()
        print("Hazards enabled.")
    else:
        print("Testing connection to Misty...")
        try:
            r = requests.get(f"{BASE_URL}/device", timeout=5)
            data = r.json()
            battery = data['result']['batteryLevel']['chargePercent']
            print(f"Connected!  Battery: {battery:.0%}")
            print("\nTesting LED...")
            led_ready();   time.sleep(0.8)
            led_error();   time.sleep(0.8)
            led_success(); time.sleep(0.8)
            led(0, 0, 0)
            print("LED OK.")
            print("\nTesting speech...")
            speak("Hello! I am ready to play the maze game.")
            print("All tests passed.")
        except Exception as e:
            print(f"Error: {e}")
