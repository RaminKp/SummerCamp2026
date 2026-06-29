"""
misty_head_tracking_two.py — Two-player head tracking for Misty II

Uses Misty's onboard FaceRecognition event (bearing + elevation in degrees)
to track two children. The robot alternates its gaze between the leftmost
and rightmost detected face every 4-5 seconds.

Usage:
    python misty_head_tracking_two.py

Press Ctrl-C to stop. The script cleans up automatically.
"""

import json
import random
import threading
import time

import requests
import websocket

# ── Configuration ─────────────────────────────────────────────────────────────

MISTY_IP = "10.42.0.197"

# Gaze switching
SWITCH_INTERVAL_MIN = 4.0      # seconds — minimum time before switching target
SWITCH_INTERVAL_MAX = 5.0      # seconds — maximum time before switching target

# Face freshness — detections older than this are discarded
FACE_FRESHNESS_SECONDS = 1.5

# Head movement tuning
SMOOTHING_ALPHA = 0.5          # 0-1: lower = smoother but laggier, higher = snappier
HEAD_VELOCITY   = 45           # head motor speed (%)
CONTROL_HZ      = 10           # control loop rate

# Sign conventions — flip if Misty turns the wrong way (see README)
BEARING_SIGN   = +1            # flip to -1 if Misty turns away horizontally
ELEVATION_SIGN = -1            # flip if Misty tilts the wrong way vertically

# Hardware safety limits (degrees)
YAW_MIN, YAW_MAX     = -75, 75
PITCH_MIN, PITCH_MAX = -35, 22

# ── State ─────────────────────────────────────────────────────────────────────

_lock    = threading.Lock()
_running = True

# Dict of {track_id: {"bearing": float, "elevation": float, "time": float}}
_faces = {}

# Current smoothed head position
_head_yaw   = 0.0
_head_pitch = 0.0

# Gaze target: "left" or "right"
_current_side = "left"
_next_switch_time = 0.0

# ── Misty REST helpers ────────────────────────────────────────────────────────

def _post(endpoint, payload=None):
    try:
        requests.post(
            f"http://{MISTY_IP}/api/{endpoint}",
            json=payload or {},
            timeout=3,
        )
    except Exception:
        pass


def start_face_detection():
    _post("faces/detection/start")
    print("  Face detection started.")


def stop_face_detection():
    _post("faces/detection/stop")


def move_head(yaw, pitch):
    _post("head", {
        "Yaw":      round(max(YAW_MIN,  min(YAW_MAX,  yaw)),  1),
        "Pitch":    round(max(PITCH_MIN, min(PITCH_MAX, pitch)), 1),
        "Velocity": HEAD_VELOCITY,
    })


def change_led(r, g, b):
    _post("led", {"Red": r, "Green": g, "Blue": b})


def reset_head():
    move_head(0, 0)

# ── WebSocket — face event ingestion ──────────────────────────────────────────

WS_URL     = f"ws://{MISTY_IP}/pubsub"
FACE_EVENT = "TwoPlayerFace"


def _on_open(ws):
    sub = {
        "Operation":  "subscribe",
        "Type":       "FaceRecognition",
        "DebounceMs": 200,
        "EventName":  FACE_EVENT,
    }
    ws.send(json.dumps(sub))
    print("  Subscribed to FaceRecognition events.")


def _on_message(ws, message):
    """Store every detected face with its bearing, elevation, and timestamp."""
    try:
        data = json.loads(message)
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, TypeError):
                return
        if not isinstance(data, dict):
            return
        if data.get("eventName") != FACE_EVENT:
            return

        msg       = data.get("message", {})
        bearing   = float(msg.get("bearing",   0))
        elevation = float(msg.get("elevation", 0))
        track_id  = msg.get("trackId", msg.get("personName", "unknown"))

        with _lock:
            _faces[track_id] = {
                "bearing":   bearing,
                "elevation": elevation,
                "time":      time.time(),
            }
    except Exception as e:
        print(f"  [ws] parse error: {e}")


def _on_error(ws, error):
    print(f"  WebSocket error: {error}")


def _on_close(ws, *args):
    print("  WebSocket closed.")


def run_ws():
    """Keep the WebSocket connection alive, reconnecting on failure."""
    ws = websocket.WebSocketApp(
        WS_URL,
        on_open=_on_open,
        on_message=_on_message,
        on_error=_on_error,
        on_close=_on_close,
    )
    while _running:
        try:
            ws.run_forever(ping_interval=20)
        except Exception as e:
            print(f"  WS reconnect: {e}")
            time.sleep(2)

# ── Gaze control loop ────────────────────────────────────────────────────────

def _fresh_faces():
    """Return list of face dicts that were seen within FACE_FRESHNESS_SECONDS,
    sorted left-to-right by bearing."""
    now = time.time()
    with _lock:
        fresh = [
            f for f in _faces.values()
            if (now - f["time"]) < FACE_FRESHNESS_SECONDS
        ]
    # Sort by bearing: most-negative (leftmost from robot's POV) first
    fresh.sort(key=lambda f: f["bearing"])
    return fresh


def _pick_next_switch_time():
    return time.time() + random.uniform(SWITCH_INTERVAL_MIN, SWITCH_INTERVAL_MAX)


def run_control_loop():
    global _head_yaw, _head_pitch, _current_side, _next_switch_time

    _next_switch_time = _pick_next_switch_time()
    period = 1.0 / CONTROL_HZ

    print("  Control loop running.  Ctrl-C to stop.")

    while _running:
        loop_start = time.time()

        faces = _fresh_faces()
        n = len(faces)

        if n == 0:
            # No faces visible — hold current position
            time.sleep(period)
            continue

        # ── Pick the target face ──────────────────────────────────────────
        if n == 1:
            # Only one face: always look at it
            target = faces[0]
        else:
            # Two or more faces: use side-based selection
            if time.time() >= _next_switch_time:
                _current_side = "right" if _current_side == "left" else "left"
                _next_switch_time = _pick_next_switch_time()
                side_label = "Player A (left)" if _current_side == "left" else "Player B (right)"
                print(f"  >> Switched gaze to {side_label}")

            if _current_side == "left":
                target = faces[0]       # leftmost
            else:
                target = faces[-1]      # rightmost

        # ── Smooth toward the target ──────────────────────────────────────
        target_yaw   = BEARING_SIGN   * target["bearing"]
        target_pitch = ELEVATION_SIGN * target["elevation"]

        _head_yaw   += (target_yaw   - _head_yaw)   * SMOOTHING_ALPHA
        _head_pitch += (target_pitch - _head_pitch) * SMOOTHING_ALPHA

        move_head(_head_yaw, _head_pitch)

        # ── LED feedback (optional) ──────────────────────────────────────
        if n >= 2:
            if _current_side == "left":
                change_led(0, 200, 255)     # cyan  → looking at Player A
            else:
                change_led(255, 140, 0)     # orange → looking at Player B
        else:
            change_led(0, 255, 0)           # green → single player

        # ── Sleep for remainder of control period ─────────────────────────
        elapsed = time.time() - loop_start
        time.sleep(max(0, period - elapsed))

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    global _running

    print(f"Two-player head tracking — Misty @ {MISTY_IP}")
    print(f"  Switch interval: {SWITCH_INTERVAL_MIN}–{SWITCH_INTERVAL_MAX}s")
    start_face_detection()
    change_led(0, 255, 0)
    reset_head()

    ws_thread = threading.Thread(target=run_ws, daemon=True)
    ws_thread.start()

    try:
        run_control_loop()
    except KeyboardInterrupt:
        pass
    finally:
        _running = False
        print("\n  Shutting down...")
        stop_face_detection()
        reset_head()
        change_led(0, 0, 0)
        print("  Done.")


if __name__ == "__main__":
    main()