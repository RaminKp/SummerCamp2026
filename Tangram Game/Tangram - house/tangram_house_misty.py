#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tangram Quest - HOUSE board (ages 9-12)  -  MISTY II edition
============================================================

This is the QTrobot/airplane game logic (ArUco perception, board homography,
batch buzzer feedback, Misty interface, head tracking) re-wired for the
PHYSICAL assets you actually printed:

    * House board ........ corner ArUco markers  1, 2, 3, 4   (DICT_4X4_50)
                           (ID1=top-left, ID2=top-right,
                            ID3=bottom-right, ID4=bottom-left)
    * 7 tangram pieces ... ArUco markers 20-26 stuck on each piece:
            20  light-blue SQUARE
            21  dark-blue  LARGE triangle
            22  purple     SMALL triangle
            23  green      SMALL triangle
            24  orange     MEDIUM triangle
            25  yellow     LARGE triangle
            26  red        PARALLELOGRAM

Game rules baked in (from your spec):
    * Children place as many pieces as they like, any order, then press the
      BUZZER (SPACE bar for now).  Misty looks at the whole board and gives ONE
      batch of feedback: which pieces are correct, which are in the right place
      but need a turn, and which are in the wrong spot.
    * Interchangeable pieces: the two LARGE triangles (dark-blue 21 / yellow 25)
      can swap slots, and the two SMALL triangles (purple 22 / green 23) can
      swap slots.
    * Optional countdown timer with a "one minute left" warning (this house
      board is the 9-12 level, so the timer is OFF by default; turn it on with
      --timer 120 for the younger 6-8 levels you add later).

WHY CALIBRATION (important)
---------------------------
Where each piece's marker should land on YOUR printed board depends on (a) your
exact print, (b) your camera mount, and (c) exactly how each sticker was placed
on each piece. Rather than hard-code coordinates that could silently miss, the
game learns the correct layout once:

    python3 tangram_house_misty.py --no-robot --camera 1 --calibrate

Assemble the house correctly under the camera, press C to capture, then (for
perfect rotation checking on the swappable triangles) swap the two large
triangles AND the two small triangles, press C again, then press S to save.
Targets are written to house_targets.json and loaded automatically next run.

Run
---
    # Real Misty
    python3 tangram_house_misty.py --misty-ip 192.168.1.50 --camera 1

    # No robot (vision + buzzer test, prints what Misty would do)
    python3 tangram_house_misty.py --no-robot --camera 1

    # Debug overlay of the camera feed
    python3 tangram_house_misty.py --no-robot --camera 1 --show-camera

SPACE = buzzer/check    H = hint    K = (re)calibrate    Q = quit

Ramin / Ayed - UNBC HRI study 2026
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

# Board corner markers (printed on the house board PDF).
BOARD_MARKER_IDS = [1, 2, 3, 4]

# Board coordinate frame == the actual US-Letter page rendered at 200 DPI
# (1 cm = 78.74 px). Corner-marker CENTERS measured from your printed board:
BOARD_MARKER_POSITIONS = {
    1: (196, 196),    # top-left
    2: (1503, 196),   # top-right
    3: (1503, 2003),  # bottom-right
    4: (196, 2003),   # bottom-left
}
PX_PER_CM = 78.74

# Exact house silhouette (board frame) extracted from your board PDF, for the
# on-screen reference drawing.
HOUSE_OUTLINE = [
    (544, 532), (544, 864), (210, 1198), (403, 1200), (403, 1667),
    (1344, 1667), (1344, 1200), (1489, 1198), (1016, 725), (881, 856), (881, 532),
]

# Tolerances (relaxed for children). Position is in board px; 1 cm = 78.74 px.
POSITION_TOLERANCE_PX  = 250    # ~3.2 cm
ROTATION_TOLERANCE_DEG = 22


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
        valid = set(PIECES) | set(BOARD_MARKER_IDS)
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
        return out


# ============================================================
#  BOARD REGISTRATION  (camera -> board homography)
# ============================================================

class BoardRegistration:
    """Homography from the 4 corner markers. Self-recovers when bumped;
    needs >=3 of the 4 corners visible."""

    def __init__(self):
        self._H: Optional[np.ndarray] = None
        self._Hinv: Optional[np.ndarray] = None

    def update(self, detections: Dict[int, Detection]) -> bool:
        active = {mid: detections[mid] for mid in BOARD_MARKER_IDS if mid in detections}
        if len(active) >= 3:
            src = np.array([[active[m].cx, active[m].cy] for m in sorted(active)],
                           dtype=np.float32)
            dst = np.array([list(BOARD_MARKER_POSITIONS[m]) for m in sorted(active)],
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
        # one short fact per newly-correct piece (capped)
        for p in newly_correct[:MAX_FACTS_PER_TURN]:
            seg.append(("happy", "point", PIECES[p]["fact"]))

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

    def __init__(self):
        self._celebration_frame = 0
        # precompute outline scaled to fit the drawing region
        xs = [p[0] for p in HOUSE_OUTLINE]
        ys = [p[1] for p in HOUSE_OUTLINE]
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
        cv2.putText(img, "Tangram Quest - Build the House!", (180, 42),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, _COL_TITLE, 2, cv2.LINE_AA)

        pts = np.array([self._to_disp(*p) for p in HOUSE_OUTLINE], np.int32)
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

    def render_calibration(self, board_ok: bool, n_captures: int,
                           captured: Dict[int, bool]) -> np.ndarray:
        img = np.full((_DISP_H, _DISP_W, 3), 235, dtype=np.uint8)
        cv2.putText(img, "CALIBRATION MODE", (250, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (40, 40, 200), 3, cv2.LINE_AA)
        lines = [
            "1. Solve the house correctly under the camera.",
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
        pts = np.array([self._to_disp(*p) for p in HOUSE_OUTLINE], np.int32)
        cv2.fillPoly(img, [pts], (225, 235, 225))
        cv2.polylines(img, [pts], True, (80, 160, 100), 4, cv2.LINE_AA)
        np.random.seed(7)
        for _ in range(14):
            cx = np.random.randint(40, _DISP_W - 40)
            cy = np.random.randint(40, _DISP_H - 40)
            r = np.random.randint(8, 20)
            a = 150 + int(50 * math.sin(self._celebration_frame * 0.08 + cx))
            cv2.circle(img, (cx, cy), r, (a, a, a), -1, cv2.LINE_AA)
        cv2.putText(img, "HOUSE COMPLETE!", (250, _DISP_H // 2),
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


def _on_complete(qt, display):
    qt.express("happy"); qt.gesture("celebrate"); time.sleep(0.3)
    qt.say("Incredible! You built the whole house! That was wonderful work!")
    qt.gesture("dance")
    if display is not None:
        for _ in range(120):
            cv2.imshow("Tangram Quest - House", display.render_celebration())
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
#  CALIBRATION FLOW
# ============================================================
def run_calibration(cap, detector, board_reg, display, model: TargetModel) -> bool:
    """Interactive calibration. Returns True if saved, False if aborted."""
    print("\n[Calib] Calibration mode. Solve the house, press C to capture, "
          "swap the swappable pairs, press C again, then S to save. Q aborts.")
    n_captures = 0
    win = "Tangram Quest - House"
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
                      f"{sorted(missing)}. Capture the full solved house first.")
                continue
            model.save()
            return True


# ============================================================
#  MAIN GAME LOOP
# ============================================================
def run_level(qt, camera_index=1, show_camera=False, llm_feedback=False,
              touch_buzzer=False, face_camera=0, face_tracking=True,
              misty_face_camera=False, show_face_camera=False,
              force_calibrate=False, timer_seconds=0.0, timer_warning=60.0):
    detector = PieceDetector()
    display = TargetDisplay()
    display._timer_total = timer_seconds if timer_seconds > 0 else 120.0
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

    win = "Tangram Quest - House"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)

    # ---- targets: load or calibrate ----
    model = TargetModel.load()
    if force_calibrate or model is None or not model.is_ready:
        if model is None or not model.is_ready:
            print("[Calib] No usable targets found - entering calibration.")
        model = TargetModel()
        if not run_calibration(cap, detector, board_reg, display, model):
            print("[Game] Calibration not completed; exiting.")
            cap.release(); cv2.destroyAllWindows(); qt.cleanup()
            return

    state = GameState()

    # ---- face tracking ----
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

    print("\n[Game] *** CLICK THE GAME WINDOW so it has keyboard focus ***")
    print("[Game] SPACE = check | H = hint | K = recalibrate | Q = quit\n")

    welcomed = False
    game_start_time = None
    warned = False
    timed_out = False
    last_press = last_hint = 0.0
    last_activity = time.time()
    inactivity_nudged = False
    nudge_idx = 0
    BUZZER_COOLDOWN, HINT_COOLDOWN = 0.8, 3.0

    try:
        while not state.is_complete:
            ret, frame = cap.read()
            if not ret:
                continue
            detections = detector.detect(frame)
            board_reg.update(detections)

            # welcome on first registration
            if board_reg.is_valid and not welcomed:
                welcomed = True
                game_start_time = time.time()
                qt.express("happy")
                qt.say_with_gesture(
                    "Hello friends! Welcome to Tangram Quest! Let's build the house "
                    "together!", "wave")
                time.sleep(0.1)
                qt.say_with_gesture(
                    f"Place the seven pieces inside the outline, then {button_word} "
                    "and I'll check your work!", "point")
                qt.reset_pose()
                last_activity = time.time()

            # timer
            time_left = None
            if timer_seconds > 0 and game_start_time is not None:
                elapsed = time.time() - game_start_time
                time_left = timer_seconds - elapsed
                if (not warned) and time_left <= timer_warning:
                    warned = True
                    qt.express("surprise")
                    qt.say_with_gesture("One minute left! You can do it!", "excited")
                    qt.reset_pose()
                if (not timed_out) and time_left <= 0:
                    timed_out = True
                    time_left = 0
                    qt.express("neutral")
                    qt.say_with_gesture("Time's up! Great effort, everyone! Let's see "
                                        "how you did.", "nod")
                    qt.reset_pose()

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
                # recalibrate on demand
                model = TargetModel()
                if run_calibration(cap, detector, board_reg, display, model):
                    state.placed.clear()
                    print("[Game] Recalibrated. Targets reloaded.")
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

        if state.is_complete:
            _on_complete(qt, display)
            qt.say("Goodbye for now, and great job, builders! See you next time!")
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
    p = argparse.ArgumentParser(description="Tangram Quest - House (Misty II, buzzer)")
    p.add_argument("--misty-ip", default=None, help="Misty IP (or use --no-robot).")
    p.add_argument("--camera", type=int, default=1, help="Puzzle camera index (default 1).")
    p.add_argument("--no-robot", action="store_true", help="Run without Misty.")
    p.add_argument("--show-camera", action="store_true", help="Show ArUco debug overlay.")
    p.add_argument("--llm-feedback", action="store_true",
                   help=f"Rephrase feedback via local Ollama ({OLLAMA_MODEL}).")
    p.add_argument("--touch-buzzer", action="store_true",
                   help="Also accept a tap on Misty as the buzzer.")
    p.add_argument("--calibrate", action="store_true",
                   help="Force calibration even if house_targets.json exists.")
    p.add_argument("--timer", type=float, default=0.0,
                   help="Countdown seconds (0=off; house is 9-12, default off). "
                        "Use 120 for the 6-8 levels.")
    p.add_argument("--timer-warning", type=float, default=60.0,
                   help="Seconds-remaining at which Misty warns (default 60).")
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

    run_level(qt, camera_index=args.camera, show_camera=args.show_camera,
              llm_feedback=args.llm_feedback, touch_buzzer=args.touch_buzzer,
              face_camera=args.face_camera, face_tracking=not args.no_face_track,
              misty_face_camera=args.misty_face_camera,
              show_face_camera=args.show_face_camera,
              force_calibrate=args.calibrate,
              timer_seconds=args.timer, timer_warning=args.timer_warning)


if __name__ == "__main__":
    main()
