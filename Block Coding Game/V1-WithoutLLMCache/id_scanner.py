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
import time
from pathlib import Path

import cv2
import misty

# ── Config ────────────────────────────────────────────────────────────────────

USERS_PATH          = Path(__file__).parent.parent.parent / "Documents" / "users.json"
ARUCO_DICT          = cv2.aruco.DICT_6X6_1000   # covers IDs up to 999
POLL_INTERVAL       = 0.05                       # seconds between frame reads
STABLE_FRAMES       = 8                          # frames a marker must appear before accepting
FACE_STABLE_FRAMES  = 5                          # face frames before Misty greets


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
    if not data.get("consent", False):
        print(f"  [id_scanner] ID {aruco_id} has consent=false — skipping.")
        return None
    return {
        "aruco_id": aruco_id,
        "name":     data.get("name") or f"Player {aruco_id}",
        "age":      data.get("age", ""),
        "plays":    data.get("plays", 0),
    }


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


def _wait_for_face(cap, face_cascade) -> bool:
    """Block until a face is detected for FACE_STABLE_FRAMES consecutive frames.

    Returns True when a face is confirmed, False if cap fails immediately.
    """
    face_count = 0
    print("  Watching for a player...")
    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(POLL_INTERVAL)
            continue
        gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4)
        if len(faces) > 0:
            face_count += 1
            if face_count >= FACE_STABLE_FRAMES:
                return True
        else:
            face_count = 0
        time.sleep(POLL_INTERVAL)


# ── Public API ────────────────────────────────────────────────────────────────

def wait_for_players(n: int = 2) -> list[dict]:
    """Scan ArUco ID cards via USB webcam until n valid players are detected.

    Phase 1 — face detection: wait once for someone to approach, then greet.
    Phase 2 — ArUco scan: scan each player's ID card one at a time with a
    direct prompt per slot. No second face-detection round — avoids the race
    where player 1's face triggers another greeting before player 2 scans.
    Falls back to keyboard entry if no webcam is available.
    """
    users = _load_users()

    print(f"\n{'='*50}")
    print(f"  PLAYER CHECK-IN  ({n} players)")
    print(f"{'='*50}\n")

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("  [id_scanner] No webcam found — falling back to keyboard entry.")
        return _keyboard_fallback(n, users)

    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    dictionary = cv2.aruco.getPredefinedDictionary(ARUCO_DICT)
    detector   = cv2.aruco.ArucoDetector(dictionary, cv2.aruco.DetectorParameters())

    players_found: list[dict] = []
    ids_seen: set[int]        = set()

    try:
        # ── Phase 1: wait for someone to approach (once only) ─────────────────
        _wait_for_face(cap, face_cascade)
        misty.speak(
            "Hello there! I can see you! "
            "Both players, please get ready to show me your ID cards!"
        )

        # ── Phase 2: scan each player's ID card in turn ───────────────────────
        while len(players_found) < n:
            slot = len(players_found) + 1
            print(f"  Hold Player {slot}'s ID card up to the webcam...")
            misty.speak(f"Player {slot}, please hold your ID card up to the camera!")

            last_id      = None
            stable_count = 0

            while True:
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
                                # stay in inner loop — wait for a valid card
                                continue
                            ids_seen.add(aruco_id)
                            players_found.append(player)
                            name = player["name"]
                            print(f"  ✓ Player {slot}: {name} (ID {aruco_id})\n")
                            misty.speak(
                                f"Welcome, {name}! "
                                "I am so happy to have you on the mission team!"
                            )
                            time.sleep(1.0)   # brief pause before next slot
                            break             # accepted — exit for loop
                    else:
                        # for loop completed without break (no new valid marker)
                        time.sleep(POLL_INTERVAL)
                        continue             # keep scanning
                    break                   # for loop broke — card accepted, exit while
                else:
                    last_id      = None
                    stable_count = 0
                    time.sleep(POLL_INTERVAL)

    finally:
        cap.release()

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
