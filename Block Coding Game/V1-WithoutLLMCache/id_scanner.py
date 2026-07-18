"""
id_scanner.py — Detect player ID cards via USB webcam (ArUco markers).

Polls a local USB webcam until two different registered IDs have been
detected with stable readings. Falls back to keyboard entry if no webcam
is found. Looks each ID up in users.json.

Face detection: watches for a face via Haar cascade and has Misty greet
the child and ask them to show their ID before scanning begins.

Usage:
    from id_scanner import wait_for_players
    players = wait_for_players()   # blocks until 2 IDs scanned
"""

import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import requests
import misty

# ── Config ────────────────────────────────────────────────────────────────────

USERS_PATH      = Path(__file__).parent.parent.parent / "Documents" / "users.json"
ARUCO_DICT      = cv2.aruco.DICT_6X6_1000   # covers IDs up to 999
POLL_INTERVAL   = 0.05                       # seconds between frame reads (USB webcam)
MISTY_POLL_INTERVAL = 0.15                   # seconds between frame fetches (~6 fps, matches proven setup)
STABLE_FRAMES   = 8                          # frames a marker must appear before accepting
MOTION_PIXELS   = 2000                       # foreground pixels to count as "someone arrived"
MOTION_STABLE   = 4                          # consecutive motion frames before prompting

# ── Camera selection ──────────────────────────────────────────────────────────
# Set to True to use Misty's front camera, False to use the local USB webcam.
USE_MISTY_CAMERA = True


# ── Misty camera helpers ──────────────────────────────────────────────────────

def _reset_misty_camera():
    """Cycle Misty's camera service to clear a stuck capture lock (409 busy)."""
    try:
        requests.post(f"http://{misty.MISTY_IP}/api/services/camera/disable",
                      json={}, timeout=3.0)
        time.sleep(2.0)
        requests.post(f"http://{misty.MISTY_IP}/api/services/camera/enable",
                      json={}, timeout=3.0)
        time.sleep(3.0)
        print("  [misty_cam] Camera service reset.")
    except Exception as e:
        print(f"  [misty_cam] reset failed: {e}")


def _read_misty_frame():
    """Fetch one 640x480 JPEG frame from Misty's camera (binary mode).
    Returns an OpenCV BGR image or None."""
    try:
        r = requests.get(
            f"http://{misty.MISTY_IP}/api/cameras/rgb",
            params={"Width": 640, "Height": 480},
            timeout=1.5,
        )
        if r.status_code == 200 and len(r.content) > 100:
            return cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
        if r.status_code == 409:
            print("  [misty_cam] Camera busy — resetting service...")
            _reset_misty_camera()
    except Exception as e:
        print(f"  [misty_cam] {e}")
    return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_users() -> dict:
    try:
        return json.loads(USERS_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  [id_scanner] Could not load users.json: {e}")
        return {}


def _player_from_id(aruco_id: int, users: dict) -> dict | None:
    data = users.get(str(aruco_id))
    if data is None:
        return None
    # consent=false only blocks video recording, not playing
    return {
        "aruco_id": aruco_id,
        "name":     data.get("name") or f"Player {aruco_id}",
        "age":      data.get("age", ""),
        "plays":    data.get("plays", 0),
        "no_video": not data.get("consent", False),
    }


def _wait_for_presence(cap) -> None:
    """Block until motion is detected — someone walked up to the camera."""
    subtractor = cv2.createBackgroundSubtractorMOG2(history=60, varThreshold=40,
                                                     detectShadows=False)
    stable = 0
    print("  Watching for players to approach...")
    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(POLL_INTERVAL)
            continue
        small  = cv2.resize(frame, (320, 240))
        mask   = subtractor.apply(small)
        motion = cv2.countNonZero(mask)
        if motion > MOTION_PIXELS:
            stable += 1
            if stable >= MOTION_STABLE:
                return
        else:
            stable = 0
        time.sleep(POLL_INTERVAL)


def _wait_for_button():
    """Block until the green button (space/enter) is pressed."""
    import tty, termios, signal
    fd  = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while True:
            ch = sys.stdin.read(1)
            if ch == '\x03':   # Ctrl+C in raw mode
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
                signal.raise_signal(signal.SIGINT)
                return
            if ch in (' ', '\r', '\n'):
                return
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _keyboard_fallback(n: int, users: dict) -> list[dict]:
    """Manual ID entry used when webcam is unavailable."""
    players_found: list[dict] = []
    ids_seen: set[int]        = set()
    while len(players_found) < n:
        slot = len(players_found) + 1
        raw  = input(f"  Enter Player {slot} ID: ").strip()
        if not raw.isdigit():
            print("  Please enter a number.")
            continue
        aruco_id = int(raw)
        if aruco_id in ids_seen:
            print(f"  ID {aruco_id} already entered — use a different ID.")
            continue
        player = _player_from_id(aruco_id, users)
        if player is None:
            print(f"  ID {aruco_id} not found in users.json (or consent=false) — try again.")
            continue
        ids_seen.add(aruco_id)
        players_found.append(player)
        name = player["name"]
        misty.speak(f"Welcome, {name}! I am so happy to have you on the mission team!")
        print(f"  ✓ Player {slot}: {name} (ID {aruco_id})\n")
    return players_found


def _wait_for_presence(cap) -> None:
    """Block until motion is detected — someone walked up to the camera.

    Uses background subtraction (MOG2) on a downscaled frame so it runs fast
    on the Pi. No model needed; works in any lighting.
    """
    subtractor = cv2.createBackgroundSubtractorMOG2(history=60, varThreshold=40,
                                                     detectShadows=False)
    stable = 0
    print("  Waiting for players to approach...")
    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(POLL_INTERVAL)
            continue
        small  = cv2.resize(frame, (320, 240))
        mask   = subtractor.apply(small)
        motion = cv2.countNonZero(mask)
        if motion > MOTION_PIXELS:
            stable += 1
            if stable >= MOTION_STABLE:
                return
        else:
            stable = 0
        time.sleep(POLL_INTERVAL)


# ── Public API ────────────────────────────────────────────────────────────────

def wait_for_players(n: int = 2) -> list[dict]:
    """Wait for a green-button press, then scan n players' ArUco ID cards.

    Button press starts the flow and triggers video recording in main.py.
    consent=false players can play — they are just not recorded.
    Falls back to keyboard entry if no webcam is available.
    Returns list of player dicts, each with a 'no_video' bool.
    """
    users = _load_users()

    print(f"\n{'='*50}")
    print(f"  PLAYER CHECK-IN  ({n} players)")
    print(f"{'='*50}\n")

    if USE_MISTY_CAMERA:
        return _wait_for_players_misty(n, users)

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("  [id_scanner] No webcam found — falling back to keyboard entry.")
        misty.speak("Press the green button when you are ready to play!")
        _wait_for_button()
        return _keyboard_fallback(n, users)

    # ── Phase 1: motion detection — wait until someone approaches ────────────
    _wait_for_presence(cap)
    print("  Someone detected — prompting for button press.")
    misty.speak("Hello there! Press the green button when you are ready to play!")

    # ── Phase 2: wait for green button press ──────────────────────────────────
    _wait_for_button()
    print("  Button pressed — starting ID scan.")
    misty.speak("Great! Both players, please show me your ID cards!")

    dictionary = cv2.aruco.getPredefinedDictionary(ARUCO_DICT)
    detector   = cv2.aruco.ArucoDetector(dictionary, cv2.aruco.DetectorParameters())

    players_found: list[dict] = []
    ids_seen: set[int]        = set()

    try:
        while len(players_found) < n:
            slot = len(players_found) + 1
            print(f"  Hold Player {slot}'s ID card up to the webcam...")
            misty.speak(f"Player {slot}, please hold your ID card up to the camera!")

            last_id      = None
            stable_count = 0
            last_prompt  = time.time()

            while True:
                if time.time() - last_prompt >= 15.0:
                    misty.speak(
                        f"I am still waiting! Player {slot}, please hold your ID card up to the camera!",
                        wait=False,
                    )
                    last_prompt = time.time()

                ret, frame = cap.read()
                if not ret:
                    time.sleep(POLL_INTERVAL)
                    continue

                _, ids, _ = detector.detectMarkers(frame)

                if ids is not None:
                    for id_arr in ids:
                        aruco_id = int(id_arr[0])

                        if aruco_id in ids_seen:
                            continue

                        if aruco_id == last_id:
                            stable_count += 1
                        else:
                            last_id      = aruco_id
                            stable_count = 1

                        if stable_count >= STABLE_FRAMES:
                            player = _player_from_id(aruco_id, users)
                            if player is None:
                                print(f"  ID {aruco_id} not registered — try another card.")
                                misty.speak("Hmm, I don't recognise that card. Try another!")
                                last_id      = None
                                stable_count = 0
                                continue
                            ids_seen.add(aruco_id)
                            players_found.append(player)
                            name = player["name"]
                            print(f"  ✓ Player {slot}: {name} (ID {aruco_id})"
                                  f"  [no_video={player['no_video']}]\n")
                            misty.speak(
                                f"Welcome, {name}! "
                                "I am so happy to have you on the mission team!"
                            )
                            time.sleep(1.0)
                            break
                    else:
                        time.sleep(POLL_INTERVAL)
                        continue
                    break
                else:
                    last_id      = None
                    stable_count = 0
                    time.sleep(POLL_INTERVAL)

    finally:
        cap.release()

    return players_found


def _wait_for_players_misty(n: int, users: dict) -> list[dict]:
    """ID scan using Misty's front camera instead of a USB webcam."""
    print("  [id_scanner] Using Misty's camera for ArUco scanning.")

    # Presence detection: fetch frames and run MOG2 on them
    subtractor = cv2.createBackgroundSubtractorMOG2(history=60, varThreshold=40,
                                                     detectShadows=False)
    stable = 0
    print("  Watching for players to approach (Misty's camera)...")
    while True:
        frame = _read_misty_frame()
        if frame is None:
            time.sleep(MISTY_POLL_INTERVAL)
            continue
        small  = cv2.resize(frame, (320, 240))
        mask   = subtractor.apply(small)
        motion = cv2.countNonZero(mask)
        if motion > MOTION_PIXELS:
            stable += 1
            if stable >= MOTION_STABLE:
                break
        else:
            stable = 0
        time.sleep(MISTY_POLL_INTERVAL)

    print("  Someone detected — prompting for button press.")
    misty.speak("Hello there! Press the green button when you are ready to play!")
    _wait_for_button()
    print("  Button pressed — starting ID scan.")
    misty.speak("Great! Both players, please show me your ID cards!")

    dictionary = cv2.aruco.getPredefinedDictionary(ARUCO_DICT)
    detector   = cv2.aruco.ArucoDetector(dictionary, cv2.aruco.DetectorParameters())

    players_found: list[dict] = []
    ids_seen: set[int]        = set()

    while len(players_found) < n:
        slot = len(players_found) + 1
        print(f"  Hold Player {slot}'s ID card up to Misty's camera...")
        misty.speak(f"Player {slot}, please hold your ID card up to my camera!")

        last_id      = None
        stable_count = 0
        last_prompt  = time.time()

        while True:
            if time.time() - last_prompt >= 15.0:
                misty.speak(
                    f"I am still waiting! Player {slot}, hold your ID card up to my camera!",
                    wait=False,
                )
                last_prompt = time.time()

            frame = _read_misty_frame()
            if frame is None:
                time.sleep(MISTY_POLL_INTERVAL)
                continue

            _, ids, _ = detector.detectMarkers(frame)

            if ids is not None:
                for id_arr in ids:
                    aruco_id = int(id_arr[0])
                    if aruco_id in ids_seen:
                        continue
                    if aruco_id == last_id:
                        stable_count += 1
                    else:
                        last_id      = aruco_id
                        stable_count = 1

                    if stable_count >= STABLE_FRAMES:
                        player = _player_from_id(aruco_id, users)
                        if player is None:
                            print(f"  ID {aruco_id} not registered — try another card.")
                            misty.speak("Hmm, I don't recognise that card. Try another!")
                            last_id      = None
                            stable_count = 0
                            continue
                        ids_seen.add(aruco_id)
                        players_found.append(player)
                        name = player["name"]
                        print(f"  ✓ Player {slot}: {name} (ID {aruco_id})"
                              f"  [no_video={player['no_video']}]\n")
                        misty.speak(
                            f"Welcome, {name}! "
                            "I am so happy to have you on the mission team!"
                        )
                        time.sleep(1.0)
                        break
                else:
                    time.sleep(MISTY_POLL_INTERVAL)
                    continue
                break
            else:
                last_id      = None
                stable_count = 0
                time.sleep(MISTY_POLL_INTERVAL)

    return players_found


def update_play_counts(players: list[dict]):
    """Increment the plays counter for each player in users.json."""
    try:
        users = json.loads(USERS_PATH.read_text(encoding="utf-8"))
        for player in players:
            key = str(player["aruco_id"])
            if key in users:
                users[key]["plays"] = users[key].get("plays", 0) + 1
        USERS_PATH.write_text(
            json.dumps(users, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as e:
        print(f"  [id_scanner] Could not update play counts: {e}")


if __name__ == "__main__":
    players = wait_for_players(2)
    print("\nPlayers ready:")
    for p in players:
        print(f"  {p['name']} (ID {p['aruco_id']}, age {p['age']}, "
              f"plays before today: {p['plays']})")
