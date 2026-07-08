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


# ---------------------------------------------------------------------------
# Video encoder selection (CPU by default, GPU opt-in via --encoder)

VAAPI_DEVICE = "/dev/dri/renderD128"

# Friendly name -> H.264 encoder candidates, tried in order. Availability is
# what really picks between them (AMF only exists on Windows builds, VAAPI
# only works on Linux), so the lists can be OS-agnostic.
ENCODER_CANDIDATES = {
    "cpu": ["libx264"],
    "amd": ["h264_amf", "h264_vaapi"],
    "nvidia": ["h264_nvenc"],
    "intel": ["h264_qsv", "h264_vaapi"],
    "auto": ["h264_amf", "h264_nvenc", "h264_qsv", "h264_vaapi"],
}
ENCODER_CHOICES = tuple(ENCODER_CANDIDATES)

_available_cache: set | None = None


def available_encoders() -> set:
    """Names of the video encoders compiled into this ffmpeg build."""
    global _available_cache
    if _available_cache is None:
        proc = run(["ffmpeg", "-hide_banner", "-encoders"])
        _available_cache = {
            line.split()[1]
            for line in proc.stdout.splitlines()
            if line.strip().startswith("V") and len(line.split()) > 1
        }
    return _available_cache


def probe_encoder(codec: str) -> bool:
    """Encode a couple of test frames: being listed in the build does not
    mean the driver/hardware actually works."""
    cmd = ["ffmpeg", "-hide_banner", "-v", "error"]
    if codec == "h264_vaapi":
        cmd += ["-vaapi_device", VAAPI_DEVICE]
    cmd += ["-f", "lavfi", "-i", "color=c=black:s=320x240:d=0.2:r=10"]
    if codec == "h264_vaapi":
        cmd += ["-vf", "format=nv12,hwupload"]
    cmd += ["-frames:v", "2", "-c:v", codec, "-f", "null", "-"]
    return subprocess.run(cmd, capture_output=True).returncode == 0


def encoder_args(codec: str, crf: int, preset: str) -> dict:
    """ffmpeg argument fragments for one concrete encoder.

    Returns {global_args, vf, codec_args}: global_args go before the inputs,
    vf is a filter suffix the caller must append to its video chain (only
    VAAPI needs one, to upload frames to the GPU), codec_args replace the
    usual -c:v block."""
    if codec == "h264_vaapi":
        return {
            "global_args": ["-vaapi_device", VAAPI_DEVICE],
            "vf": "format=nv12,hwupload",
            "codec_args": ["-c:v", "h264_vaapi", "-qp", str(crf)],
        }
    if codec == "h264_amf":
        return {
            "global_args": [], "vf": None,
            "codec_args": ["-c:v", "h264_amf", "-quality", "balanced",
                           "-rc", "cqp", "-qp_i", str(crf), "-qp_p", str(crf),
                           "-pix_fmt", "yuv420p"],
        }
    if codec == "h264_nvenc":
        return {
            "global_args": [], "vf": None,
            "codec_args": ["-c:v", "h264_nvenc", "-preset", "p5",
                           "-cq", str(crf), "-pix_fmt", "yuv420p"],
        }
    if codec == "h264_qsv":
        return {
            "global_args": [], "vf": None,
            "codec_args": ["-c:v", "h264_qsv", "-global_quality", str(crf),
                           "-pix_fmt", "nv12"],
        }
    return {
        "global_args": [], "vf": None,
        "codec_args": ["-c:v", "libx264", "-preset", preset,
                       "-crf", str(crf), "-pix_fmt", "yuv420p"],
    }


def select_encoder(name: str, crf: int, preset: str) -> dict:
    """Resolve a friendly encoder name (--encoder value) to working ffmpeg
    args, falling back to libx264 with a warning when no GPU encoder is
    usable."""
    check_binaries()
    codec = "libx264"
    if name != "cpu":
        for candidate in ENCODER_CANDIDATES.get(name, []):
            if candidate in available_encoders() and probe_encoder(candidate):
                codec = candidate
                break
        else:
            if name != "auto":
                print(f"warning: no working '{name}' GPU encoder found "
                      f"(tried {', '.join(ENCODER_CANDIDATES[name])}); "
                      "falling back to CPU (libx264)", file=sys.stderr)
    settings = encoder_args(codec, crf, preset)
    settings["codec"] = codec
    return settings
