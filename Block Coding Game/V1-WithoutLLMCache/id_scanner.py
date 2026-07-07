"""
id_scanner.py — Scan ArUco ID cards via Misty's built-in camera.

Polls Misty's RGB camera over REST until two different registered IDs
have been detected. Looks each ID up in users.json.

Usage:
    from id_scanner import wait_for_players
    players = wait_for_players()   # blocks until 2 IDs scanned
"""

import base64
import json
import time
from pathlib import Path

import cv2
import numpy as np
import requests

import misty

# ── Config ────────────────────────────────────────────────────────────────────

USERS_PATH    = Path(__file__).parent.parent.parent / "Documents" / "users.json"
ARUCO_DICT    = cv2.aruco.DICT_6X6_1000   # covers IDs up to 999
POLL_INTERVAL = 0.3                        # seconds between camera polls

# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_users() -> dict:
    try:
        return json.loads(USERS_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  [id_scanner] Could not load users.json: {e}")
        return {}


def _detect_aruco(frame: np.ndarray) -> list[int]:
    dictionary = cv2.aruco.getPredefinedDictionary(ARUCO_DICT)
    detector   = cv2.aruco.ArucoDetector(dictionary, cv2.aruco.DetectorParameters())
    _, ids, _  = detector.detectMarkers(frame)
    if ids is None:
        return []
    return [int(i[0]) for i in ids]


def _grab_misty_frame() -> np.ndarray | None:
    try:
        r = requests.get(
            f"http://{misty.MISTY_IP}/api/cameras/rgb",
            params={"Base64": "true"},
            timeout=5,
        )
        if r.status_code != 200:
            return None
        img_b64 = r.json().get("result", {}).get("base64", "")
        if not img_b64:
            return None
        img_bytes = base64.b64decode(img_b64)
        return cv2.imdecode(np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_COLOR)
    except Exception as e:
        print(f"  [id_scanner] Camera error: {e}")
        return None


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


# ── Public API ────────────────────────────────────────────────────────────────

def wait_for_players(n: int = 2) -> list[dict]:
    """Prompt the facilitator to type each player's ID number.

    Looks up each ID in users.json. Keeps asking until n valid IDs are entered.
    Returns a list of n player dicts ordered by entry.
    """
    users         = _load_users()
    players_found: list[dict] = []
    ids_seen: set[int]        = set()

    print(f"\n{'='*50}")
    print(f"  PLAYER CHECK-IN  ({n} players)")
    print(f"{'='*50}\n")

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
        print(f"  ✓ Player {slot}: {player['name']} (ID {aruco_id})\n")

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
