# Misty II Head Tracking for Two-Player HRI Studies

Onboard face-detection-based head tracking for Misty II. Uses Misty's built-in `FaceRecognition` event to keep the robot's gaze on children during a two-player game, alternating between the leftmost and rightmost detected faces every 4–5 seconds.

Prepared for the NORTHERN-STARS HRI summer camp study (UNBC, 2026).

---

## What it does

- Runs face detection **entirely onboard Misty** — no laptop-side computer vision, no MediaPipe, no camera stream pulling.
- Subscribes to the `FaceRecognition` WebSocket event, which already provides per-face bearing and elevation in degrees.
- Sorts visible faces by horizontal position each control cycle. Leftmost face = "Player A", rightmost = "Player B".
- Switches gaze between the two sides every 4.0–5.0 seconds (uniformly randomized to avoid mechanical-feeling periodicity).
- Smoothly tracks the current target between switches, so the head gently follows small movements rather than freezing.
- If only one face is visible: looks at that one.
- If no faces are visible: holds position.

## Why on-robot detection

Misty's `FaceRecognition` event reports `Bearing` and `Elevation` already converted to degrees relative to the camera's optical axis. This eliminates the FOV calibration, pixel-to-angle math, and external CV pipeline you'd otherwise need (e.g., MediaPipe-based approaches like the QT setup). The trade-off: it is a frontal-face detector, so faces in sharp profile may not register. For seated children at 1–3 m playing a tabletop game, this is rarely an issue.

---

## Requirements

- Misty II (Standard or Enhanced Edition).
- Python 3.8+.
- `mistyPy` library:
  ```
  pip install mistyPy
  ```
- A network where your computer and Misty are on the same subnet.

## Setup

1. Find Misty's IP address (use the Misty app, the Command Center, or your router's device list).
2. Open `misty_head_tracking.py` and set:
   ```python
   MISTY_IP = "10.42.0.197"
   ```
3. Run:
   ```
   python misty_head_tracking.py
   ```
4. Press `Ctrl-C` to stop. The script cleans up: stops face detection, unregisters events, and returns the head to neutral.

---

## First-run calibration (30 seconds)

The single most common first-run issue is a sign convention mismatch — Misty looks *away* from the child instead of *toward* them. Fix:

1. Stand in front of Misty and slowly step to **her right**.
2. If her head follows you to her right: signs are correct, you're done.
3. If her head turns to her left (away from you): flip `BEARING_SIGN` in the config block from `+1` to `-1`.
4. Repeat the same test vertically (have someone tall stand close, then have them crouch). If she tracks the wrong way: flip `ELEVATION_SIGN`.

These flags are at the top of the config section precisely because they're the thing most likely to need adjustment.

---

## Configuration reference

All knobs live at the top of `misty_head_tracking.py`.

### Connection

| Setting | Default | Description |
|---|---|---|
| `MISTY_IP` | `"192.168.0.100"` | Misty's IP on your local network. |

### Gaze behavior

| Setting | Default | Description |
|---|---|---|
| `SWITCH_INTERVAL_MIN` | `4.0` s | Minimum time before switching gaze between the two players. |
| `SWITCH_INTERVAL_MAX` | `5.0` s | Maximum time before switching. Each switch picks a fresh value in this range. |
| `FACE_FRESHNESS_SECONDS` | `1.5` s | How long a face detection stays "live" before being dropped. Increase if Misty drifts away during brief profile turns. |
| `SMOOTHING_ALPHA` | `0.5` | Blend factor toward the target (0–1). Lower = smoother but laggier. Higher = snappier but jerkier. |
| `HEAD_VELOCITY` | `45` | Head motor speed (%). Lower feels more natural for child-facing HRI. |
| `CONTROL_HZ` | `10` | Control loop rate. Rarely needs changing. |

### Sign conventions (calibration flags)

| Setting | Default | Description |
|---|---|---|
| `BEARING_SIGN` | `+1` | Flip to `-1` if Misty turns away from faces horizontally. |
| `ELEVATION_SIGN` | `-1` | Flip if Misty tilts the wrong way vertically. |

### Hardware safety limits

| Setting | Default | Description |
|---|---|---|
| `YAW_MIN`, `YAW_MAX` | `-75`, `75` | Conservative head-yaw bounds (degrees). Misty's hardware allows ±81. |
| `PITCH_MIN`, `PITCH_MAX` | `-35`, `22` | Pitch bounds. Negative = up, positive = down. |

---

## Tuning for the study environment

Common observations from sessions and the corresponding adjustments:

| Symptom | Adjustment |
|---|---|
| Head motion feels jerky / mechanical | Lower `SMOOTHING_ALPHA` to 0.3; lower `HEAD_VELOCITY` to 30. |
| Head feels too slow to follow a moving child | Raise `SMOOTHING_ALPHA` to 0.7. |
| Misty drifts back to neutral every time a kid turns their head | Raise `FACE_FRESHNESS_SECONDS` to 2.5–3.0. |
| Switching feels too regular / predictable | Widen the switch interval (e.g. 3.5 to 5.5 s). |
| Misty can't reach a child seated low at a table | Raise `PITCH_MAX` toward 25 (the hardware ceiling is ~26). |

---

## How the gaze-switching logic works

A subtle design decision worth knowing for the study writeup: the code tracks **side** ("left" vs "right"), not Misty's TrackId.

Misty's TrackId is assigned per detection and can change when a face briefly leaves view (a kid turning to look at the game board, blinking, leaning back). If the gaze controller locked onto TrackIds, every such momentary dropout would trigger a spurious "switch" event.

Instead, on each control cycle the controller:
1. Pulls the current set of fresh face detections (within `FACE_FRESHNESS_SECONDS`).
2. Sorts them by yaw (most-left to most-right).
3. Looks at whichever face is on the currently-selected side.
4. Switches sides on the configured timer.

This makes the behavior robust to fidgeting and brief profile-turns without any per-face identity tracking.

---

## Known limitations

- **Frontal faces only.** Misty's onboard detector loses faces in strong profile. For seated tabletop play this is rare; for active full-body play it may matter.
- **Lighting.** Strong backlight (e.g. children sitting in front of a bright window) degrades detection. Worth scouting each session location.
- **One player visible, then both, then one again.** When a face appears or disappears, the "left" and "right" designations are re-derived from the current set. Briefly, Misty may look at the lone visible child even mid-cycle. This is intentional (matches the "only one face → look at that one" spec) but may produce a slightly faster-than-expected switch when the second child reappears.
- **TrackId reset.** Misty re-assigns TrackIds when faces drop out and re-detect. Side-based tracking (above) means this doesn't matter for gaze control, but it does mean per-face identity-level logging is not available without enrolling faces first.

---

## File layout

```
misty_head_tracking.py    # the runnable script
README.md                 # this file
```

The script is self-contained — no module structure to set up, no config files.

---

## License / attribution

Internal research code for the NORTHERN-STARS project at UNBC. Cite as appropriate in study writeups; flag any reuse outside the project to the supervisor.
