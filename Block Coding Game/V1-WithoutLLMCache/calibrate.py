"""
Calibration script for DEG_PER_SECOND.
Run this, measure the actual turn, enter it, and it prints the corrected value.
"""
import time
import requests
import misty

TARGET = 90.0   # degrees we want Misty to turn

def run():
    print(f"\nMisty Calibration — Turn Test")
    print(f"Target: {TARGET}°  |  Current DEG_PER_SECOND: {misty.DEG_PER_SECOND}")
    print("=" * 50)

    misty.disable_hazards()
    time.sleep(0.5)

    round_num = 1
    while True:
        input(f"\n[Round {round_num}] Press ENTER to make Misty turn {TARGET}° left...")
        misty.turn_left(TARGET)

        actual = input("  How many degrees did she actually turn? ").strip()
        try:
            actual_deg = float(actual)
        except ValueError:
            print("  Invalid number, try again.")
            continue

        if actual_deg <= 0:
            print("  Must be a positive number.")
            continue

        corrected = misty.DEG_PER_SECOND * (actual_deg / TARGET)
        print(f"\n  Actual: {actual_deg}°  →  new DEG_PER_SECOND = {corrected:.2f}")

        again = input("  Test again with corrected value? (y/n): ").strip().lower()
        if again == "y":
            misty.DEG_PER_SECOND = corrected
            print(f"  Updated to {corrected:.2f} for next round.")
            round_num += 1
        else:
            print(f"\n{'=' * 50}")
            print(f"  Final DEG_PER_SECOND = {corrected:.2f}")
            print(f"  Update this line in misty.py:")
            print(f"    DEG_PER_SECOND = {corrected:.2f}")
            print(f"{'=' * 50}\n")
            break

    misty.enable_hazards()

if __name__ == "__main__":
    run()
