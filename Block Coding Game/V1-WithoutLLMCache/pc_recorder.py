"""
pc_recorder.py — Webcam+mic recorder server. RUNS ON THE LINUX PC, not the Pi.

Records with ffmpeg (video + audio) instead of OpenCV (video only).
The Pi sends segment commands over the hotspot network; each segment is
one .mp4 file with sound.

Endpoints (plain GET):
    /start?session_id=<id>  — close current segment, start a new file
    /stop                   — close current segment (recording pauses)
    /status                 — current segment name or "idle"

Run on the Linux PC (needs: sudo apt install ffmpeg):
    python3 pc_recorder.py

Recordings are saved to a `recordings/` folder next to this file.
"""

from __future__ import annotations

import signal
import subprocess
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# ── Config ────────────────────────────────────────────────────────────────────

RECORDINGS_DIR = Path(__file__).parent / "recordings"
VIDEO_DEVICE   = "/dev/video0"
FPS            = 20
RESOLUTION     = "1280x720"
PORT           = 8765

# Microphone input. "pulse"+"default" works on PulseAudio/PipeWire desktops.
# If audio fails, the recorder automatically falls back to video-only.
AUDIO_ARGS = ["-f", "pulse", "-i", "default"]


# ── ffmpeg segment management ─────────────────────────────────────────────────

class FfmpegRecorder:
    def __init__(self):
        RECORDINGS_DIR.mkdir(exist_ok=True)
        self._proc: subprocess.Popen | None = None
        self._segment_name = "idle"
        self._lock = threading.Lock()

    def _build_cmd(self, path: Path, with_audio: bool) -> list[str]:
        cmd = ["ffmpeg", "-y",
               "-f", "v4l2", "-framerate", str(FPS),
               "-video_size", RESOLUTION, "-i", VIDEO_DEVICE]
        if with_audio:
            cmd += AUDIO_ARGS
        cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "23"]
        if with_audio:
            cmd += ["-c:a", "aac"]
        cmd += [str(path)]
        return cmd

    def _spawn(self, path: Path) -> subprocess.Popen | None:
        """Start ffmpeg with audio; fall back to video-only if it dies fast."""
        for with_audio in (True, False):
            proc = subprocess.Popen(
                self._build_cmd(path, with_audio),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(1.5)
            if proc.poll() is None:
                if not with_audio:
                    print("[recorder] WARNING: mic capture failed — video only.")
                return proc
        print("[recorder] ERROR: ffmpeg could not start. Is the webcam free?")
        return None

    def _kill_current(self):
        if self._proc and self._proc.poll() is None:
            # SIGINT lets ffmpeg finalize the file cleanly
            self._proc.send_signal(signal.SIGINT)
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None

    def start_segment(self, session_id: str):
        safe_id = session_id.replace(":", "-").replace("/", "-")
        path = RECORDINGS_DIR / f"{safe_id}.mp4"
        with self._lock:
            self._kill_current()
            self._proc = self._spawn(path)
            self._segment_name = safe_id if self._proc else "idle"
        if self._proc:
            print(f"[recorder] ▶ segment started: {path.name}")

    def stop_segment(self):
        with self._lock:
            self._kill_current()
            self._segment_name = "idle"
        print("[recorder] ■ segment stopped (not recording)")

    def status(self) -> str:
        with self._lock:
            if self._proc and self._proc.poll() is None:
                return self._segment_name
            return "idle"


_recorder = FfmpegRecorder()


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
    try:
        ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        _recorder.stop_segment()
        print("\n[recorder] Stopped.")
