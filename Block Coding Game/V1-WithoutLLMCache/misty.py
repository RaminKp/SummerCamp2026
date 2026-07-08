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
CM_PER_SECOND  = 23.3
DEG_PER_SECOND = 15.17

# ── ✏️  Voice / Audio ─────────────────────────────────────────────────────────
VOICE        = "en-us-x-sfg-local"  # Android TTS voice installed on this robot
PITCH        = 1.2                   # >1 = higher pitch (clearer for young kids)
SPEECH_RATE  = 0.75                  # <1 = slower/clearer for kids
VOLUME       = 90                    # speaker volume 0-100 (set once at startup)

# Reuse one TCP connection for every request instead of a new handshake per
# command — on a flaky/congested hotspot link the handshake itself is a
# common point of packet loss.
_session = requests.Session()


# ── WebSocket movement-completion tracking ────────────────────────────────────

_ws_app      = None
_ws_moving   = False
_stopped_event = threading.Event()
_stopped_event.set()   # start as "already stopped"

WS_STOP_TIMEOUT = 5.0  # fallback seconds after commanded duration


def _on_ws_message(ws, message):
    global _ws_moving
    try:
        msg = json.loads(message).get("message", {})
        lin = abs(float(msg.get("linearVelocity", 0)))
        ang = abs(float(msg.get("angularVelocity", 0)))
        if lin > 0.5 or ang > 0.5:
            _ws_moving = True
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

    _ws_app = _websocket.WebSocketApp(
        url,
        on_open    = _on_open,
        on_message = _on_ws_message,
        on_error   = lambda ws, e: print(f"  [WS] Error: {e}"),
        on_close   = lambda ws, c, m: print("  [WS] Disconnected."),
    )
    threading.Thread(
        target=lambda: _ws_app.run_forever(reconnect=5),
        daemon=True,
    ).start()
    time.sleep(1.0)
    print("  [WS] Connected to Misty.")


def _wait_stopped(fallback_ms: int):
    """Wait until Misty reports zero velocity, or fall back to sleep + buffer.

    First waits up to 1s for the robot to actually START moving (nonzero
    velocity seen on WS). If movement is never detected, the WS message was
    lost — fall back to a timed sleep for this command only, leaving the
    event state clean for the next command.
    """
    if not (_WS_AVAILABLE and _ws_app is not None):
        time.sleep(fallback_ms / 1000 + 0.5)
        return

    # Wait for movement to begin (proves WS is tracking this command)
    start = time.time()
    while not _ws_moving and time.time() - start < 1.0:
        time.sleep(0.05)

    if not _ws_moving:
        # WS missed the movement start — sleep for the commanded duration
        print("  [WS] Movement not detected — sleep fallback for this command.")
        _stopped_event.set()   # leave event in a clean (set) state
        time.sleep(fallback_ms / 1000 + 0.5)
        return

    # Movement confirmed — wait for Misty to stop
    timeout = fallback_ms / 1000 + WS_STOP_TIMEOUT
    if not _stopped_event.wait(timeout=timeout):
        print(f"  [WS] Stop timeout after {timeout:.1f}s — continuing.")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _post(endpoint: str, payload: dict, retries: int = 5) -> requests.Response:
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            r = _session.post(f"{BASE_URL}/{endpoint}", json=payload, timeout=5)
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

def forward(cm: float):
    ms = _cm_to_ms(cm)
    print(f"    → forward {cm}cm ({ms}ms)")
    _stopped_event.clear()
    _post("drive/time", {"LinearVelocity": DRIVE_SPEED, "AngularVelocity": 0, "TimeMs": ms})
    _wait_stopped(ms)


def back(cm: float):
    ms = _cm_to_ms(cm)
    print(f"    → back {cm}cm ({ms}ms)")
    _stopped_event.clear()
    _post("drive/time", {"LinearVelocity": -DRIVE_SPEED, "AngularVelocity": 0, "TimeMs": ms})
    _wait_stopped(ms)


def turn_left(degrees: float):
    ms = _deg_to_ms(degrees)
    print(f"    → turn left {degrees}° ({ms}ms)")
    _stopped_event.clear()
    _post("drive/time", {"LinearVelocity": 0, "AngularVelocity": TURN_SPEED, "TimeMs": ms})
    _wait_stopped(ms)


def turn_right(degrees: float):
    ms = _deg_to_ms(degrees)
    print(f"    → turn right {degrees}° ({ms}ms)")
    _stopped_event.clear()
    _post("drive/time", {"LinearVelocity": 0, "AngularVelocity": -TURN_SPEED, "TimeMs": ms})
    _wait_stopped(ms)


def turn_180():
    ms = _deg_to_ms(180)
    print(f"    → turn 180° ({ms}ms)")
    _stopped_event.clear()
    _post("drive/time", {"LinearVelocity": 0, "AngularVelocity": TURN_SPEED, "TimeMs": ms})
    _wait_stopped(ms)


def head(pitch: float = 0, roll: float = 0, yaw: float = 0, velocity: float = 60):
    """Move Misty's head. Pitch: negative = up, positive = down (range ~-40 to 26)."""
    _post("head", {"Pitch": pitch, "Roll": roll, "Yaw": yaw, "Velocity": velocity})
    time.sleep(0.5)


def stop():
    print("    → stop")
    _post("drive/stop", {})


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

def celebrate():
    """Turn to face kids, then celebrate with speech and a head nod."""
    turn_180()
    head(pitch=-40)
    led_win()
    speak("Congratulations, mission team! All missions complete — you are incredible!")
    # Head nod
    _post("head", {"Pitch": -10, "Roll": 0, "Yaw": 0, "Velocity": 60})
    time.sleep(0.4)
    _post("head", {"Pitch": 10, "Roll": 0, "Yaw": 0, "Velocity": 60})
    time.sleep(0.4)
    _post("head", {"Pitch": 0, "Roll": 0, "Yaw": 0, "Velocity": 60})


def recalibrate_at_home(marker_id: int = 0, nudge_deg: float = 8.0):
    """
    Take a photo with Misty's camera, detect the home ArUco marker,
    and nudge left/right to re-centre. Place marker ID 0 on the wall/floor
    directly in front of Misty's home position at camera height.
    """
    import base64
    import numpy as np
    import cv2

    print("  [recalibrate] Taking picture...")
    try:
        r = requests.get(f"{BASE_URL}/cameras/rgb", params={"Base64": "true"}, timeout=10)
        r.raise_for_status()
        img_b64 = r.json()["result"]["base64"]
    except Exception as e:
        print(f"  [recalibrate] Camera error: {e} — skipping")
        return

    img_bytes  = base64.b64decode(img_b64)
    frame      = cv2.imdecode(np.frombuffer(img_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    detector   = cv2.aruco.ArucoDetector(dictionary, cv2.aruco.DetectorParameters())
    corners, ids, _ = detector.detectMarkers(frame)

    if ids is None:
        print(f"  [recalibrate] No markers detected — skipping")
        return

    for i, mid in enumerate(ids):
        if int(mid[0]) == marker_id:
            cx         = corners[i][0][:, 0].mean()
            frame_cx   = frame.shape[1] / 2
            offset_px  = cx - frame_cx          # + = marker is right → robot drifted left
            threshold  = frame.shape[1] * 0.05  # 5 % of frame width

            if offset_px > threshold:
                print(f"  [recalibrate] Drifted left ({offset_px:.0f}px) — nudging right {nudge_deg}°")
                turn_right(nudge_deg)
            elif offset_px < -threshold:
                print(f"  [recalibrate] Drifted right ({abs(offset_px):.0f}px) — nudging left {nudge_deg}°")
                turn_left(nudge_deg)
            else:
                print(f"  [recalibrate] On target (offset {offset_px:.0f}px) — no correction")
            return

    print(f"  [recalibrate] Marker {marker_id} not in frame — skipping")


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
    stop()   # ensure Misty halts fully after the last command


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
