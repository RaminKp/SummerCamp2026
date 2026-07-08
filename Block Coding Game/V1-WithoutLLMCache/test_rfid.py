"""Raw RFID diagnostic — run with: python3 test_rfid.py
Shows what every reader sees every 0.3s. Press Ctrl+C to stop."""
import sys
import time
import json
from pathlib import Path

sys.path.insert(0, "/home/unbcroboticslab/Desktop/Sensors/RFID")
import rfid_reader
import RPi.GPIO as GPIO

CARD_MAP_PATH = Path(__file__).parent / "card_map.json"

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

print("Building readers...")
readers = rfid_reader.build_readers()
print(f"  {len(readers)} reader(s) ready.\n")

try:
    card_map = json.loads(CARD_MAP_PATH.read_text())
    print(f"card_map.json — {len(card_map)} entries: {list(card_map.keys())}\n")
except Exception as e:
    card_map = {}
    print(f"Could not load card_map.json: {e}\n")

print("Polling readers — place cards on them. Ctrl+C to stop.\n")

try:
    while True:
        row = []
        for name, reader in readers:
            uid = rfid_reader.scan_once(name, reader)
            if uid:
                game_id = card_map.get(uid, "UNKNOWN")
                row.append(f"{name}:{uid}(id={game_id})")
            else:
                row.append(f"{name}:empty")
        print("  " + "  |  ".join(row))
        time.sleep(0.3)
except KeyboardInterrupt:
    print("\nDone.")
finally:
    GPIO.cleanup()
