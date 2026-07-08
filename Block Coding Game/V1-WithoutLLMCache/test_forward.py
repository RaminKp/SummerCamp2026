"""
test_forward.py — Measure how far Misty actually travels for a given forward command.

Place Misty at a marked starting point, run this script, then measure the
distance from start to where she stops. Adjust CM_PER_SECOND in misty.py
until the measured distance matches the commanded distance.

Usage:
    python3 test_forward.py            # drives 30cm (one grid step)
    python3 test_forward.py 60         # drives 60cm (two grid steps)
"""

import sys
import time
import misty

COMMANDED_CM = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0

print("=" * 50)
print("  MISTY FORWARD DISTANCE TEST")
print("=" * 50)
print(f"\n  Commanded distance : {COMMANDED_CM} cm")
print(f"  Drive speed        : {misty.DRIVE_SPEED}")
print(f"  CM_PER_SECOND      : {misty.CM_PER_SECOND}")
ms = int((COMMANDED_CM / misty.CM_PER_SECOND) * 1000)
print(f"  Calculated TimeMs  : {ms} ms")
print()
print("  Mark Misty's starting position, then press ENTER to drive.")
input("  > ")

misty.disable_hazards()
misty.forward(COMMANDED_CM)
misty.stop()

print()
print("  Misty has stopped.")
print("  Measure the distance from the start mark to her current position.")
measured = input("  Measured distance (cm): ").strip()

try:
    measured_cm = float(measured)
    ratio = measured_cm / COMMANDED_CM
    corrected = misty.CM_PER_SECOND * ratio
    print()
    print(f"  Commanded : {COMMANDED_CM:.1f} cm")
    print(f"  Measured  : {measured_cm:.1f} cm")
    print(f"  Error     : {measured_cm - COMMANDED_CM:+.1f} cm  ({(ratio - 1) * 100:+.1f}%)")
    print()
    if abs(ratio - 1.0) < 0.02:
        print("  CM_PER_SECOND is accurate — no change needed.")
    else:
        print(f"  Suggested CM_PER_SECOND: {corrected:.2f}  (currently {misty.CM_PER_SECOND})")
        print(f"  Update misty.py line:  CM_PER_SECOND = {corrected:.2f}")
except ValueError:
    print("  Could not parse measurement — no suggestion calculated.")

misty.enable_hazards()
