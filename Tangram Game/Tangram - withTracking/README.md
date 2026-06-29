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
5. **Timer & point** — each board runs its own countdown (house 3 min, sword
   4 min). Misty announces the time at the start, reminds the child at each
   minute and again 20 seconds from the end, and awards **one point** if the
   whole shape is finished before the buzzer count runs out.

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

The game also ships with an **offline narration cache** of pre-generated
child-friendly dialogue (welcome lines, encouragement, hints, timer reminders,
…). It's optional: if `narration_cache.json` isn't present the game uses
hardcoded defaults. To (re)generate fresh wording, see
[Offline narration cache](#offline-narration-cache) below — this needs
[Ollama](https://ollama.com) but only at *generation* time, never during play.

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
| `--timer S` | per-shape | Countdown length. Omit to use the built-in per-shape timers (**house 3 min, sword 4 min**); `0` = no timer; any positive `S` forces that same length on every shape |
| `--final-warning S` | `20` | Seconds-left at which Misty gives her final "hurry" warning (the whole-minute reminders are automatic) |
| `--face-camera N` | `0` | Camera index for face tracking |
| `--no-face-track` | off | Disable Misty's head tracking |
| `--misty-face-camera` | off | Use Misty's own camera for face tracking |
| `--show-face-camera` | off | Show the face-tracking camera window |

---

## Notes for the study

### Timer
Each board now runs its own countdown, on by default: **3 minutes for the house,
4 minutes for the sword**. The clock starts *after* Misty finishes the welcome
intro, so the spoken setup doesn't eat into the child's time. During the round
Misty speaks the time aloud:

- **At the start** — "You have three minutes to build the house… ready, set, go!"
- **At every whole minute remaining** — e.g. the house gets a reminder at 2:00
  and 1:00 left; the sword at 3:00, 2:00, and 1:00 left.
- **A final warning 20 seconds before the end** — "Only 20 seconds left! Hurry!"
  (move this with `--final-warning S`).

Nothing is hard-stopped — at zero, Misty just announces time's up.

To override: `--timer 0` turns the timer off entirely, and `--timer 120` (or any
positive number) forces that same length on **both** boards, ignoring the
per-shape defaults.

### Scoring
A child earns **one point** for a board only if the full shape is confirmed
correct (all seven pieces green on a buzzer press) **before the timer runs out**.
If the clock reaches zero first, that round scores **no point** — and the result
is locked, so finishing late doesn't sneak one in. Either way Misty stays warm
("no point this round, but let's try again!") and the board resets for another
attempt or a board swap. The score is cumulative across rounds and Misty
announces the running total on each point. With the timer off (`--timer 0`),
completing the shape always earns the point.

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

### Offline narration cache

Every spoken line in the game — welcome, instructions, hints, encouragement
when pieces snap into place, "give it a little turn", timer reminders, time's
up, completion, goodbye — is drawn from `narration_cache.json` at runtime. The
cache stores **10 variations per key**, and the game does a single
`random.choice()` on every line, so a child rarely hears the exact same
sentence twice in one session.

**No LLM runs during gameplay.** Generation happens once, offline, with
`generate_narration_cache.py` calling a local Ollama model
(`gemma3:4b` by default). The robot just reads JSON.

#### Generate / refresh the cache

```bash
# First time, on a machine with Ollama (any time you want fresh wording):
ollama pull gemma3:4b
python3 generate_narration_cache.py            # 10 variations × 26 keys
```

The script saves to `narration_cache.json` next to itself. Copy that one file
to the robot machine and play normally — Ollama isn't needed there.

```bash
python3 generate_narration_cache.py --variations 5      # smaller cache
python3 generate_narration_cache.py --force             # regenerate everything
python3 generate_narration_cache.py --keys welcome,nudge,goodbye
python3 generate_narration_cache.py --model llama3.2:3b # try a different model
```

#### How it stays robust

| | |
|:--|:--|
| **Retries** | Exponential backoff (5 s → 10 s → 20 s) on HTTP 500, because Ollama returns 500 while warming the model on the first call. |
| **`<think>` stripping** | Reasoning models (e.g. `qwen3`) wrap output in `<think>…</think>`; the generator regex-strips these before saving. |
| **Placeholder validation** | Each key has required placeholders (`{name}`, `{score}`, `{label}`, etc.). Any variation that drops one is rejected and the model is asked again. |
| **Incremental save** | The JSON is written after each key, so a Ctrl-C mid-run keeps the work already done. |
| **Fallback chain** | At runtime: cache variation → hardcoded default for the key → generic line. The game never crashes on a missing or malformed entry. |
| **Backward compatible** | The loader accepts either a list of variations (current format) or a single string per key (legacy), so older cache files still work. |

#### When to regenerate

Re-run the generator whenever you:
- change one of the hardcoded defaults in `narration_prompts.py`,
- add or rename a key,
- want the children to hear noticeably different wording in a new study cycle.

### Per-press LLM rephrasing (separate, optional)

Distinct from the offline cache above, `--llm-feedback` keeps the original
*per-press* rephrasing path: after every buzzer press, the assembled feedback
sentences are rewritten into one or two warmer sentences by a local Ollama
model (default `qwen3:0.6b`; change `OLLAMA_MODEL` near the top). The script
calls `localhost:11434`; if Ollama is unreachable it silently falls back to
the cached/default phrasing. Leave it **off** for runs where you want every
child to hear identical wording.

These two features compose: with `--llm-feedback` on, each feedback round is
first composed from cache variations and then passed through Ollama for a
final per-press rewrite.

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
| `narration.py` | Runtime loader — reads `narration_cache.json` and serves one random variation per spoken line, with a default fallback |
| `narration_prompts.py` | Single source of truth: every dialogue key, its hardcoded default, and the placeholders it must preserve |
| `generate_narration_cache.py` | Offline script — calls local Ollama to (re)generate `narration_cache.json` |
| `narration_cache.json` | **Generated** by the script above; checked in or regenerated per study cycle |
| `requirements.txt` | Python dependencies |
| `house_targets.json` | **Generated** by calibration; the learned solved layout |
| `sword_targets.json` | **Generated** by calibration for the sword board |

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
- **Robot always says the same welcome / hints / encouragement** —
  `narration_cache.json` is missing or partial; the game has fallen back to
  hardcoded defaults. Run `python3 generate_narration_cache.py` (needs Ollama
  on that machine) and copy the resulting JSON to the robot's working
  directory. The game prints a one-line `[Narration] …` summary at startup
  saying how many variations it loaded.
- **Generator hangs on the first call / spits HTTP 500** — Ollama is still
  loading the model. The script retries with 5 s / 10 s / 20 s backoff; just
  let it run. If it keeps failing, confirm the model is pulled
  (`ollama list` should show `gemma3:4b` or whatever `--model` you passed).

---

*UNBC HRI study — 2026.*
