# 🤖 Misty Maze Game

A card-sequencing navigation game where children use RFID cards to program Misty's route through a maze.

---

## Hardware Required

| Component | Details |
|---|---|
| Misty II robot | Fully charged, WiFi hotspot active |
| Raspberry Pi | Running this codebase, connected to Misty's hotspot |
| 6× MFRC522 RFID readers | Wired to the Pi via SPI (see wiring map PDF) |
| RFID cards/tokens | At least 3 types enrolled: Forward, Left, Right |
| Keyboard | For ENTER-to-submit during play |

---

## Pre-Game Setup

### Step 1 — Start Misty's Hotspot

1. Power on Misty by pressing the button on her base.
2. Wait ~60 seconds for her to fully boot (she'll play a startup sound).
3. On the Raspberry Pi, open WiFi settings and connect to **Misty's hotspot** network.
4. Confirm the Pi is connected before proceeding.

> **Note:** Misty's IP address is hardcoded in `misty.py` as `10.42.0.197`. If her IP ever changes (e.g. after a reset), update `MISTY_IP` at the top of that file.

---

### Step 2 — Verify Connection to Misty

Run the connection test to confirm the Pi can reach Misty and all systems are working:

```bash
cd /home/unbcroboticslab/Desktop/blossom_game
python misty.py
```

You should see:
```
Connected!  Battery: 87%
Testing LED...
LED OK.
Testing speech...
All tests passed.
```

If it fails with a `ConnectionError`, check the WiFi connection and IP address.

---

### Step 3 — Place Misty at the Start of the Map

- Position Misty at the **designated start tile**, facing the **correct starting direction** for the active map.
- The start position must be consistent each run — Misty has no GPS and navigates purely by timed drive commands.
- Double-check she has **clear space** in front of her for the first move.

---

### Step 4 — Enrol RFID Cards *(first time only)*

If this is the first time running, or you have new cards, enrol them:

```bash
python enrol_cards.py
```

Follow the on-screen prompts — tap each card type onto **Reader 1** when asked. You can enrol **multiple physical cards per action** (e.g. several "Forward" cards so the player has enough for longer sequences).

The mapping is saved to `card_map.json` and loaded automatically each game.

---

### Step 5 — Select the Active Map *(optional)*

Open `maps.py` and set `ACTIVE_MAP_ID` near the bottom of the file:

```python
ACTIVE_MAP_ID = 1   # change to 2, 3, etc. for different maps
```

Available maps are listed at the top of the `MAPS` dictionary in the same file.

---

### Step 6 — Make Sure Ollama is Running *(for narration)*

The game uses a local LLM (Ollama + Llama 3.2) to generate Misty's speech. Start it if it isn't running:

```bash
ollama serve
```

If Ollama is unavailable, the game falls back to pre-written static messages automatically — the game will still work.

---

## Running the Game

```bash
cd /home/unbcroboticslab/Desktop/blossom_game
python main.py
```

The game will:
1. Load the active map and print its phases
2. Generate narration for all checkpoints (~30 seconds)
3. Misty's LED turns **blue** and she announces the game
4. For each phase, she gives a hint and waits for the player

---

## How to Play

Each phase, the player must arrange RFID cards on the readers to match the correct sequence:

| Reader | Role |
|---|---|
| Reader 1 | Step 1 of the sequence |
| Reader 2 | Step 2 of the sequence |
| Reader 3 | Step 3 … and so on |

**Card types:**

| Card | Action |
|---|---|
| Forward card | Move forward one segment |
| Left card | Turn left 90° |
| Right card | Turn right 90° |

1. Tap cards onto the correct readers in order (Reader 1 first, then 2, 3…).
2. Press **ENTER** in the terminal to submit the sequence.
3. Misty validates and responds:
   - ✅ **Correct** — LED goes green, Misty drives the route
   - 🔴 **Wrong order** — right cards, wrong sequence; try rearranging
   - 🔴 **Wrong cards** — incorrect card types; try different ones
4. After a successful run, Misty returns home and the next phase begins.

> **To abort the game:** Press ENTER with **no cards** placed on any reader.

---

## Folder Structure

```
blossom_game/
├── main.py          # Game loop — run this to play
├── detector.py      # RFID reader interface (6 readers, Enter to submit)
├── validator.py     # Checks scanned sequence against expected sequence
├── maps.py          # Map and checkpoint definitions — edit routes here
├── misty.py         # Misty API wrappers (drive, LED, speech)
├── narrator.py      # Ollama LLM narration generator
├── enrol_cards.py   # One-time card enrolment tool
└── card_map.json    # Auto-generated UID → game action mapping

Sensors/RFID/
├── rfid_reader.py           # Shared RFID hardware module
├── rfid_test.py             # Standalone reader test
├── RFID_RPi_Setup_Guide.pdf # Hardware wiring guide
└── Six_Reader_RC522_Wiring_Map.pdf
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `ConnectionError` reaching Misty | Check WiFi — Pi must be on Misty's hotspot. Confirm IP in `misty.py`. |
| `FileNotFoundError: card_map.json` | Run `python enrol_cards.py` to enrol cards first. |
| Reader not detecting cards | Run `python Sensors/RFID/rfid_test.py` to test readers individually. |
| Card UID not recognised (game ID = 0) | Card not enrolled — re-run `enrol_cards.py` and tap that card. |
| Narration not generating | Start Ollama with `ollama serve`. Game will fall back to static lines. |
| Misty doesn't drive straight | Adjust `CM_PER_SECOND` in `misty.py` and re-run calibration. |
