#!/usr/bin/env python3
"""Estimate the sync offset between two recordings by cross-correlating their
audio tracks (e.g. the screen capture and the camera, both picking up the
same voice/room audio).

Prints a JSON result. `offset` is the value to pass as --offset to
compose_camera.py / mix_audio.py: positive means the camera started recording
BEFORE the screen capture (that much of the camera's start gets skipped).

Usage:
    python sync_offset.py screen.mp4 camera.mp4 [--window 300]
"""

import argparse
import json
import subprocess

import numpy as np

from common import check_binaries, die, video_info

SAMPLE_RATE = 8000
ENV_RATE = 200  # envelope sample rate; offset resolution = 5 ms


def read_audio(path: str, window: float) -> np.ndarray:
    cmd = [
        "ffmpeg", "-v", "error", "-i", path, "-t", str(window),
        "-map", "0:a:0", "-ac", "1", "-ar", str(SAMPLE_RATE),
        "-f", "f32le", "pipe:1",
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        die(f"could not decode audio from {path}:\n{proc.stderr.decode()[-500:]}")
    return np.frombuffer(proc.stdout, dtype=np.float32)


def envelope(samples: np.ndarray) -> np.ndarray:
    """Loudness envelope at ENV_RATE Hz, zero-mean."""
    hop = SAMPLE_RATE // ENV_RATE
    n = len(samples) // hop
    if n == 0:
        die("audio track is too short to correlate")
    env = np.abs(samples[: n * hop]).reshape(n, hop).mean(axis=1)
    env -= env.mean()
    return env


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("base", help="reference video (screen recording)")
    parser.add_argument("camera", help="video to align against the reference")
    parser.add_argument("--window", type=float, default=300,
                        help="how many seconds of audio to analyze (default 300)")
    args = parser.parse_args()

    check_binaries()
    for path in (args.base, args.camera):
        if not video_info(path)["audio"]:
            die(f"{path} has no audio track; measure the offset manually")

    base = envelope(read_audio(args.base, args.window))
    cam = envelope(read_audio(args.camera, args.window))

    nfft = 1 << (len(base) + len(cam) - 1).bit_length()
    corr = np.fft.irfft(np.fft.rfft(base, nfft) * np.conj(np.fft.rfft(cam, nfft)),
                        nfft)
    # corr[k] = sum base[n] * cam[n - k]; negative lags wrap to the end.
    lags = np.concatenate([np.arange(len(base)), np.arange(-len(cam) + 1, 0)])
    valid = np.concatenate([corr[: len(base)], corr[nfft - len(cam) + 1:]])

    k = int(np.argmax(valid))
    # base[n] = cam[n - lag]  =>  camera started -lag/ENV_RATE before the base.
    offset = -lags[k] / ENV_RATE

    norm = np.linalg.norm(base) * np.linalg.norm(cam)
    confidence = float(valid[k] / norm) if norm else 0.0

    print(json.dumps({
        "offset": round(float(offset), 3),
        "confidence": round(confidence, 3),
        "note": "positive offset = camera started earlier; pass it as --offset "
                "to compose_camera.py and mix_audio.py",
    }, indent=2))
    if confidence < 0.2:
        print("warning: low confidence — the tracks may not share common audio; "
              "verify the offset manually", flush=True)


if __name__ == "__main__":
    main()
