"""
enrol_cards.py
--------------
Interactive card enrolment tool for the Blossom Maze game.

Run this script ONCE (or whenever you get new cards) to teach the system
which physical RFID card represents which game action:

    1 = Forward
    2 = Turn Left
    3 = Turn Right

Multiple physical cards can be enrolled for the same action — useful when
the game needs several "Forward" cards in a sequence, for example.

The script scans one reader at a time.  Tap each card you want to assign
to a game ID, and the UID→ID mapping is saved to card_map.json in this
directory.  detector.py loads that file automatically at game startup.

Usage:
    cd /home/unbcroboticslab/Desktop/blossom_game
    python enrol_cards.py
"""

import sys
import json
import time
import threading
from pathlib import Path

# Allow importing rfid_reader from the sibling RFID folder
sys.path.insert(0, "/home/unbcroboticslab/Desktop/Sensors/RFID")
import rfid_reader

CARD_MAP_PATH = Path(__file__).parent / "card_map.json"

# Game IDs and human-readable labels
GAME_IDS = {
    1: "Forward",
    2: "Turn Left",
    3: "Turn Right",
}

ENROL_READER_INDEX = 0   # use Reader 1 (index 0) for all enrolments


def read_one_card(reader_pair: tuple, timeout: float = 15.0) -> str | None:
    """Block until a card is tapped on the enrolment reader, then return its UID."""
    name, reader = reader_pair
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        uid = rfid_reader.scan_once(name, reader)
        if uid:
            return uid
        time.sleep(0.05)
    return None


def main():
    print("=" * 55)
    print("  Blossom Maze — RFID Card Enrolment")
    print("=" * 55)
    print()
    print("This script maps each physical RFID card to a game action.")
    print(f"Results will be saved to: {CARD_MAP_PATH}\n")

    # Load existing map so we can update rather than overwrite
    existing: dict[str, int] = {}
    if CARD_MAP_PATH.exists():
        try:
            existing = json.loads(CARD_MAP_PATH.read_text())
            print(f"Loaded existing map with {len(existing)} card(s).\n")
        except Exception:
            print("Warning: could not read existing card_map.json — starting fresh.\n")

    print("Initialising RFID readers...")
    readers = rfid_reader.build_readers()
    enrol_reader = readers[ENROL_READER_INDEX]
    print(f"Using {enrol_reader[0]} for enrolment.\n")

    card_map: dict[str, int] = dict(existing)

    for game_id, label in GAME_IDS.items():
        # Show cards already enrolled for this ID
        already = [uid for uid, gid in card_map.items() if gid == game_id]

        print(f"\n  ── Game ID {game_id}: {label} ──")
        if already:
            print(f"  Currently enrolled ({len(already)} card(s)):")
            for uid in already:
                print(f"    • {uid}")
            answer = input("  Clear these and re-enrol from scratch? [y/N] ").strip().lower()
            if answer == "y":
                for uid in already:
                    del card_map[uid]
                already = []
            else:
                answer2 = input("  Add more cards to this action? [y/N] ").strip().lower()
                if answer2 != "y":
                    print(f"  Keeping existing {len(already)} card(s) for ID {game_id}.\n")
                    continue
                # fall through to the enrolment loop below

        # ── Enrolment loop — keep enrolling cards until the user says stop ──
        card_count = len(already)   # already enrolled so far this session
        while True:
            card_num = card_count + 1
            print(f"\n  Tap card #{card_num} for \"{label}\" on Reader 1...")
            print("  (waiting up to 15 seconds — lift the previous card first)")

            uid = read_one_card(enrol_reader, timeout=15.0)

            if uid is None:
                if card_count == 0:
                    print(f"  ⚠  Timed out — skipping Game ID {game_id}.")
                    print("     Re-run this script to enrol it later.\n")
                else:
                    print(f"  ⚠  Timed out — keeping the {card_count} card(s) already enrolled.\n")
                break

            # Warn if this UID is already mapped to a *different* game ID
            if uid in card_map and card_map[uid] != game_id:
                old_id = card_map[uid]
                print(f"  ⚠  UID {uid} is already enrolled as ID {old_id} ({GAME_IDS[old_id]}).")
                answer = input("  Reassign it to this action? [y/N] ").strip().lower()
                if answer != "y":
                    print("  Skipping this card.")
                    time.sleep(0.5)
                    continue

            if uid in card_map and card_map[uid] == game_id:
                print(f"  ⚠  This card is already enrolled for \"{label}\" — skipping duplicate.")
                time.sleep(0.5)
                continue

            card_map[uid] = game_id
            card_count += 1
            print(f"  ✓  Card #{card_count} enrolled: UID {uid}  →  Game ID {game_id} ({label})")

            # Brief pause so the user can lift the card before the next scan
            time.sleep(1.0)

            answer = input(f"  Enrol another card for \"{label}\"? [y/N] ").strip().lower()
            if answer != "y":
                print(f"  Done — {card_count} card(s) enrolled for \"{label}\".\n")
                break

    # Save
    CARD_MAP_PATH.write_text(json.dumps(card_map, indent=2))
    print("=" * 55)
    print(f"  Saved {len(card_map)} mapping(s) to {CARD_MAP_PATH.name}")
    print()
    for uid, gid in card_map.items():
        print(f"    {uid}  →  ID {gid} ({GAME_IDS.get(gid, '?')})")
    print("=" * 55)

    import RPi.GPIO as GPIO
    GPIO.cleanup()


if __name__ == "__main__":
    main()
