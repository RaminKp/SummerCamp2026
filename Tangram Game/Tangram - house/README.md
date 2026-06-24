# Tangram Quest — House board (Misty II edition)

An interactive tangram game for the **UNBC Human–Robot Interaction children's
study**. A child assembles a 7-piece tangram **house** under an overhead camera;
when they press a **buzzer**, the Misty II robot looks at the whole board and
gives one batch of warm, spoken feedback — which pieces are right, which are in
the right place but need a turn, and which are in the wrong spot.

This is the airplane/house game logic re-wired for the **physical assets you
actually printed**: the house board with corner markers **1–4** and the seven
wooden pieces carrying ArUco markers **20–26**.

---

## The physical set

All markers are **ArUco `DICT_4X4_50`**.

**House board** — four corner markers:

| Marker | Corner |
|:------:|:-------|
| 1 | top-left |
| 2 | top-right |
| 3 | bottom-right |
| 4 | bottom-left |

**Pieces** — one marker stuck centred on each:

| ID | Piece | Colour | Rotation symmetry |
|:--:|:------|:-------|:-----------------:|
| 20 | square | light blue | 90° |
| 21 | large triangle | dark blue | none |
| 22 | small triangle | purple | none |
| 23 | small triangle | green | none |
| 24 | medium triangle | orange | none |
| 25 | large triangle | yellow | none |
| 26 | parallelogram | red | 180° |

**Interchangeable pairs** (either piece may fill either slot):
the two **large** triangles (21 ↔ 25) and the two **small** triangles (22 ↔ 23).

---

## How it works

1. **Perception** — OpenCV detects every ArUco marker each frame.
2. **Board frame** — the four corner markers define a homography, so piece
   positions are measured in a stable *board* coordinate system even if the
   camera is bumped (needs ≥3 of the 4 corners visible). The board frame and the
   on-screen house outline are taken directly from your printed board PDF
   (walls ≈ 11.88 cm wide, roof slopes 6 cm and 8.4 cm, chimney = the 4.2 cm
   square).
3. **Targets via calibration** — instead of hard-coding where each piece should
   land (which depends on your exact print, camera mount, and how each sticker
   sits on each piece), the game **learns** the solved layout once and saves it
   to `house_targets.json`.
4. **Buzzer feedback** — on a press, every piece is scored as **correct**,
   **right-spot-needs-a-turn**, **wrong-spot**, or **missing**, and Misty speaks
   a short, encouraging summary with a matching face, LED colour, and gesture.

A child-facing window shows the house outline plus a row of seven chips that
fill with a checkmark as pieces are confirmed. The camera feed is **not** shown
to the child (debug overlay is opt-in).

---

## Install

```bash
pip install -r requirements.txt
```

> **Important:** the game uses `cv2.aruco`, which ships only in the **contrib**
> build of OpenCV. If plain `opencv-python` is already installed, remove it
> first (`pip uninstall opencv-python`) — the two packages conflict.

Python 3.8+ recommended.

---

## First run — calibrate once (~30 seconds)

```bash
python3 tangram_house_misty.py --no-robot --camera 1 --calibrate
```

1. Place the board under the camera so **all four corners** are visible.
2. **Solve the house correctly**, then press **`C`** to capture.
3. **Swap the two large triangles _and_ the two small triangles**, then press
   **`C`** again. *(This second capture lets the game check rotation exactly for
   either triangle in either slot. If you skip it, swapped triangles are still
   accepted — but on position only.)*
4. Press **`S`** to save. This writes `house_targets.json`, which loads
   automatically on every later run.

Press **`Q`** to abort calibration without saving.

Re-calibrate any time during play with **`K`**, or force it at startup with
`--calibrate`.

---

## Play

```bash
# With a real Misty II
python3 tangram_house_misty.py --misty-ip 192.168.1.50 --camera 1

# Vision + buzzer only (prints what Misty would say/do)
python3 tangram_house_misty.py --no-robot --camera 1

# Same, with the ArUco debug overlay so you can confirm detection
python3 tangram_house_misty.py --no-robot --camera 1 --show-camera
```

### Controls

| Key | Action |
|:---:|:-------|
| **SPACE** | Buzzer — check the whole board |
| **H** | Hint about the next piece to fix |
| **K** | Re-calibrate |
| **Q** | Quit |

> Click the game window first so it has keyboard focus.

---

## Command-line options

| Flag | Default | Purpose |
|:-----|:--------|:--------|
| `--misty-ip IP` | — | Misty II address (or use `--no-robot`) |
| `--no-robot` | off | Run without a robot (vision + buzzer test) |
| `--camera N` | `1` | Puzzle (overhead) camera index |
| `--calibrate` | off | Force calibration even if targets exist |
| `--show-camera` | off | Show the ArUco debug overlay window |
| `--touch-buzzer` | off | Also accept a tap on Misty's head as the buzzer (needs the SDK) |
| `--llm-feedback` | off | Rephrase feedback through a local Ollama model |
| `--timer S` | `0` (off) | Countdown seconds; `0` = no timer |
| `--timer-warning S` | `60` | Seconds-left at which Misty gives the "one minute" warning |
| `--face-camera N` | `0` | Camera index for face tracking |
| `--no-face-track` | off | Disable Misty's head tracking |
| `--misty-face-camera` | off | Use Misty's own camera for face tracking |
| `--show-face-camera` | off | Show the face-tracking camera window |

---

## Notes for the study

### Timer
This house board is the **Level 1, ages 9–12** card, so the timer is **off by
default**. It's fully built in for the younger groups — add `--timer 120` (and
optionally `--timer-warning 60`) and Misty will count down, warn at one minute,
and announce time's up without hard-stopping the child.

### Physical GPIO buzzer
The child presses a real button, not the keyboard. A clean hook is already in
place: `MistyAgent` (and `DummyAgent`) expose a `threading.Event` at
`qt._buzzer` and a `poll_buzzer()` the main loop checks every frame. From a
`gpiozero` callback, just set the event:

```python
from gpiozero import Button
button = Button(17)              # your GPIO pin
button.when_pressed = lambda: qt._buzzer.set()
```

A physical press then behaves exactly like SPACE. (Wire this in `main()` after
the agent `qt` is created.)

### Local LLM rephrasing (optional)
With `--llm-feedback`, each batch of feedback is rephrased into one or two
warmer sentences by a local [Ollama](https://ollama.com) model — default
`qwen3:0.6b` (change `OLLAMA_MODEL` near the top). The script calls
`localhost:11434`; if Ollama is unreachable it silently falls back to the
built-in deterministic phrasing. Leave it **off** for runs where you want every
child to hear identical wording.

### Misty connection
The robot is driven over plain **REST** by default (no `mistyPy` install
needed). To use the SDK instead — required only for the head-tap buzzer
(`--touch-buzzer`) — set `USE_MISTY_SDK = True` at the top and
`pip install mistyPy`. Misty's voice, pitch, and speech rate are constants near
the top of the file.

### Tuning acceptance
Two constants near the top control how forgiving the check is (relaxed for
children by default):

```python
POSITION_TOLERANCE_PX  = 250   # ~3.2 cm in board space (78.74 px/cm)
ROTATION_TOLERANCE_DEG = 22
```

Lower them for stricter placement, raise them to be more forgiving.

---

## Files

| File | Role |
|:-----|:-----|
| `tangram_house_misty.py` | The game |
| `requirements.txt` | Python dependencies |
| `house_targets.json` | **Generated** by calibration; the learned solved layout |

---

## Troubleshooting

- **"Board: NOT FOUND" / outline stays grey** — fewer than 3 corner markers are
  visible. Reposition the camera so all four show; run with `--show-camera` to
  watch detection live.
- **Pieces don't go green even when placed correctly** — the targets are off.
  Re-calibrate (`K`), and do the swap (second) capture. Confirm the board print
  is at 100% / actual size (check the ruler on the PDF).
- **Small markers (1.2 cm purple/green) flicker or miss** — make sure the camera
  is at MJPG 1080p (the script forces this) and the lighting is even; raise the
  camera a little or improve contrast.
- **`module 'cv2' has no attribute 'aruco'`** — you have plain `opencv-python`.
  Uninstall it and install `opencv-contrib-python`.
- **Misty silent / unreachable** — confirm the robot is powered on, on the same
  network, and `ping <misty-ip>` works.

---

*UNBC HRI study — 2026.*
