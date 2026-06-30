"""
Excel game logging via openpyxl, for research-study tracking.

Writes three sheets in one workbook (created on first run, appended to after):

  Sessions      — one row per full game played (start/end, duration, outcome)
  Attempts      — one row per RFID scan submission at a checkpoint
  PlayerSummary — one row per playthrough, rolling up that playthrough's
                  Sessions + Attempts rows into a single flat view

IMPORTANT: PlayerID identifies a single *playthrough*, not a person. If the
same kid (e.g. "Alex") plays twice, each play gets its own new PlayerID —
the two runs are never merged. This is deliberate: the study needs to be
able to look at two plays by the same name as independent data points,
since a player may behave differently each time. The "Player Name" field
is free-text and purely for human-readability; it plays no role in lookup
or identity.
"""

from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook

LOG_PATH = Path(__file__).parent / "game_log.xlsx"

SESSIONS_HEADER = [
    "PlayerID", "Player Name", "Date", "Map", "Start Time", "End Time",
    "Duration (s)", "Outcome",
]

ATTEMPTS_HEADER = [
    "PlayerID", "Player Name", "Date", "Map", "Checkpoint", "Attempt #",
    "Scanned RFIDs", "Expected RFIDs", "Result", "Correct?",
    "Start Time", "End Time", "Duration (s)",
]

SUMMARY_HEADER = [
    "PlayerID", "Player Name", "Date", "Map", "Outcome",
    "Total Attempts", "Correct Attempts", "Incorrect Attempts",
    "Accuracy (%)", "Game Duration (s)",
]


def _ensure_workbook() -> Workbook:
    if LOG_PATH.exists():
        wb = load_workbook(LOG_PATH)
    else:
        wb = Workbook()
        wb.remove(wb.active)

    if "Sessions" not in wb.sheetnames:
        wb.create_sheet("Sessions").append(SESSIONS_HEADER)
    if "Attempts" not in wb.sheetnames:
        wb.create_sheet("Attempts").append(ATTEMPTS_HEADER)
    if "PlayerSummary" not in wb.sheetnames:
        wb.create_sheet("PlayerSummary").append(SUMMARY_HEADER)

    return wb


def _next_player_id(wb: Workbook) -> int:
    """One new ID per playthrough — PlayerSummary row count is the source of truth."""
    return wb["PlayerSummary"].max_row  # header is row 1, so first player gets ID 1


class GameLogger:
    """One instance per game session; call start(), log_attempt(), end()."""

    def __init__(self, player_name: str, map_name: str):
        self.player_name = player_name
        self.map_name = map_name
        self.player_id: int | None = None
        self._session_start: datetime | None = None
        self._checkpoint_start: datetime | None = None
        self._attempt_rows: list[dict] = []

    # ── session-level ──────────────────────────────────────────────────────

    def start(self):
        self._session_start = datetime.now()
        wb = _ensure_workbook()
        self.player_id = _next_player_id(wb)
        wb.save(LOG_PATH)

    def end(self, outcome: str):
        end_time = datetime.now()
        start = self._session_start or end_time
        duration = round((end_time - start).total_seconds(), 1)

        wb = _ensure_workbook()
        wb["Sessions"].append([
            self.player_id,
            self.player_name,
            start.strftime("%Y-%m-%d"),
            self.map_name,
            start.strftime("%H:%M:%S"),
            end_time.strftime("%H:%M:%S"),
            duration,
            outcome,
        ])

        total = len(self._attempt_rows)
        correct = sum(1 for a in self._attempt_rows if a["correct"])
        accuracy = round(100 * correct / total, 1) if total else 0.0

        wb["PlayerSummary"].append([
            self.player_id,
            self.player_name,
            start.strftime("%Y-%m-%d"),
            self.map_name,
            outcome,
            total,
            correct,
            total - correct,
            accuracy,
            duration,
        ])

        wb.save(LOG_PATH)

    # ── per-checkpoint-attempt level ──────────────────────────────────────

    def begin_checkpoint_attempt(self):
        self._checkpoint_start = datetime.now()

    def log_attempt(self, checkpoint_label: str, attempt_num: int,
                     scanned: list[int], expected: list[int], result: str):
        end_time = datetime.now()
        start = self._checkpoint_start or end_time
        duration = round((end_time - start).total_seconds(), 1)
        correct = (result == "CORRECT")

        self._attempt_rows.append({"correct": correct})

        wb = _ensure_workbook()
        wb["Attempts"].append([
            self.player_id,
            self.player_name,
            start.strftime("%Y-%m-%d"),
            self.map_name,
            checkpoint_label,
            attempt_num,
            str(scanned),
            str(expected),
            result,
            "Yes" if correct else "No",
            start.strftime("%H:%M:%S"),
            end_time.strftime("%H:%M:%S"),
            duration,
        ])
        wb.save(LOG_PATH)
