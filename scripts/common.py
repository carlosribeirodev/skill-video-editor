"""Shared helpers for the video-editor skill scripts."""

import json
import shutil
import subprocess
import sys


def die(msg: str, code: int = 1):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def check_binaries():
    for binary in ("ffmpeg", "ffprobe"):
        if shutil.which(binary) is None:
            die(f"'{binary}' not found on PATH. Install FFmpeg first (see README).")


def run(cmd: list[str], quiet: bool = True) -> subprocess.CompletedProcess:
    """Run a command, raising with the captured stderr on failure."""
    proc = subprocess.run(cmd, capture_output=quiet, text=True)
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        tail = "\n".join(stderr.splitlines()[-15:])
        die(f"command failed: {' '.join(cmd)}\n{tail}")
    return proc


def ffprobe_json(path: str) -> dict:
    check_binaries()
    proc = run([
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", path,
    ])
    return json.loads(proc.stdout)


def parse_rate(rate: str) -> float:
    """Parse an ffprobe rate like '30000/1001' into a float."""
    if not rate or rate == "0/0":
        return 0.0
    if "/" in rate:
        num, den = rate.split("/")
        return float(num) / float(den) if float(den) else 0.0
    return float(rate)


def video_info(path: str) -> dict:
    """Summarize the streams of a media file."""
    data = ffprobe_json(path)
    info = {
        "path": path,
        "duration": float(data.get("format", {}).get("duration", 0) or 0),
        "video": None,
        "audio": None,
    }
    for stream in data.get("streams", []):
        if stream["codec_type"] == "video" and info["video"] is None:
            fps = parse_rate(stream.get("avg_frame_rate") or "") or parse_rate(
                stream.get("r_frame_rate") or "")
            info["video"] = {
                "width": stream["width"],
                "height": stream["height"],
                "fps": round(fps, 3),
                "codec": stream.get("codec_name"),
            }
        elif stream["codec_type"] == "audio" and info["audio"] is None:
            info["audio"] = {
                "codec": stream.get("codec_name"),
                "sample_rate": int(stream.get("sample_rate", 0) or 0),
                "channels": stream.get("channels"),
            }
    return info


def even(value: float) -> int:
    """Round to the nearest even integer (required by yuv420p encoders)."""
    return max(2, int(round(value / 2)) * 2)
