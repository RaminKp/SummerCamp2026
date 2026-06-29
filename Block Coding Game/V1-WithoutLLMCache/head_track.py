"""
head_track.py — Misty II head tracking + LLM natural speech
Run standalone: python head_track.py

Features:
  - Misty's head follows your face using her built-in face detection
  - Press ENTER to speak to Misty (text input) — she replies via Claude + TTS
  - Ctrl+C to quit

Requirements:
    pip install websocket-client
    Ollama running locally: https://ollama.com  (ollama pull llama3.2:1b)
"""

import json
import os
import threading
import time

import requests
import websocket

import misty

# ── Config ────────────────────────────────────────────────────────────────────

WS_URL          = f"ws://{misty.MISTY_IP}/pubsub"
HEAD_VELOCITY   = 40          # lower = smoother head movement
HEAD_SMOOTHING  = 0.12        # lower = less jerky (was 0.4)
HEAD_DEAD_ZONE  = 5.0         # degrees — ignore tiny movements
FACE_EVENT      = "FaceDetect"
MAX_HISTORY     = 10          # conversation turns kept in context
OLLAMA_URL      = "http://localhost:11434/api/chat"
OLLAMA_MODEL    = "llama3.2:1b"   # change to "phi3:mini" etc.

# Head range limits (Misty II hardware)
YAW_MIN, YAW_MAX     = -90,  90   # left / right
PITCH_MIN, PITCH_MAX = -40,  26   # down / up

# ── State ─────────────────────────────────────────────────────────────────────

_current_yaw   = 0.0
_current_pitch = 0.0
_lock          = threading.Lock()
_running       = True
_conversation  = []   # list of {"role": ..., "content": ...}

# ── Misty REST helpers ────────────────────────────────────────────────────────

def _post(endpoint, payload):
    try:
        requests.post(f"http://{misty.MISTY_IP}/api/{endpoint}", json=payload, timeout=3)
    except Exception:
        pass


def start_face_detection():
    _post("faces/detection/start", {})
    print("  Face detection started.")


def stop_face_detection():
    _post("faces/detection/stop", {})


def move_head(yaw: float, pitch: float):
    _post("head", {
        "Yaw":      round(max(YAW_MIN,   min(YAW_MAX,   yaw)),   1),
        "Pitch":    round(max(PITCH_MIN, min(PITCH_MAX, pitch)), 1),
        "Velocity": HEAD_VELOCITY,
    })


def reset_head():
    move_head(0, 0)

# ── WebSocket — face tracking ─────────────────────────────────────────────────

def _on_open(ws):
    sub = {
        "Operation":  "subscribe",
        "Type":       "FaceRecognition",
        "DebounceMs": 300,
        "EventName":  FACE_EVENT,
    }
    ws.send(json.dumps(sub))
    print("  Subscribed to face detection events.")


def _on_message(ws, message):
    global _current_yaw, _current_pitch
    try:
        data = json.loads(message)
        if isinstance(data, str):
            data = json.loads(data)
        if data.get("eventName") != FACE_EVENT:
            return

        msg       = data.get("message", {})
        bearing   = float(msg.get("bearing",   0))   # degrees: + = right
        elevation = float(msg.get("elevation", 0))   # degrees: + = up

        with _lock:
            # Skip tiny movements
            if (abs(bearing - _current_yaw) < HEAD_DEAD_ZONE and
                    abs(elevation - _current_pitch) < HEAD_DEAD_ZONE):
                return

            # Smooth toward the new target
            _current_yaw   += (bearing   - _current_yaw)   * HEAD_SMOOTHING
            _current_pitch += (elevation - _current_pitch) * HEAD_SMOOTHING

            # Misty's yaw: positive = right, bearing positive = face to the right
            move_head(-_current_yaw, _current_pitch)

    except Exception as e:
        print(f"  [head] error: {e}")


def _on_error(ws, error):
    print(f"  WebSocket error: {error}")


def _on_close(ws, *args):
    print("  WebSocket closed.")


def run_head_tracking():
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

# ── LLM natural speech ────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are Misty, a friendly and curious social robot made by Misty Robotics. "
    "You are talking to a person standing in front of you. "
    "Keep replies short — 1 to 3 sentences — since you'll be speaking them aloud. "
    "Be warm, engaging, and occasionally a little playful."
)


def chat_with_misty(user_text: str) -> str:
    _conversation.append({"role": "user", "content": user_text})

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + _conversation[-MAX_HISTORY:]

    response = requests.post(OLLAMA_URL, json={
        "model":    OLLAMA_MODEL,
        "messages": messages,
        "stream":   False,
    }, timeout=30)
    response.raise_for_status()

    reply = response.json()["message"]["content"].strip()
    _conversation.append({"role": "assistant", "content": reply})
    return reply


def run_conversation():
    print("\n  Type a message and press ENTER to talk to Misty.")
    print("  Leave blank + ENTER to skip. Ctrl+C to quit.\n")
    while _running:
        try:
            user_input = input("  You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input:
            continue

        print("  Misty thinking...")
        reply = chat_with_misty(user_input)
        print(f"  Misty: {reply}")
        misty.speak(reply, wait=True)

# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    global _running

    print("Starting Misty head tracking + LLM speech (Ollama)...")
    misty.disable_hazards()
    start_face_detection()
    reset_head()

    tracker = threading.Thread(target=run_head_tracking, daemon=True)
    tracker.start()

    try:
        run_conversation()
    except KeyboardInterrupt:
        pass
    finally:
        _running = False
        print("\nShutting down...")
        stop_face_detection()
        reset_head()
        misty.enable_hazards()
        print("Done.")


if __name__ == "__main__":
    run()
