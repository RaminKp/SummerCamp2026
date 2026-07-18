"""
pc_recorder.py — Webcam recorder server. RUNS ON THE PC, not the Pi.

The webcam is plugged into the PC; the game runs on the Pi. The Pi sends
segment commands over the hotspot network and this server records
continuously, switching output files with no gap between segments.

Endpoints (plain GET):
    /start?session_id=<id>  — close current segment, start a new file
    /stop                   — close current segment (recording pauses)
    /status                 — current segment name or "idle"

Run on the PC (needs: pip install opencv-python):
    python pc_recorder.py

Recordings are saved to a `recordings/` folder next to this file.
Windows Firewall will ask to allow Python on first run — allow it,
otherwise the Pi cannot reach this server.
"""

import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import cv2

# ── Config ────────────────────────────────────────────────────────────────────

RECORDINGS_DIR = Path(__file__).parent / "recordings"
WEBCAM_INDEX   = 0
FPS            = 20.0
RESOLUTION     = (1280, 720)
PORT           = 8765


# ── Continuous capture with swappable writers ────────────────────────────────

class SegmentedRecorder:
    """Holds the webcam open permanently; segments switch by swapping the
    VideoWriter, so there is never a gap or a camera re-open delay."""

    def __init__(self):
        RECORDINGS_DIR.mkdir(exist_ok=True)
        self._writer: cv2.VideoWriter | None = None
        self._segment_name = "idle"
        self._lock = threading.Lock()
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def start_segment(self, session_id: str):
        safe_id = session_id.replace(":", "-").replace("/", "-")
        path = RECORDINGS_DIR / f"{safe_id}.avi"
        fourcc = cv2.VideoWriter_fourcc(*"XVID")
        new_writer = cv2.VideoWriter(str(path), fourcc, FPS, RESOLUTION)
        with self._lock:
            if self._writer:
                self._writer.release()
            self._writer = new_writer
            self._segment_name = safe_id
        print(f"[recorder] ▶ segment started: {path.name}")

    def stop_segment(self):
        with self._lock:
            if self._writer:
                self._writer.release()
                self._writer = None
            self._segment_name = "idle"
        print("[recorder] ■ segment stopped (not recording)")

    def status(self) -> str:
        with self._lock:
            return self._segment_name if self._writer else "idle"

    def _loop(self):
        cap = cv2.VideoCapture(WEBCAM_INDEX)
        if not cap.isOpened():
            print(f"[recorder] ERROR: webcam {WEBCAM_INDEX} not found.")
            return
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  RESOLUTION[0])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, RESOLUTION[1])
        print(f"[recorder] Webcam {WEBCAM_INDEX} open at {RESOLUTION[0]}x{RESOLUTION[1]}.")

        frame_time = 1.0 / FPS
        while self._running:
            t0 = time.time()
            ret, frame = cap.read()
            if ret:
                if frame.shape[1] != RESOLUTION[0] or frame.shape[0] != RESOLUTION[1]:
                    frame = cv2.resize(frame, RESOLUTION)
                with self._lock:
                    if self._writer:
                        self._writer.write(frame)
            sleep = frame_time - (time.time() - t0)
            if sleep > 0:
                time.sleep(sleep)

        with self._lock:
            if self._writer:
                self._writer.release()
        cap.release()


_recorder = SegmentedRecorder()


# ── HTTP interface ────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/start":
            qs = parse_qs(parsed.query)
            session_id = (qs.get("session_id") or
                          [f"idle_{datetime.now().strftime('%Y%m%dT%H%M%S')}"])[0]
            _recorder.start_segment(session_id)
            body = f"recording:{session_id}"
        elif parsed.path == "/stop":
            _recorder.stop_segment()
            body = "stopped"
        elif parsed.path == "/status":
            body = _recorder.status()
        else:
            self.send_response(404)
            self.end_headers()
            return
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        pass  # keep the console quiet — segment prints are enough


if __name__ == "__main__":
    print(f"[recorder] Listening on port {PORT}. Waiting for commands from the Pi...")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
