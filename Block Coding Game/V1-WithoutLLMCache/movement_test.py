import time
import requests

# ── Config ────────────────────────────────────────────────────────────────────

MISTY_IP       = "10.42.0.197"  # update if changed
BASE_URL       = f"http://{MISTY_IP}/api"

DRIVE_SPEED    = 45.0
TURN_SPEED     = 20.0
CM_PER_SECOND  = 22.0   # update after calibration
DEG_PER_SECOND = 15.0   # calibrated

# ── ✏️  EDIT HERE ─────────────────────────────────────────────────────────────

FORWARD_CM   = 35    # distance per leg
TURN_DEGREES = 90    # degrees per turn
LOOPS        = 1     # number of times to repeat


# ── Helpers ───────────────────────────────────────────────────────────────────

def _post(endpoint, payload):
    r = requests.post(f"{BASE_URL}/{endpoint}", json=payload, timeout=10)
    r.raise_for_status()
    return r

def _cm_to_ms(cm):
    return int((cm / CM_PER_SECOND) * 1000)

def _deg_to_ms(degrees):
    return int((degrees / DEG_PER_SECOND) * 1000)

def forward(cm):
    ms = _cm_to_ms(cm)
    print(f"    → forward {cm}cm ({ms}ms)")
    _post("drive/time", {"LinearVelocity": DRIVE_SPEED, "AngularVelocity": 0, "TimeMs": ms})
    time.sleep(ms / 1000 + 0.3)

def back(cm):
    ms = _cm_to_ms(cm)
    print(f"    → back {cm}cm ({ms}ms)")
    _post("drive/time", {"LinearVelocity": -DRIVE_SPEED, "AngularVelocity": 0, "TimeMs": ms})
    time.sleep(ms / 1000 + 0.3)

def turn_left(degrees):
    ms = _deg_to_ms(degrees)
    print(f"    → turn left {degrees}° ({ms}ms)")
    _post("drive/time", {"LinearVelocity": 0, "AngularVelocity": TURN_SPEED, "TimeMs": ms})
    time.sleep(ms / 1000 + 0.3)

def turn_right(degrees):
    ms = _deg_to_ms(degrees)
    print(f"    → turn right {degrees}° ({ms}ms)")
    _post("drive/time", {"LinearVelocity": 0, "AngularVelocity": -TURN_SPEED, "TimeMs": ms})
    time.sleep(ms / 1000 + 0.3)

def stop():
    _post("drive/stop", {})
    print("    → stop")

def disable_hazards():
    _post("hazard/updatebasesettings", {
        "RevertToDefault": False,
        "DisableTimeOfFlights": True,
        "DisableBumpSensors": True
    })

def enable_hazards():
    _post("hazard/updatebasesettings", {"RevertToDefault": True})


# ── Sequences ─────────────────────────────────────────────────────────────────

def run_forward_sequence():
    """
    One loop leg:
    forward → turn left → forward → turn right → forward
    """
    forward(FORWARD_CM)
    turn_left(TURN_DEGREES)
    forward(FORWARD_CM)
    turn_right(TURN_DEGREES)
    forward(FORWARD_CM)

def run_reverse_sequence():
    """
    Exact reverse — undoes run_forward_sequence step by step.
    back → turn left → back → turn right → back
    """
    back(FORWARD_CM)
    turn_left(TURN_DEGREES)   # reverses the turn_right
    back(FORWARD_CM)
    turn_right(TURN_DEGREES)  # reverses the turn_left
    back(FORWARD_CM)


# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    print("Disabling hazards...")
    disable_hazards()
    time.sleep(0.5)

    # ── Forward pass ──────────────────────────────────────────────────────────
    print(f"\n=== Forward pass ({LOOPS} loops) ===")
    for i in range(1, LOOPS + 1):
        print(f"\n  Loop {i} of {LOOPS}:")
        run_forward_sequence()

    stop()
    print("\nReached finish line. Pausing...")
    time.sleep(1)

    # ── Reverse pass ──────────────────────────────────────────────────────────
    print(f"\n=== Reverse pass ({LOOPS} loops) ===")
    for i in range(1, LOOPS + 1):
        print(f"\n  Loop {i} of {LOOPS}:")
        run_reverse_sequence()

    stop()
    print("\nBack at start. Done!")
    enable_hazards()


if __name__ == "__main__":
    run()