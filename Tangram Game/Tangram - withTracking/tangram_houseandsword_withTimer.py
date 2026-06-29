#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tangram Quest - MULTI-SHAPE (house + sword)  -  MISTY II edition
===============================================================

ArUco perception, board homography, batch buzzer feedback, Misty interface and
head tracking, wired for the PHYSICAL assets you printed. The game knows which
puzzle is on the table from a SHAPE marker on the board, so you just drop a
board under the camera and it plays that shape:

    * Boards ............. corner ArUco markers 1,2,3,4  (DICT_4X4_50)
                           (ID1=top-left, ID2=top-right,
                            ID3=bottom-right, ID4=bottom-left)
                           plus ONE shape marker per board:
                              10 = house  (portrait board)
                              11 = sword  (landscape board)
    * 7 tangram pieces ... ArUco markers 20-26 stuck on each piece:
            20  light-blue SQUARE      24  orange     MEDIUM triangle
            21  dark-blue  LARGE tri   25  yellow     LARGE triangle
            22  purple     SMALL tri   26  red        PARALLELOGRAM
            23  green      SMALL tri

The same 7 pieces build every shape; only the board (outline + targets) changes.
Marker ID ranges: 1-4 corners, 10-19 shapes, 20-26 pieces.

Game rules baked in (from your spec):
    * Children place pieces in any order, then press the BUZZER (SPACE for now).
      Misty looks at the whole board and gives ONE batch of feedback: which are
      correct, which are in the right place but need a turn, which are misplaced.
    * Interchangeable pieces: the two LARGE triangles (21/25) can swap slots, and
      the two SMALL triangles (22/23) can swap slots.
    * Optional countdown timer with a "one minute left" warning (default OFF for
      ages 9-12; turn on with --timer 120 for the younger 6-8 levels).

WHY CALIBRATION (important)
---------------------------
Where each piece's marker lands depends on YOUR print, camera mount, and exactly
how each sticker sits on each piece - so the game LEARNS each shape's layout once
and saves it per shape (house_targets.json, sword_targets.json). To calibrate a
shape: show its board, assemble it correctly, press C; then swap the two large
triangles AND the two small triangles, press C again (for rotation), then S.

Run
---
    # Real Misty - auto-detects whichever board you put down
    python3 tangram_house_misty.py --misty-ip 192.168.1.50 --camera 1

    # No robot (vision + buzzer test)
    python3 tangram_house_misty.py --no-robot --camera 1 --show-camera

    # Force one puzzle / (re)calibrate it
    python3 tangram_house_misty.py --no-robot --camera 1 --shape sword --calibrate

SPACE = buzzer/check    H = hint    K = (re)calibrate    Q = quit

"""

import argparse
import json
import math
import os
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

import cv2
import cv2.aruco as aruco
import numpy as np

try:
    import requests
except ImportError:
    requests = None  # only needed when actually talking to Misty


# ============================================================
#  GLOBAL TOGGLES
# ============================================================

USE_MISTY_SDK       = False   # False = raw REST (no mistyPy install needed)
LOCK_CORRECT_PIECES = True    # once a piece is correct it stays correct
MAX_FACTS_PER_TURN  = 3       # cap educational facts spoken per buzzer press
MISTY_VOLUME        = 90      # startup speaker volume

# ── Voice (Android TTS voice installed on the robot) ─────────────────────────
MISTY_VOICE       = "en-us-x-sfg-local"
MISTY_PITCH       = 1.0
MISTY_SPEECH_RATE = 0.9       # <1 = slower (clearer for kids)

# Optional local LLM rephrasing (only used with --llm-feedback).
OLLAMA_MODEL = "qwen3:0.6b"   # your chosen small model; any Ollama tag works

TARGETS_FILE = "house_targets.json"


# ============================================================
#  PIECE + BOARD CONFIG  (your physical markers)
# ============================================================
# rot_sym: rotational symmetry of the SHAPE in degrees. 360 = no symmetry
# (a triangle must match its captured angle); 90 = square; 180 = parallelogram.
PIECES: Dict[int, dict] = {
    20: {"name": "square",          "label": "light blue square",
         "shape": "square",         "color_bgr": (235, 170, 70),  "rot_sym": 90,
         "fact": "A square has four equal sides and four square corners!"},
    21: {"name": "large triangle",  "label": "dark blue triangle",
         "shape": "triangle",       "color_bgr": (150, 70, 20),   "rot_sym": 360,
         "fact": "This is one of the two biggest triangles in the puzzle!"},
    22: {"name": "small triangle",  "label": "purple triangle",
         "shape": "triangle",       "color_bgr": (170, 70, 150),  "rot_sym": 360,
         "fact": "Two small triangles can join together to make a square!"},
    23: {"name": "small triangle",  "label": "green triangle",
         "shape": "triangle",       "color_bgr": (70, 175, 80),   "rot_sym": 360,
         "fact": "A triangle has three sides and three pointy corners!"},
    24: {"name": "medium triangle", "label": "orange triangle",
         "shape": "triangle",       "color_bgr": (30, 140, 240),  "rot_sym": 360,
         "fact": "The medium triangle is bigger than the small ones!"},
    25: {"name": "large triangle",  "label": "yellow triangle",
         "shape": "triangle",       "color_bgr": (40, 210, 235),  "rot_sym": 360,
         "fact": "The two large triangles cover half of the whole shape!"},
    26: {"name": "parallelogram",   "label": "red parallelogram",
         "shape": "parallelogram",  "color_bgr": (50, 50, 210),   "rot_sym": 180,
         "fact": "A parallelogram has two pairs of parallel sides!"},
}
ALL_PIECE_IDS = list(PIECES.keys())

# Pieces that may legally swap slots with each other.
INTERCHANGEABLE_GROUPS: List[List[int]] = [[21, 25], [22, 23]]

def _group_of(pid: int) -> List[int]:
    for g in INTERCHANGEABLE_GROUPS:
        if pid in g:
            return g
    return [pid]

# Board corner markers (printed on every board, same IDs on each).
BOARD_MARKER_IDS = [1, 2, 3, 4]
PX_PER_CM = 78.74               # all board frames rendered at 200 DPI

# ---- SHAPE identifier markers ------------------------------------------------
# Each board carries ONE extra marker that names the puzzle, so the game knows
# which shape is under the camera just from looking. IDs 10-19 are reserved for
# shapes (corners use 1-4, pieces use 20-26); all DICT_4X4_50.
SHAPE_MARKER_IDS = [10, 11]

# Exact silhouettes in each board's own 200-DPI frame (for the on-screen
# reference drawing). Reconstructed from tangram geometry, not pixels.
HOUSE_OUTLINE = [   # portrait board, frame 1700 x 2200
    (544, 532), (544, 864), (210, 1198), (403, 1200), (403, 1667),
    (1344, 1667), (1344, 1200), (1489, 1198), (1016, 725), (881, 856), (881, 532),
]
SWORD_OUTLINE = [   # landscape board, frame 2200 x 1700 (pommel left, tip right)
    (68, 850), (398, 519), (398, 685), (729, 685), (729, 382), (963, 616),
    (1898, 616), (2132, 850), (1898, 1084), (963, 1084), (729, 1318),
    (729, 1015), (398, 1015), (398, 1181),
]

# Per-shape config. corners = the 4 corner-marker CENTERS in THAT board's own
# 200-DPI canonical image. The homography maps the detected corners onto these,
# so each shape gets a stable, undistorted board frame of its own; targets are
# learned/saved per shape.
SHAPES: Dict[int, dict] = {
    10: {"name": "house", "title": "House", "targets": "house_targets.json",
         "outline": HOUSE_OUTLINE, "timer": 180,   # 3 minutes to build the house
         "corners": {1: (196, 196), 2: (1503, 196), 3: (1503, 2003), 4: (196, 2003)}},
    11: {"name": "sword", "title": "Sword", "targets": "sword_targets.json",
         "outline": SWORD_OUTLINE, "timer": 240,   # 4 minutes to build the sword
         "corners": {1: (196, 196), 2: (2004, 196), 3: (2004, 1504), 4: (196, 1504)}},
}
DEFAULT_SHAPE_ID = 10
_NAME_TO_SHAPE_ID = {v["name"]: k for k, v in SHAPES.items()}

# Tolerances (relaxed for children). Position is in board px; 1 cm = 78.74 px.
POSITION_TOLERANCE_PX  = 250    # ~3.2 cm
ROTATION_TOLERANCE_DEG = 22


def detect_shape_id(detections: Dict[int, "Detection"]) -> Optional[int]:
    """Pick the shape marker currently on the board (largest if several seen)."""
    seen = [(mid, cv2.contourArea(detections[mid].corners.astype(np.float32)))
            for mid in SHAPE_MARKER_IDS if mid in detections]
    if not seen:
        return None
    return max(seen, key=lambda t: t[1])[0]


# ============================================================
#  ArUco PERCEPTION
# ============================================================

@dataclass
class Detection:
    marker_id: int
    cx: float
    cy: float
    angle_deg: float
    corners: np.ndarray  # (4,2)


class PieceDetector:
    """OpenCV ArUco detection -> per-marker pose in image space."""

    def __init__(self):
        self.dictionary = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
        try:
            params = aruco.DetectorParameters()            # OpenCV 4.7+
            self.detector = aruco.ArucoDetector(self.dictionary, params)
            self._new_api = True
        except AttributeError:
            self._new_api = False                          # OpenCV <= 4.6
            self.params = aruco.DetectorParameters_create()

    def detect(self, frame: np.ndarray) -> Dict[int, Detection]:
        if self._new_api:
            corners, ids, _ = self.detector.detectMarkers(frame)
        else:
            corners, ids, _ = aruco.detectMarkers(
                frame, self.dictionary, parameters=self.params)

        results: Dict[int, Detection] = {}
        if ids is None:
            return results
        valid = set(PIECES) | set(BOARD_MARKER_IDS) | set(SHAPE_MARKER_IDS)
        for i, mid in enumerate(ids.flatten()):
            mid = int(mid)
            if mid not in valid:
                continue
            c = corners[i][0]
            cx, cy = c.mean(axis=0)
            dx, dy = c[1] - c[0]                # top edge direction
            angle = math.degrees(math.atan2(dy, dx))
            results[mid] = Detection(mid, float(cx), float(cy), float(angle), c)
        return results

    def draw_overlay(self, frame, detections, placed, board_reg=None):
        out = frame.copy()
        ok = board_reg is not None and board_reg.is_valid
        cv2.putText(out, "Board: REGISTERED" if ok else "Board: NOT FOUND",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                    (0, 200, 0) if ok else (0, 0, 255), 2)
        for d in detections.values():
            if d.marker_id in PIECES:
                col = (70, 200, 120) if d.marker_id in placed else (255, 210, 40)
                cv2.polylines(out, [d.corners.astype(int)], True, col, 2)
                cv2.putText(out, PIECES[d.marker_id]["label"],
                            (int(d.cx) + 8, int(d.cy) - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 2)
            elif d.marker_id in BOARD_MARKER_IDS:
                cv2.polylines(out, [d.corners.astype(int)], True, (255, 150, 0), 2)
                cv2.putText(out, f"REF {d.marker_id}", (int(d.cx) + 8, int(d.cy) - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 150, 0), 1)
            elif d.marker_id in SHAPE_MARKER_IDS:
                nm = SHAPES.get(d.marker_id, {}).get("name", "?")
                cv2.polylines(out, [d.corners.astype(int)], True, (200, 0, 200), 2)
                cv2.putText(out, f"SHAPE {d.marker_id}:{nm}",
                            (int(d.cx) + 8, int(d.cy) - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 0, 200), 1)
        return out


# ============================================================
#  BOARD REGISTRATION  (camera -> board homography)
# ============================================================

class BoardRegistration:
    """Homography from the 4 corner markers. Self-recovers when bumped;
    needs >=3 of the 4 corners visible."""

    def __init__(self, corners: Optional[Dict[int, Tuple[float, float]]] = None):
        self._H: Optional[np.ndarray] = None
        self._Hinv: Optional[np.ndarray] = None
        self.corners = dict(corners) if corners else dict(SHAPES[DEFAULT_SHAPE_ID]["corners"])

    def set_corners(self, corners: Dict[int, Tuple[float, float]]):
        """Switch to a different board's corner layout; forces re-registration."""
        self.corners = dict(corners)
        self._H = None
        self._Hinv = None

    def update(self, detections: Dict[int, Detection]) -> bool:
        active = {mid: detections[mid] for mid in BOARD_MARKER_IDS if mid in detections}
        if len(active) >= 3:
            src = np.array([[active[m].cx, active[m].cy] for m in sorted(active)],
                           dtype=np.float32)
            dst = np.array([list(self.corners[m]) for m in sorted(active)],
                           dtype=np.float32)
            if len(active) >= 4:
                H, _ = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
            else:
                M = cv2.getAffineTransform(src[:3], dst[:3])
                H = np.vstack([M, [0, 0, 1]])
            if H is not None:
                self._H = H
                try:
                    self._Hinv = np.linalg.inv(H)
                except np.linalg.LinAlgError:
                    self._Hinv = None
        return self._H is not None

    @property
    def is_valid(self) -> bool:
        return self._H is not None

    def camera_to_board(self, cx, cy):
        pt = np.array([[[cx, cy]]], dtype=np.float32)
        out = cv2.perspectiveTransform(pt, self._H)
        return float(out[0][0][0]), float(out[0][0][1])

    def transform_angle(self, cx, cy, angle_deg):
        dx = math.cos(math.radians(angle_deg)) * 50
        dy = math.sin(math.radians(angle_deg)) * 50
        x1, y1 = self.camera_to_board(cx, cy)
        x2, y2 = self.camera_to_board(cx + dx, cy + dy)
        return math.degrees(math.atan2(y2 - y1, x2 - x1))

    def board_pose(self, d: Detection) -> Tuple[float, float, float]:
        bx, by = self.camera_to_board(d.cx, d.cy)
        ba = self.transform_angle(d.cx, d.cy, d.angle_deg)
        return bx, by, ba


# ============================================================
#  TARGET MODEL  (slots learned by calibration)
# ============================================================
# A "slot" is one physical position in the solved house. Non-swappable pieces
# own one slot each; each interchangeable group owns two slots that either of
# its members may fill. angles[pid] is the expected marker angle for piece pid
# in that slot (filled in as you capture; swapped captures fill the partners).

@dataclass
class Slot:
    sid: int
    pos: Tuple[float, float]
    allowed: List[int]
    angles: Dict[int, float] = field(default_factory=dict)


class TargetModel:
    def __init__(self):
        self.slots: List[Slot] = []

    # ---- persistence ----
    def save(self, path: str = TARGETS_FILE):
        data = {"slots": [
            {"sid": s.sid, "pos": list(s.pos), "allowed": s.allowed,
             "angles": {str(k): v for k, v in s.angles.items()}}
            for s in self.slots]}
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"[Calib] Saved {len(self.slots)} slots -> {path}")

    @classmethod
    def load(cls, path: str = TARGETS_FILE) -> Optional["TargetModel"]:
        if not os.path.exists(path):
            return None
        try:
            data = json.load(open(path))
        except Exception as e:
            print(f"[Calib] Could not read {path}: {e}")
            return None
        m = cls()
        for s in data.get("slots", []):
            m.slots.append(Slot(
                sid=int(s["sid"]),
                pos=(float(s["pos"][0]), float(s["pos"][1])),
                allowed=[int(x) for x in s["allowed"]],
                angles={int(k): float(v) for k, v in s.get("angles", {}).items()},
            ))
        print(f"[Calib] Loaded {len(m.slots)} slots from {path}")
        return m

    @property
    def is_ready(self) -> bool:
        # need a slot for every piece (each piece must appear in some allowed set)
        covered = set()
        for s in self.slots:
            covered.update(s.allowed)
        return covered >= set(ALL_PIECE_IDS)

    def slots_for(self, pid: int) -> List[Slot]:
        return [s for s in self.slots if pid in s.allowed]

    # ---- calibration capture ----
    def capture(self, board_poses: Dict[int, Tuple[float, float, float]]) -> int:
        """Fold one capture (pid -> board (x,y,angle)) into the model.

        First capture should be the correctly solved house. A second capture
        with the two large triangles swapped AND the two small triangles
        swapped fills in the partner angles so rotation checking works for
        either piece in either swappable slot.
        """
        n = 0
        # 1) non-interchangeable pieces -> their own slot
        for pid in ALL_PIECE_IDS:
            if len(_group_of(pid)) > 1:
                continue
            if pid not in board_poses:
                continue
            x, y, a = board_poses[pid]
            existing = self.slots_for(pid)
            if existing:
                existing[0].pos = (x, y)
                existing[0].angles[pid] = a
            else:
                self.slots.append(Slot(len(self.slots), (x, y), [pid], {pid: a}))
            n += 1
        # 2) interchangeable groups
        for group in INTERCHANGEABLE_GROUPS:
            present = [(pid, board_poses[pid]) for pid in group if pid in board_poses]
            if not present:
                continue
            gslots = [s for s in self.slots if s.allowed == group]
            if not gslots:
                # bootstrap: create one slot per present member at its position
                for pid, (x, y, a) in present:
                    self.slots.append(Slot(len(self.slots), (x, y), list(group), {pid: a}))
                    n += 1
            else:
                # assign each present member to the nearest existing group slot
                for pid, (x, y, a) in present:
                    best = min(gslots, key=lambda s: (s.pos[0]-x)**2 + (s.pos[1]-y)**2)
                    best.angles[pid] = a
                    n += 1
        return n


# ---- angle helpers ----
def _ang_diff(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)

def rotation_ok(actual: float, expected: float, sym_deg: int, tol: float) -> bool:
    if sym_deg >= 360:
        return _ang_diff(actual, expected) <= tol
    d = (actual - expected) % sym_deg
    d = min(d, sym_deg - d)
    return d <= tol


# ============================================================
#  BATCH EVALUATION  (the buzzer model)
# ============================================================
ST_CORRECT   = "correct"
ST_ROTATE    = "rotate"
ST_MISPLACED = "misplaced"
ST_MISSING   = "missing"


def evaluate_board(detections: Dict[int, Detection], board_reg: BoardRegistration,
                   model: TargetModel, locked: Set[int]) -> Dict[int, str]:
    statuses: Dict[int, str] = {}
    valid = board_reg.is_valid and model is not None and model.is_ready

    poses: Dict[int, Tuple[float, float, float]] = {}
    if valid:
        for pid, d in detections.items():
            if pid in PIECES:
                poses[pid] = board_reg.board_pose(d)

    for pid in ALL_PIECE_IDS:
        if LOCK_CORRECT_PIECES and pid in locked:
            statuses[pid] = ST_CORRECT
            continue
        if not valid or pid not in poses:
            statuses[pid] = ST_MISSING
            continue

        x, y, a = poses[pid]
        sym = PIECES[pid]["rot_sym"]
        cand = model.slots_for(pid)
        # nearest allowed slot by position
        best, best_d = None, 1e18
        for s in cand:
            dd = math.hypot(x - s.pos[0], y - s.pos[1])
            if dd < best_d:
                best, best_d = s, dd
        if best is None or best_d > POSITION_TOLERANCE_PX:
            statuses[pid] = ST_MISPLACED
            continue
        # position is good; check rotation
        if pid in best.angles:
            ok = rotation_ok(a, best.angles[pid], sym, ROTATION_TOLERANCE_DEG)
        else:
            # swapped piece into a slot we never captured for it: accept on
            # position (recommend a 2nd, swapped calibration capture for strict
            # rotation checking).
            ok = True
        statuses[pid] = ST_CORRECT if ok else ST_ROTATE
    return statuses


# ============================================================
#  FEEDBACK TEXT
# ============================================================
def _join(names: List[str]) -> str:
    names = list(names)
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return f"{', '.join(names[:-1])} and {names[-1]}"

def _the(pid: int) -> str:
    return f"the {PIECES[pid]['label']}"


def build_feedback(statuses: Dict[int, str], newly_correct: List[int]
                   ) -> List[Tuple[str, str, str]]:
    """Return a list of (expression, gesture, sentence)."""
    seg: List[Tuple[str, str, str]] = []
    correct   = [p for p in ALL_PIECE_IDS if statuses[p] == ST_CORRECT]
    rotate    = [p for p in ALL_PIECE_IDS if statuses[p] == ST_ROTATE]
    misplaced = [p for p in ALL_PIECE_IDS if statuses[p] == ST_MISPLACED]

    if not correct and not rotate and not misplaced:
        seg.append(("neutral", "shrug",
                    "I don't see any pieces on the board yet. Put some on, then "
                    "press the button!"))
        return seg

    if newly_correct:
        names = _join([_the(p) for p in newly_correct])
        verb = "is" if len(newly_correct) == 1 else "are"
        if len(newly_correct) >= 2:
            seg.append(("happy", "celebrate",
                        f"Wow, great teamwork! {names.capitalize()} {verb} all in "
                        f"the perfect spot!"))
        else:
            seg.append(("happy", "nod",
                        f"Yes! {names.capitalize()} {verb} in the right place!"))


    if len(correct) >= 2 and not newly_correct:
        seg.append(("happy", "excited",
                    f"Keep going - you already have {len(correct)} pieces right!"))

    if rotate:
        names = _join([_the(p) for p in rotate])
        verb = "is" if len(rotate) == 1 else "are"
        it = "it" if len(rotate) == 1 else "them"
        seg.append(("surprise", "point",
                    f"{names.capitalize()} {verb} in the right spot - just give "
                    f"{it} a little turn!"))

    if misplaced:
        names = _join([_the(p) for p in misplaced])
        verb = "needs" if len(misplaced) == 1 else "need"
        seg.append(("neutral", "shrug",
                    f"{names.capitalize()} {verb} to move to a different spot."))
    return seg


_HINT = {
    ST_MISSING:   "I don't see the {label} yet. Can you find it and place it?",
    ST_MISPLACED: "The {label} is on the board, but it belongs in a different spot. Try moving it!",
    ST_ROTATE:    "The {label} is in the right place! Just give it a little turn.",
}


# ============================================================
#  CHILD-FACING DISPLAY  (house outline + status chips; no camera feed)
# ============================================================
_DISP_W, _DISP_H = 960, 720
_COL_BG      = (245, 245, 250)
_COL_OUTLINE = (90, 90, 90)
_COL_TITLE   = (60, 60, 60)


class TargetDisplay:
    """Clean reference: the house outline (drawn from your real board) plus a
    row of piece chips that fill in only when Misty CONFIRMS them on a press."""

    def __init__(self, outline=None, title="House"):
        self._celebration_frame = 0
        self.set_shape(outline if outline is not None else HOUSE_OUTLINE, title)

    def set_shape(self, outline, title):
        """Point the display at a different puzzle outline + name."""
        self._outline = list(outline)
        self._title = title
        xs = [p[0] for p in self._outline]
        ys = [p[1] for p in self._outline]
        self._bx0, self._by0 = min(xs), min(ys)
        bw, bh = max(xs) - min(xs), max(ys) - min(ys)
        region_w, region_h = _DISP_W - 120, _DISP_H - 245
        self._scale = min(region_w / bw, region_h / bh)
        draw_w, draw_h = bw * self._scale, bh * self._scale
        self._ox = (_DISP_W - draw_w) / 2
        self._oy = 95 + (region_h - draw_h) / 2

    def _to_disp(self, bx, by):
        return (int(self._ox + (bx - self._bx0) * self._scale),
                int(self._oy + (by - self._by0) * self._scale))

    def render(self, placed: Set[int], status_text: str = "",
               time_left: Optional[float] = None) -> np.ndarray:
        img = np.full((_DISP_H, _DISP_W, 3), 0, dtype=np.uint8)
        img[:] = _COL_BG
        title = f"Tangram Quest - Build the {self._title}!"
        (tw0, _), _ = cv2.getTextSize(title, cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2)
        cv2.putText(img, title, ((_DISP_W - tw0) // 2, 42),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, _COL_TITLE, 2, cv2.LINE_AA)

        pts = np.array([self._to_disp(*p) for p in self._outline], np.int32)
        cv2.polylines(img, [pts], True, _COL_OUTLINE, 3, cv2.LINE_AA)

        # piece status chips: single row of 7
        chip = 92
        gap = 10
        n = len(ALL_PIECE_IDS)
        total_w = n * chip + (n - 1) * gap
        x0 = (_DISP_W - total_w) // 2
        y0 = _DISP_H - 132
        for i, pid in enumerate(ALL_PIECE_IDS):
            cx = x0 + i * (chip + gap)
            cy = y0
            done = pid in placed
            col = PIECES[pid]["color_bgr"] if done else (210, 210, 215)
            cv2.rectangle(img, (cx, cy), (cx + chip, cy + chip), col, -1)
            cv2.rectangle(img, (cx, cy), (cx + chip, cy + chip), (110, 110, 110), 2)
            if done:
                cv2.line(img, (cx + 20, cy + chip // 2),
                         (cx + chip // 2 - 4, cy + chip - 24), (255, 255, 255), 5)
                cv2.line(img, (cx + chip // 2 - 4, cy + chip - 24),
                         (cx + chip - 18, cy + 22), (255, 255, 255), 5)
            short = PIECES[pid]["label"].replace(" triangle", " tri").replace(
                "light blue", "lt-blue").replace("parallelogram", "p-gram")
            cv2.putText(img, short, (cx - 2, cy + chip + 16),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.36,
                        (40, 40, 40) if done else (130, 130, 130), 1, cv2.LINE_AA)

        # timer bar
        if time_left is not None:
            self._draw_timer(img, time_left)

        remaining = len(ALL_PIECE_IDS) - len(placed)
        if not status_text:
            status_text = ("Place pieces, then press SPACE to check!"
                           if remaining > 0 else "All pieces placed!")
        (tw, _), _ = cv2.getTextSize(status_text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        cv2.putText(img, status_text, ((_DISP_W - tw) // 2, y0 - 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (40, 40, 40), 2, cv2.LINE_AA)
        return img

    def _draw_timer(self, img, time_left):
        total = max(1e-3, getattr(self, "_timer_total", 120.0))
        frac = max(0.0, min(1.0, time_left / total))
        bx, by, bw, bh = 250, 56, 400, 16
        cv2.rectangle(img, (bx, by), (bx + bw, by + bh), (210, 210, 215), -1)
        col = (70, 180, 70) if frac > 0.5 else (40, 180, 235) if frac > 0.25 else (40, 40, 220)
        cv2.rectangle(img, (bx, by), (bx + int(bw * frac), by + bh), col, -1)
        m, s = divmod(int(max(0, time_left)), 60)
        cv2.putText(img, f"{m}:{s:02d}", (bx + bw + 12, by + bh),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (60, 60, 60), 2, cv2.LINE_AA)

    def render_wait(self) -> np.ndarray:
        """Shown when no board is under the camera yet."""
        img = np.full((_DISP_H, _DISP_W, 3), 0, dtype=np.uint8)
        img[:] = _COL_BG
        for txt, fs, y in [("Tangram Quest", 1.3, _DISP_H // 2 - 70),
                           ("Place a puzzle board under the camera", 0.8,
                            _DISP_H // 2),
                           ("(house or sword)", 0.6, _DISP_H // 2 + 44)]:
            (tw, _), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, fs, 2)
            cv2.putText(img, txt, ((_DISP_W - tw) // 2, y),
                        cv2.FONT_HERSHEY_SIMPLEX, fs, _COL_TITLE, 2, cv2.LINE_AA)
        return img

    def render_calibration(self, board_ok: bool, n_captures: int,
                           captured: Dict[int, bool]) -> np.ndarray:
        img = np.full((_DISP_H, _DISP_W, 3), 235, dtype=np.uint8)
        cv2.putText(img, "CALIBRATION MODE", (250, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (40, 40, 200), 3, cv2.LINE_AA)
        lines = [
            f"1. Solve the {self._title.upper()} correctly under the camera.",
            "2. Press  C  to capture.",
            "3. Swap the 2 large triangles AND the 2 small",
            "   triangles, then press  C  again (for rotation).",
            "4. Press  S  to save and start playing.",
            "",
            f"Board corners visible: {'YES' if board_ok else 'NO - show all 4'}",
            f"Captures taken: {n_captures}",
        ]
        y = 110
        for ln in lines:
            cv2.putText(img, ln, (60, y), cv2.FONT_HERSHEY_SIMPLEX, 0.62,
                        (40, 40, 40), 2, cv2.LINE_AA)
            y += 38
        x = 60
        y += 6
        cv2.putText(img, "Detected now:", (60, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (40, 40, 40), 2, cv2.LINE_AA)
        y += 34
        for pid in ALL_PIECE_IDS:
            seen = captured.get(pid, False)
            col = (70, 160, 70) if seen else (160, 160, 160)
            cv2.circle(img, (x + 10, y - 6), 8, col, -1)
            cv2.putText(img, PIECES[pid]["label"], (x + 28, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1, cv2.LINE_AA)
            y += 30
        return img

    def render_celebration(self) -> np.ndarray:
        self._celebration_frame += 1
        pulse = int(15 * math.sin(self._celebration_frame * 0.12))
        img = np.full((_DISP_H, _DISP_W, 3), 235 + pulse, dtype=np.uint8)
        pts = np.array([self._to_disp(*p) for p in self._outline], np.int32)
        cv2.fillPoly(img, [pts], (225, 235, 225))
        cv2.polylines(img, [pts], True, (80, 160, 100), 4, cv2.LINE_AA)
        np.random.seed(7)
        for _ in range(14):
            cx = np.random.randint(40, _DISP_W - 40)
            cy = np.random.randint(40, _DISP_H - 40)
            r = np.random.randint(8, 20)
            a = 150 + int(50 * math.sin(self._celebration_frame * 0.08 + cx))
            cv2.circle(img, (cx, cy), r, (a, a, a), -1, cv2.LINE_AA)
        msg = f"{self._title.upper()} COMPLETE!"
        (tw0, _), _ = cv2.getTextSize(msg, cv2.FONT_HERSHEY_SIMPLEX, 1.2, 3)
        cv2.putText(img, msg, ((_DISP_W - tw0) // 2, _DISP_H // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (40, 40, 200), 3, cv2.LINE_AA)
        return img


# ============================================================
#  MISTY II INTERFACE
# ============================================================
_MISTY_EYES = {
    "happy":    "e_Joy.jpg",
    "surprise": "e_Amazement.jpg",
    "neutral":  "e_DefaultContent.jpg",
    "thinking": "e_ContentLeft.jpg",
    "sad":      "e_Sadness.jpg",
}
_MISTY_LED = {
    "happy": (0, 200, 0), "surprise": (255, 170, 0), "neutral": (0, 120, 255),
    "thinking": (120, 0, 255), "sad": (200, 0, 0),
}
BUZZER_SENSORS = {"HeadFront", "HeadBack", "HeadLeft", "HeadRight", "Scruff", "Chin"}


class MistyAgent:
    """Talks to Misty II via raw REST (default) or the mistyPy SDK."""

    _REST_TIMEOUT = 1.5
    _TTS_TIMEOUT = 5.0

    def __init__(self, ip: str, words_per_sec: float = 2.6):
        self.words_per_sec = words_per_sec
        self.base = f"http://{ip}/api"
        self._ip = ip
        self._sdk = None
        self.follower = None
        self._buzzer = threading.Event()

        if USE_MISTY_SDK:
            try:
                from mistyPy.Robot import Robot as _R
            except (ImportError, ModuleNotFoundError):
                from mistyPy import Robot as _R
            try:
                self._sdk = _R(ip)
            except Exception as e:
                print(f"[Misty warn] SDK init failed ({e}); using REST.")
                self._sdk = None
        if self._sdk is None and requests is None:
            raise RuntimeError("REST mode needs `requests` (pip install requests).")

        if requests is not None:
            try:
                requests.get(f"http://{ip}/api", timeout=2.0)
                print(f"[Misty] {ip} reachable.")
            except Exception:
                print(f"[Misty] WARNING: cannot reach Misty at {ip} "
                      f"(powered on? same WiFi? try: ping {ip})")

        def _startup():
            if self._sdk:
                try:
                    self._sdk.halt()
                    self._sdk.set_default_volume(MISTY_VOLUME)
                except Exception as e:
                    print(f"[Misty warn] startup: {e}")
            self.reset_pose()
        t = threading.Thread(target=_startup, daemon=True)
        t.start()
        t.join(timeout=6.0)

    # ---- tracking pause hooks ----
    def _pause_tracking(self):
        if self.follower is not None:
            self.follower.pause()

    def _resume_tracking(self):
        if self.follower is not None:
            self.follower.resume()

    # ---- REST helper ----
    def _post(self, endpoint, payload):
        try:
            requests.post(f"{self.base}{endpoint}", json=payload,
                          timeout=self._REST_TIMEOUT)
        except Exception as e:
            print(f"[Misty warn] POST {endpoint}: {e}")

    # ---- speech ----
    def say(self, text: str, block: bool = True) -> None:
        print(f"[Misty says] {text}")
        spoken = False
        if requests is not None:
            try:
                requests.post(f"http://{self._ip}/api/tts/speak",
                              json={"Text": text, "Voice": MISTY_VOICE,
                                    "Pitch": MISTY_PITCH,
                                    "SpeechRate": MISTY_SPEECH_RATE, "Flush": True},
                              timeout=self._TTS_TIMEOUT)
                spoken = True
            except Exception as e:
                print(f"[Misty warn] speak: {e}")
        elif self._sdk:
            try:
                self._sdk.speak(text, flush=True)
                spoken = True
            except Exception as e:
                print(f"[Misty warn] speak SDK: {e}")
        if block and spoken:
            words = max(1, len(text.split()))
            time.sleep(words / (self.words_per_sec * MISTY_SPEECH_RATE) + 0.5)

    def say_with_gesture(self, text: str, gesture_name: str) -> None:
        self._pause_tracking()
        t = threading.Thread(target=self.gesture, args=(gesture_name,), daemon=True)
        t.start()
        self.say(text, block=True)
        t.join(timeout=5.0)

    # ---- face + LED ----
    def express(self, emotion: str) -> None:
        eye = _MISTY_EYES.get(emotion, _MISTY_EYES["neutral"])
        r, g, b = _MISTY_LED.get(emotion, _MISTY_LED["neutral"])
        if self._sdk:
            try:
                self._sdk.display_image(eye, 1)
                self._sdk.change_led(r, g, b)
                return
            except Exception:
                pass
        self._post("/images/display", {"FileName": eye, "Alpha": 1})
        self._post("/led", {"red": r, "green": g, "blue": b})

    # ---- arms / head ----
    def _move_arms(self, left, right):
        if self._sdk:
            try:
                self._sdk.move_arms(left, right); return
            except Exception:
                pass
        self._post("/arms/set", {"LeftArmPosition": left, "RightArmPosition": right,
                                 "Units": "degrees"})

    def _move_head(self, pitch=0, roll=0, yaw=0, vel=100):
        if self._sdk:
            try:
                self._sdk.move_head(pitch, roll, yaw, velocity=vel); return
            except Exception:
                pass
        self._post("/head", {"Pitch": pitch, "Roll": roll, "Yaw": yaw,
                             "Velocity": vel, "Units": "degrees"})

    def reset_pose(self):
        self._pause_tracking()
        self._move_head(0, 0, 0)
        self._move_arms(70, 70)
        time.sleep(0.4)
        self._resume_tracking()

    def gesture(self, name: str) -> None:
        self._pause_tracking()
        if name in ("clapping", "celebrate"):
            for _ in range(3):
                self._move_arms(-29, -29); time.sleep(0.35)
                self._move_arms(70, 70);   time.sleep(0.35)
        elif name == "dance":
            for _ in range(2):
                self._move_arms(-29, 70); self._move_head(0, 20, 20); time.sleep(0.4)
                self._move_arms(70, -29); self._move_head(0, -20, -20); time.sleep(0.4)
            self._move_head(0, 0, 0); self._move_arms(70, 70)
        elif name == "wave":
            for _ in range(2):
                self._move_arms(70, -20); time.sleep(0.3)
                self._move_arms(70, 10);  time.sleep(0.3)
            self._move_arms(70, 70)
        elif name == "point":
            self._move_arms(70, -15); time.sleep(0.5); self._move_arms(70, 70)
        elif name == "nod":
            self._move_head(15, 0, 0); time.sleep(0.35)
            self._move_head(-10, 0, 0); time.sleep(0.35); self._move_head(0, 0, 0)
        elif name == "shrug":
            self._move_arms(20, 20); time.sleep(0.4); self._move_arms(70, 70)
        elif name == "excited":
            self._move_arms(-29, -29); time.sleep(0.25)
            self._move_arms(50, 50);   time.sleep(0.25)
            self._move_arms(-29, -29); time.sleep(0.25); self._move_arms(70, 70)

    def play_sound(self, filename, volume=60):
        if self._sdk:
            try:
                self._sdk.play_audio(filename, volume=volume); return
            except Exception:
                pass
        self._post("/audio/play", {"FileName": filename, "Volume": volume})

    # ---- optional touch buzzer ----
    def enable_touch_buzzer(self):
        if not self._sdk:
            print("[Misty] Touch buzzer needs the SDK (USE_MISTY_SDK=True).")
            return
        from mistyPy.Events import Events
        self._sdk.register_event(event_name="tangram_buzzer",
                                 event_type=Events.TouchSensor,
                                 callback_function=self._on_touch, keep_alive=True)
        print("[Misty] Touch-sensor buzzer enabled.")

    def _on_touch(self, data):
        try:
            sensor = None
            if isinstance(data, dict):
                msg = data.get("message", data)
                sensor = msg.get("sensorPosition") if isinstance(msg, dict) else msg
            if sensor in BUZZER_SENSORS:
                self._buzzer.set()
        except Exception as e:
            print(f"[Misty warn] touch: {e}")

    def poll_buzzer(self) -> bool:
        if self._buzzer.is_set():
            self._buzzer.clear()
            return True
        return False

    def cleanup(self):
        if self._sdk:
            try:
                self._sdk.unregister_all_events()
            except Exception:
                pass
        try:
            self.express("neutral")
            self.reset_pose()
        except Exception:
            pass

    # ---- optional local LLM rephrase ----
    def ai_edge_rephrase(self, sentences: List[str], timeout_s: float = 8.0):
        system = ("You are a warm robot helping children build a tangram house. "
                  "Rephrase the feedback into 1-2 short, kind, encouraging "
                  "sentences. Keep every fact. No lists. Max 35 words.")
        prompt = f"{system}\n\nFeedback: {' '.join(sentences)}\n\nRephrased:"
        payload = json.dumps({"model": OLLAMA_MODEL, "prompt": prompt,
                              "stream": False}).encode()
        try:
            req = urllib.request.Request("http://localhost:11434/api/generate",
                                         data=payload,
                                         headers={"Content-Type": "application/json"},
                                         method="POST")
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                return json.loads(resp.read().decode()).get("response", "").strip() or None
        except Exception as e:
            print(f"[Misty warn] Ollama: {e}")
            return None


class DummyAgent:
    """No-robot stand-in for testing vision + buzzer."""
    def __init__(self):
        self.follower = None
    def _pause_tracking(self): pass
    def _resume_tracking(self): pass
    def say(self, text, block=True):
        print(f"[NO-ROBOT says] {text}")
        if block:
            time.sleep(min(1.5, 0.25 + 0.12 * len(text.split())))
    def express(self, emotion): print(f"[NO-ROBOT face] {emotion}")
    def gesture(self, name): print(f"[NO-ROBOT gesture] {name}")
    def say_with_gesture(self, text, g): print(f"[NO-ROBOT {g}] {text}"); self.say(text)
    def play_sound(self, f, volume=60): pass
    def reset_pose(self): pass
    def _move_head(self, pitch=0, roll=0, yaw=0, vel=100): pass
    def enable_touch_buzzer(self): print("[NO-ROBOT] use SPACE bar.")
    def poll_buzzer(self): return False
    def cleanup(self): pass
    def ai_edge_rephrase(self, s, timeout_s=8.0): return None


# ============================================================
#  MISTY HEAD FOLLOWER  (Haar face tracking -> head yaw/pitch)
# ============================================================
class _MistyCameraStream:
    _TARGET_FPS = 8.0
    def __init__(self, misty_ip: str):
        self._url = f"http://{misty_ip}/api/cameras/rgb?base64=false&width=320&height=240"
        self._lock = threading.Lock()
        self._frame = None
        self._new = False
        self._running = False
        self._thread = None
    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()
    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3.0)
    def _poll(self):
        if requests is None:
            return
        delay = 1.0 / self._TARGET_FPS
        while self._running:
            t0 = time.time()
            try:
                resp = requests.get(self._url, timeout=3.0)
                if resp.status_code == 200 and resp.content:
                    arr = np.frombuffer(resp.content, np.uint8)
                    fr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                    if fr is not None:
                        with self._lock:
                            self._frame, self._new = fr, True
            except Exception as e:
                print(f"[MistyCam] {e}")
            time.sleep(max(0.0, delay - (time.time() - t0)))
    def read(self):
        with self._lock:
            if self._frame is not None and self._new:
                self._new = False
                return True, self._frame.copy()
        return False, None


class MistyHeadFollower:
    DEADZONE = 0.01
    PITCH_OFFSET = 3.0
    TIMEOUT_STOP, TIMEOUT_RESET, TIMEOUT_PATROL = 5.0, 10.0, 20.0
    GAIN_INC_YAW, GAIN_INC_PITCH = 20.0, 12.0
    YAW_MAX, YAW_MIN = 75.0, -75.0
    PITCH_MAX, PITCH_MIN = 20.0, -35.0

    def __init__(self, agent, camera_index: Optional[int] = 0,
                 misty_ip: Optional[str] = None, use_viz: bool = False):
        self._agent = agent
        self._cam_idx = camera_index
        self._misty_ip = misty_ip
        self._use_viz = use_viz
        self._misty_cam = None
        self._lock = threading.Lock()
        self._is_active = True
        self._running = False
        self._thread = None
        self._last_yaw = self._last_pitch = 0.0
        self._last_send_time = 0.0
        self._last_person_seen_time = 0.0
        self._last_state_log_time = 0.0
        self._viz_frame = None
        self._viz_lock = threading.Lock()
        cascade = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        self._face = cv2.CascadeClassifier(cascade)
        if self._face.empty():
            raise RuntimeError("Could not load Haar cascade.")

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        print("[HeadFollower] Started.")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3.0)

    def pause(self):
        with self._lock:
            self._is_active = False

    def resume(self):
        with self._lock:
            self._is_active = True

    def get_viz_frame(self):
        with self._viz_lock:
            return self._viz_frame

    def _run(self):
        cap = None
        if self._misty_ip and self._cam_idx is None:
            self._misty_cam = _MistyCameraStream(self._misty_ip)
            self._misty_cam.start()
            time.sleep(0.5)
        else:
            backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
            cap = cv2.VideoCapture(self._cam_idx, backend)
            if not cap.isOpened():
                print(f"[HeadFollower] cannot open camera {self._cam_idx}; disabled.")
                return
        self._reset_head()
        rate = 1.0 / 10
        while self._running:
            ret, frame = (self._misty_cam.read() if self._misty_cam else cap.read())
            if not ret or frame is None:
                time.sleep(rate); continue
            try:
                self._update(frame)
            except Exception as e:
                print(f"[HeadFollower] {e}")
            time.sleep(rate)
        if cap is not None:
            cap.release()
        if self._misty_cam is not None:
            self._misty_cam.stop()
        self._reset_head()

    def _update(self, frame):
        with self._lock:
            if not self._is_active:
                return
        now = time.time()
        self._track(frame)
        dt = now - self._last_person_seen_time
        if dt < self.TIMEOUT_STOP:
            pass
        elif dt < self.TIMEOUT_RESET:
            self._last_yaw *= 0.95; self._last_pitch *= 0.95; self._publish()
        elif dt < self.TIMEOUT_PATROL:
            self._last_yaw = 30.0 * math.sin(now * 0.3); self._last_pitch = -5.0
            self._publish()

    def _track(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        min_sz = (40, 40) if self._misty_cam is not None else (60, 60)
        faces = self._face.detectMultiScale(gray, 1.1, 4, minSize=min_sz)
        if len(faces) > 0:
            self._last_person_seen_time = time.time()
            fx, fy, fw, fh = max(faces, key=lambda f: f[2] * f[3])
            h, w = frame.shape[:2]
            cx = (fx + fw / 2) / w
            cy = (fy + fh / 2) / h
            if self._misty_cam is not None:
                ty = self._last_yaw + (cx - 0.5) * self.GAIN_INC_YAW
                tp = self._last_pitch + (cy - 0.5) * self.GAIN_INC_PITCH
            else:
                ty = (cx - 0.5) * self.YAW_MAX * 0.85
                tp = (cy - 0.5) * self.PITCH_MAX * 0.70
            a = 0.35
            self._last_yaw = a * ty + (1 - a) * self._last_yaw
            self._last_pitch = a * tp + (1 - a) * self._last_pitch
            self._publish()
        if self._use_viz:
            vis = frame.copy()
            for (x, y, fw, fh) in faces:
                cv2.rectangle(vis, (x, y), (x + fw, y + fh), (0, 255, 0), 2)
            with self._viz_lock:
                self._viz_frame = vis

    def _publish(self, force=False):
        yaw = max(self.YAW_MIN, min(self.YAW_MAX, self._last_yaw))
        pitch = max(self.PITCH_MIN, min(self.PITCH_MAX, self._last_pitch + self.PITCH_OFFSET))
        now = time.time()
        if force or now - self._last_send_time >= 0.2:
            self._last_send_time = now
            self._agent._move_head(pitch=pitch, roll=0, yaw=yaw, vel=80)

    def _reset_head(self):
        self._last_yaw = self._last_pitch = 0.0
        self._publish(force=True)


# ============================================================
#  GAME STATE + HANDLERS
# ============================================================
@dataclass
class GameState:
    placed: Set[int] = field(default_factory=set)
    @property
    def is_complete(self) -> bool:
        return len(self.placed) == len(ALL_PIECE_IDS)


def _speak_segments(qt, segments, llm_feedback: bool):
    if llm_feedback:
        rephrased = qt.ai_edge_rephrase([s for _, _, s in segments])
        if rephrased:
            expr = segments[0][0] if segments else "neutral"
            gest = segments[0][1] if segments else "nod"
            qt.express(expr)
            qt.say_with_gesture(rephrased, gest)
            return
    for expression, gesture_name, sentence in segments:
        qt.express(expression)
        qt.say_with_gesture(sentence, gesture_name)
        time.sleep(0.15)


def handle_buzzer(qt, state, detections, board_reg, model, llm_feedback):
    statuses = evaluate_board(detections, board_reg, model, state.placed)
    newly = [p for p in ALL_PIECE_IDS
             if statuses[p] == ST_CORRECT and p not in state.placed]
    segments = build_feedback(statuses, newly)
    for p in newly:
        state.placed.add(p)
    _speak_segments(qt, segments, llm_feedback)
    qt.reset_pose()


def handle_hint(qt, state, detections, board_reg, model):
    if not board_reg.is_valid:
        qt.express("neutral"); qt.gesture("shrug")
        qt.say("I can't see the board corners. Let's make sure all four corner "
               "markers are showing!")
        return
    statuses = evaluate_board(detections, board_reg, model, state.placed)
    for st in (ST_MISSING, ST_MISPLACED, ST_ROTATE):
        cand = [p for p in ALL_PIECE_IDS if statuses[p] == st]
        if cand:
            qt.express("thinking"); qt.gesture("point")
            qt.say(_HINT[st].format(label=PIECES[cand[0]]["label"]))
            qt.reset_pose()
            return
    qt.express("happy"); qt.gesture("nod")
    qt.say("Everything looks great! Press the button to check!")


def _on_complete(qt, display, win):
    qt.express("happy"); qt.gesture("celebrate"); time.sleep(0.3)
    name = display._title.lower() if display is not None else "puzzle"
    qt.say(f"Incredible! You built the whole {name}! That was wonderful work!")
    qt.gesture("dance")
    if display is not None:
        for _ in range(120):
            cv2.imshow(win, display.render_celebration())
            if cv2.waitKey(33) & 0xFF == ord("q"):
                break


INACTIVITY_TIMEOUT = 18.0
_INACTIVITY_NUDGES = [
    ("neutral", "nod",   "Don't be shy - put a piece on the board and give it a try!"),
    ("surprise", "point", "Which piece do you think comes next? Take a guess!"),
    ("happy", "wave",    "You've got this! Pick any piece and place it!"),
    ("thinking", "shrug", "Hmm, where could the next piece go? Try one!"),
]


# ============================================================
#  TIMER + SCORING HELPERS
# ============================================================
_NUM_WORDS = {0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
              6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}


def _num_word(n: int) -> str:
    return _NUM_WORDS.get(int(n), str(int(n)))


def _spoken_duration(total_seconds: float) -> str:
    """A child-friendly spoken length, e.g. 180 -> 'three minutes',
    90 -> 'one minute and 30 seconds'."""
    total = int(round(total_seconds))
    m, s = divmod(total, 60)
    parts = []
    if m:
        parts.append(f"{_num_word(m)} minute" + ("s" if m != 1 else ""))
    if s:
        sec = _num_word(s) if s <= 10 else str(s)
        parts.append(f"{sec} second" + ("s" if s != 1 else ""))
    return " and ".join(parts) if parts else "no time"


def build_timer_milestones(total_seconds: float, final_warning_seconds: float = 20.0):
    """Reminders to speak during the round, keyed by seconds-REMAINING.

    One reminder at each whole minute left (the very start is announced
    separately), plus a final warning `final_warning_seconds` before the end.
    Each entry is {t, expr, gest, msg, fired}; the round loop fires them once.
    """
    total = float(total_seconds)
    ms = []
    for m in range(int(total // 60), 0, -1):
        t = m * 60
        if t >= total:                       # start is announced on its own
            continue
        if m == 1:
            msg = "One minute left! Keep building!"
            expr, gest = "surprise", "excited"
        else:
            msg = f"{_num_word(m).capitalize()} minutes left! You're doing great!"
            expr, gest = "neutral", "point"
        ms.append({"t": float(t), "expr": expr, "gest": gest, "msg": msg})

    fw = float(final_warning_seconds)
    if 0 < fw < total and all(abs(fw - d["t"]) > 1e-6 for d in ms):
        secs = _num_word(int(fw)) if fw <= 10 else str(int(fw))
        ms.append({"t": fw, "expr": "surprise", "gest": "excited",
                   "msg": f"Only {secs} seconds left! Hurry, you can do it!"})

    ms.sort(key=lambda d: d["t"], reverse=True)   # largest remaining first
    for d in ms:
        d["fired"] = False
    return ms


# ============================================================
#  CALIBRATION FLOW
# ============================================================
def run_calibration(cap, detector, board_reg, display, model: TargetModel,
                    win: str, targets_path: str) -> bool:
    """Interactive calibration for the ACTIVE shape. Returns True if saved."""
    print(f"\n[Calib] Calibration mode for '{display._title}'. Solve it, press C "
          f"to capture, swap the swappable pairs, press C again, then S to save. "
          f"Q aborts.")
    n_captures = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            continue
        detections = detector.detect(frame)
        board_ok = board_reg.update(detections)
        captured_now = {pid: (pid in detections) for pid in ALL_PIECE_IDS}
        cv2.imshow(win, display.render_calibration(board_ok, n_captures, captured_now))
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            print("[Calib] Aborted.")
            return False
        if key in (ord("c"), ord("C")):
            if not board_ok:
                print("[Calib] Need all/3+ board corners visible to capture.")
                continue
            poses = {pid: board_reg.board_pose(d)
                     for pid, d in detections.items() if pid in PIECES}
            added = model.capture(poses)
            n_captures += 1
            print(f"[Calib] Capture {n_captures}: folded {added} pieces "
                  f"({len(poses)} detected).")
        if key in (ord("s"), ord("S")):
            if not model.is_ready:
                missing = set(ALL_PIECE_IDS) - {p for s in model.slots for p in s.allowed}
                print(f"[Calib] Not all pieces captured yet. Missing slots for: "
                      f"{sorted(missing)}. Capture the full solved shape first.")
                continue
            model.save(targets_path)
            return True


# ============================================================
#  MAIN GAME LOOP
# ============================================================
def run_level(qt, camera_index=1, show_camera=False, llm_feedback=False,
              touch_buzzer=False, face_camera=0, face_tracking=True,
              misty_face_camera=False, show_face_camera=False,
              force_calibrate=False, timer_seconds=-1.0, final_warning_seconds=20.0,
              forced_shape_id=None):
    detector = PieceDetector()
    display = TargetDisplay()
    board_reg = BoardRegistration()

    backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
    print(f"[Camera] Opening puzzle camera {camera_index} ...")
    cap = cv2.VideoCapture(camera_index, backend)
    # JVCU100 / overhead webcam: force MJPG @ 1080p so small markers decode and
    # USB2 doesn't throttle the frame rate.
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    if not cap.isOpened():
        print(f"ERROR: could not open puzzle camera {camera_index}.")
        sys.exit(1)
    print(f"[Camera] Puzzle camera {camera_index} ready "
          f"({int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x"
          f"{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}).")

    win = "Tangram Quest"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)

    # ---- face tracking (independent of which puzzle is up) ----
    follower = None
    if face_tracking:
        try:
            if misty_face_camera and hasattr(qt, "_ip"):
                follower = MistyHeadFollower(qt, camera_index=None,
                                             misty_ip=qt._ip, use_viz=show_face_camera)
            else:
                follower = MistyHeadFollower(qt, camera_index=face_camera,
                                             use_viz=show_face_camera)
            follower.start()
            qt.follower = follower
        except Exception as e:
            print(f"[HeadFollower] disabled: {e}")
            follower = None

    if touch_buzzer:
        qt.enable_touch_buzzer()
    button_word = "tap my head" if touch_buzzer else "press the space bar"

    # ---- per-shape session state (reset whenever the board changes) ----
    active_id = None
    shape_cfg = None
    model = None
    state = GameState()
    welcomed = False
    game_start_time = None
    timed_out = False
    last_press = last_hint = 0.0
    last_activity = time.time()
    inactivity_nudged = False
    nudge_idx = 0
    cand_id, cand_count = None, 0          # shape-switch debounce
    SWITCH_FRAMES = 5
    BUZZER_COOLDOWN, HINT_COOLDOWN = 0.8, 3.0

    # ---- timer + scoring ----
    score = 0                 # one point per shape completed within its time
    round_scored = False      # has THIS round's point/no-point been decided?
    current_timer = 0.0       # this shape's countdown length (seconds)
    timer_total = 0.0         # the timer actually running this round
    milestones = []           # spoken reminders for this round

    def resolve_timer(cfg) -> float:
        """Pick this shape's countdown length.
        timer_seconds < 0 -> per-shape default (house 180, sword 240);
        timer_seconds == 0 -> timer off; timer_seconds > 0 -> global override."""
        if timer_seconds < 0:
            return float(cfg.get("timer", 0.0))
        return float(timer_seconds)

    def reset_round():
        """Clear everything tied to one build attempt (keeps cumulative score)."""
        nonlocal state, welcomed, game_start_time, timed_out, round_scored
        nonlocal timer_total, milestones, last_activity, inactivity_nudged
        state = GameState()
        welcomed = False
        game_start_time = None
        timed_out = False
        round_scored = False
        timer_total = 0.0
        milestones = []
        last_activity = time.time()
        inactivity_nudged = False

    def configure_for_shape(sid) -> bool:
        """Point the board frame / display / targets at shape `sid`.
        Calibrates if that shape has no usable targets. False = calib aborted."""
        nonlocal active_id, shape_cfg, model, state, welcomed, game_start_time
        nonlocal timed_out, last_activity, inactivity_nudged
        nonlocal current_timer, round_scored, timer_total, milestones
        cfg = SHAPES[sid]
        board_reg.set_corners(cfg["corners"])
        display.set_shape(cfg["outline"], cfg["title"])
        m = None if force_calibrate else TargetModel.load(cfg["targets"])
        if force_calibrate or m is None or not m.is_ready:
            print(f"[Calib] No usable targets for '{cfg['name']}' - calibrating.")
            m = TargetModel()
            if not run_calibration(cap, detector, board_reg, display, m,
                                   win, cfg["targets"]):
                return False
        model = m
        active_id = sid
        shape_cfg = cfg
        current_timer = resolve_timer(cfg)
        state = GameState()
        welcomed = False
        game_start_time = None
        timed_out = False
        round_scored = False
        timer_total = 0.0
        milestones = []
        last_activity = time.time()
        inactivity_nudged = False
        tinfo = (f"{_spoken_duration(current_timer)} timer" if current_timer > 0
                 else "no timer")
        print(f"[Game] Now playing: {cfg['title']} ({tinfo})")
        return True

    print("\n[Game] *** CLICK THE GAME WINDOW so it has keyboard focus ***")
    print("[Game] SPACE = check | H = hint | K = recalibrate | Q = quit")
    if forced_shape_id is None:
        print("[Game] Put the house OR sword board under the camera to begin.\n")

    try:
        if forced_shape_id is not None:
            if not configure_for_shape(forced_shape_id):
                print("[Game] Calibration not completed; exiting.")
                cap.release(); cv2.destroyAllWindows(); qt.cleanup()
                return

        while True:
            ret, frame = cap.read()
            if not ret:
                continue
            detections = detector.detect(frame)

            # ---- which puzzle is on the table? (debounced; skip if forced) ----
            if forced_shape_id is None:
                seen = detect_shape_id(detections)
                if seen is not None and seen != active_id:
                    cand_count = cand_count + 1 if seen == cand_id else 1
                    cand_id = seen
                    if cand_count >= SWITCH_FRAMES:
                        cand_id, cand_count = None, 0
                        if not configure_for_shape(seen):
                            active_id = None      # aborted -> back to waiting
                            continue
                else:
                    cand_id, cand_count = None, 0

            # ---- nothing selected yet: ask for a board ----
            if active_id is None:
                cv2.imshow(win, display.render_wait())
                if (cv2.waitKey(1) & 0xFF) == ord("q"):
                    break
                continue

            board_reg.update(detections)

            # welcome on first registration of this puzzle
            if board_reg.is_valid and not welcomed:
                welcomed = True
                name = shape_cfg["title"].lower()
                qt.express("happy")
                qt.say_with_gesture(
                    f"Hello friends! Welcome to Tangram Quest! Let's build the "
                    f"{name} together!", "wave")
                time.sleep(0.1)
                qt.say_with_gesture(
                    f"Place the seven pieces inside the outline, then {button_word} "
                    "and I'll check your work!", "point")

                # arm this round's countdown (house = 3 min, sword = 4 min)
                timer_total = float(current_timer)
                timed_out = False
                round_scored = False
                if timer_total > 0:
                    display._timer_total = timer_total
                    milestones = build_timer_milestones(timer_total,
                                                         final_warning_seconds)
                    qt.express("surprise")
                    qt.say_with_gesture(
                        f"You have {_spoken_duration(timer_total)} to build the "
                        f"{name}. Finish in time to earn a point. "
                        f"Ready, set, go!", "excited")
                else:
                    milestones = []
                qt.reset_pose()
                game_start_time = time.time()   # clock starts AFTER the intro
                last_activity = time.time()

            # ---- timer: spoken reminders + time's-up scoring ----
            time_left = None
            if timer_total > 0 and game_start_time is not None:
                elapsed = time.time() - game_start_time
                time_left = max(0.0, timer_total - elapsed)

                # fire the most urgent un-spoken reminder (skip any we overran)
                overdue = [m for m in milestones
                           if not m["fired"] and time_left <= m["t"]]
                if overdue:
                    chosen = min(overdue, key=lambda m: m["t"])
                    for m in overdue:
                        m["fired"] = True
                    qt.express(chosen["expr"])
                    qt.say_with_gesture(chosen["msg"], chosen["gest"])
                    qt.reset_pose()

                # time's up -> no point this round (locks the result)
                if (not timed_out) and time_left <= 0:
                    timed_out = True
                    if not round_scored:
                        round_scored = True
                        qt.express("neutral")
                        qt.say_with_gesture(
                            "Time's up! You didn't finish this one in time, so no "
                            "point this round. But you worked so hard - let's try "
                            "again!", "nod")
                        qt.reset_pose()
                        print(f"[Score] Time out on '{shape_cfg['title']}': "
                              f"no point. Total score: {score}")
                        reset_round()
                        continue

            status = ""
            if not board_reg.is_valid:
                status = "Show all 4 board corners to the camera..."
            cv2.imshow(win, display.render(state.placed, status, time_left))

            if show_camera:
                cv2.imshow("Camera (debug)",
                           detector.draw_overlay(frame, detections, state.placed, board_reg))
            if show_face_camera and follower is not None:
                viz = follower.get_viz_frame()
                if viz is not None:
                    h, w = viz.shape[:2]
                    if w > 640:
                        viz = cv2.resize(viz, (640, int(h * 640 / w)))
                    cv2.imshow("Face Tracking", viz)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key in (ord("k"), ord("K")):
                # recalibrate the ACTIVE puzzle on demand
                m = TargetModel()
                if run_calibration(cap, detector, board_reg, display, m,
                                   win, shape_cfg["targets"]):
                    model = m
                    state.placed.clear()
                    print(f"[Game] Recalibrated '{shape_cfg['name']}'.")
                continue

            buzzed = (key == 32) or qt.poll_buzzer()
            if buzzed and (time.time() - last_press) > BUZZER_COOLDOWN:
                last_press = last_activity = time.time()
                inactivity_nudged = False
                if not board_reg.is_valid:
                    qt.express("neutral"); qt.gesture("shrug")
                    qt.say("I can't see the board yet. Let's show all four corners!")
                    continue
                handle_buzzer(qt, state, detections, board_reg, model, llm_feedback)
                cv2.imshow(win, display.render(state.placed, "", time_left))
                cv2.waitKey(1)

            if key == ord("h") and (time.time() - last_hint) > HINT_COOLDOWN:
                last_hint = last_activity = time.time()
                inactivity_nudged = False
                handle_hint(qt, state, detections, board_reg, model)

            # inactivity nudge
            if (time.time() - last_activity) > INACTIVITY_TIMEOUT and not inactivity_nudged \
                    and welcomed:
                expr, gest, msg = _INACTIVITY_NUDGES[nudge_idx % len(_INACTIVITY_NUDGES)]
                nudge_idx += 1
                qt.express(expr); qt.gesture(gest); qt.say(msg); qt.reset_pose()
                inactivity_nudged = True
                last_activity = time.time()

            # completion within time -> one point, celebrate, then reset
            if state.is_complete and not round_scored and not timed_out:
                round_scored = True
                score += 1
                name = shape_cfg["title"].lower()
                _on_complete(qt, display, win)
                if timer_total > 0:
                    qt.say(f"You finished the {name} in time! That's one point! "
                           f"Your score is now {score}.")
                else:
                    qt.say(f"You built the whole {name}! That's one point! "
                           f"Your score is now {score}.")
                print(f"[Score] Completed '{shape_cfg['title']}': +1 point. "
                      f"Total score: {score}")
                qt.say("Goodbye for now, and great job, builders! See you next time!")
                reset_round()
    finally:
        if follower is not None:
            follower.stop()
        cap.release()
        cv2.destroyAllWindows()
        qt.cleanup()


# ============================================================
#  ENTRY POINT
# ============================================================
def main():
    p = argparse.ArgumentParser(
        description="Tangram Quest (Misty II, buzzer) - auto-detects house/sword board")
    p.add_argument("--misty-ip", default=None, help="Misty IP (or use --no-robot).")
    p.add_argument("--camera", type=int, default=1, help="Puzzle camera index (default 1).")
    p.add_argument("--no-robot", action="store_true", help="Run without Misty.")
    p.add_argument("--shape", choices=sorted(_NAME_TO_SHAPE_ID), default=None,
                   help="Force a puzzle and skip auto-detect (default: auto from the "
                        "board's shape marker).")
    p.add_argument("--show-camera", action="store_true", help="Show ArUco debug overlay.")
    p.add_argument("--llm-feedback", action="store_true",
                   help=f"Rephrase feedback via local Ollama ({OLLAMA_MODEL}).")
    p.add_argument("--touch-buzzer", action="store_true",
                   help="Also accept a tap on Misty as the buzzer.")
    p.add_argument("--calibrate", action="store_true",
                   help="Force calibration of each puzzle as it is first shown.")
    p.add_argument("--timer", type=float, default=-1.0,
                   help="Countdown seconds. -1 (default) = per-shape "
                        "(house 3 min, sword 4 min); 0 = off; >0 = same length "
                        "for every shape.")
    p.add_argument("--final-warning", type=float, default=20.0,
                   help="Seconds-remaining for Misty's last warning (default 20). "
                        "Whole-minute reminders are spoken automatically.")
    p.add_argument("--face-camera", type=int, default=0, help="Face-tracking camera index.")
    p.add_argument("--no-face-track", action="store_true", help="Disable head tracking.")
    p.add_argument("--misty-face-camera", action="store_true",
                   help="Use Misty's own camera for face tracking.")
    p.add_argument("--show-face-camera", action="store_true",
                   help="Show the face-tracking camera window.")
    args = p.parse_args()

    qt = DummyAgent() if args.no_robot else (
        MistyAgent(args.misty_ip) if args.misty_ip
        else p.error("--misty-ip is required (or use --no-robot)."))

    forced = _NAME_TO_SHAPE_ID[args.shape] if args.shape else None
    run_level(qt, camera_index=args.camera, show_camera=args.show_camera,
              llm_feedback=args.llm_feedback, touch_buzzer=args.touch_buzzer,
              face_camera=args.face_camera, face_tracking=not args.no_face_track,
              misty_face_camera=args.misty_face_camera,
              show_face_camera=args.show_face_camera,
              force_calibrate=args.calibrate,
              timer_seconds=args.timer, final_warning_seconds=args.final_warning,
              forced_shape_id=forced)


if __name__ == "__main__":
    main()
