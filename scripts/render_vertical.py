#!/usr/bin/env python3
"""Reframe a 16:9 screencast into a 9:16 (portrait) video using a crop plan.

The crop plan is a JSON file with keyframes marking which region of the source
is relevant at each moment. Between keyframes the virtual camera holds still;
at each keyframe it glides to the new region with an eased pan/zoom animation.
Every region is expanded to the output aspect ratio (minimum cover), so the
portrait frame is always fully filled — never letterboxed.

Crop plan format (coordinates in SOURCE pixels; regions do not need to match
the output aspect, the renderer expands them):

    {
      "keyframes": [
        {"time": 0.0,  "region": [640, 120, 800, 700], "label": "editor",
         "anchor": "left"},
        {"time": 22.0, "region": [0, 560, 900, 500],   "label": "terminal"}
      ]
    }

The optional "anchor" (left/right/top/bottom, default center) says which side
of the region to keep visible when the final crop is narrower or shorter than
the marked region — e.g. "left" keeps the start of code lines on screen.

Usage:
    python render_vertical.py screen.mp4 --plan plan.json --out vertical.mp4
"""

import argparse
import json
import math
import subprocess
import sys

import cv2
import numpy as np

from common import ENCODER_CHOICES, check_binaries, die, even, select_encoder, \
    video_info


def ease_in_out(p: float) -> float:
    """Smootherstep easing: gentle start and stop for the camera glide."""
    p = min(1.0, max(0.0, p))
    return p * p * p * (p * (p * 6 - 15) + 10)


def cover_region(region, src_w, src_h, aspect, anchor="center"):
    """Expand a region to the output aspect (minimum cover) and clamp it
    inside the source frame. Returns (cx, cy, w) — height is w / aspect.

    When the resulting crop cannot contain the whole marked region (e.g. a
    wide code block in a tall 9:16 crop), `anchor` picks the side that stays
    visible instead of cutting both edges around the center."""
    x, y, w0, h0 = region
    if w0 <= 0 or h0 <= 0:
        die(f"invalid region {region}: width/height must be positive")
    w, h = float(w0), float(h0)
    if w / h < aspect:
        w = h * aspect
    h = w / aspect
    if w > src_w:
        w, h = src_w, src_w / aspect
    if h > src_h:
        h, w = src_h, src_h * aspect
    if w < w0 and anchor == "left":
        cx = x + w / 2.0
    elif w < w0 and anchor == "right":
        cx = x + w0 - w / 2.0
    else:
        cx = x + w0 / 2.0
    if h < h0 and anchor == "top":
        cy = y + h / 2.0
    elif h < h0 and anchor == "bottom":
        cy = y + h0 - h / 2.0
    else:
        cy = y + h0 / 2.0
    cx = min(max(cx, w / 2.0), src_w - w / 2.0)
    cy = min(max(cy, h / 2.0), src_h - h / 2.0)
    return cx, cy, w


class CropTrack:
    """Piecewise camera path: hold on each keyframe region, eased transition
    starting at each keyframe's timestamp."""

    def __init__(self, keyframes, transition, src_w, src_h, aspect):
        if not keyframes:
            die("crop plan has no keyframes")
        kfs = sorted(keyframes, key=lambda k: k["time"])
        self.times = [float(k["time"]) for k in kfs]
        self.regions = [cover_region(k["region"], src_w, src_h, aspect,
                                     k.get("anchor", "center"))
                        for k in kfs]
        self.transition = max(0.0, transition)
        self.aspect = aspect

    def region_at(self, t):
        times, regions = self.times, self.regions
        if t <= times[0]:
            return regions[0]
        i = 0
        for j, kt in enumerate(times):
            if kt <= t:
                i = j
        if i == 0:
            return regions[0]
        duration = self.transition
        if i + 1 < len(times):  # never overrun the next keyframe
            duration = min(duration, times[i + 1] - times[i])
        if duration <= 0 or t >= times[i] + duration:
            return regions[i]
        p = ease_in_out((t - times[i]) / duration)
        cx0, cy0, w0 = regions[i - 1]
        cx1, cy1, w1 = regions[i]
        # Interpolate zoom in log space so it feels linear to the eye.
        w = w0 * math.exp(p * math.log(w1 / w0)) if w0 != w1 else w0
        return cx0 + (cx1 - cx0) * p, cy0 + (cy1 - cy0) * p, w


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video", help="source (landscape) video")
    parser.add_argument("--plan", required=True, help="crop plan JSON")
    parser.add_argument("--out", required=True, help="output video path")
    parser.add_argument("--width", type=int, default=1080)
    parser.add_argument("--height", type=int, default=1920)
    parser.add_argument("--transition", type=float, default=0.8,
                        help="pan/zoom animation length in seconds (default 0.8)")
    parser.add_argument("--crf", type=int, default=19, help="x264 quality (default 19)")
    parser.add_argument("--preset", default="medium", help="x264 preset (default medium)")
    parser.add_argument("--encoder", choices=ENCODER_CHOICES, default="cpu",
                        help="video encoder: cpu (libx264, default), amd (AMF/VAAPI), "
                             "nvidia (NVENC), intel (QSV/VAAPI) or auto; GPU choices "
                             "fall back to cpu when unavailable")
    parser.add_argument("--no-audio", action="store_true",
                        help="do not carry the source audio over")
    args = parser.parse_args()

    check_binaries()
    info = video_info(args.video)
    if not info["video"]:
        die(f"no video stream in {args.video}")
    src_w, src_h = info["video"]["width"], info["video"]["height"]
    fps = info["video"]["fps"] or 30.0
    out_w, out_h = even(args.width), even(args.height)

    plan = json.loads(open(args.plan).read())
    track = CropTrack(plan["keyframes"], plan.get("transition", args.transition),
                      src_w, src_h, out_w / out_h)

    capture = cv2.VideoCapture(args.video)
    if not capture.isOpened():
        die(f"could not open {args.video}")

    enc = select_encoder(args.encoder, args.crf, args.preset)
    encode = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        *enc["global_args"],
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{out_w}x{out_h}",
        "-r", f"{fps}", "-i", "pipe:0",
    ]
    if not args.no_audio and info["audio"]:
        encode += ["-i", args.video, "-map", "0:v", "-map", "1:a:0",
                   "-c:a", "aac", "-b:a", "192k"]
    if enc["vf"]:
        encode += ["-vf", enc["vf"]]
    encode += [
        *enc["codec_args"], "-movflags", "+faststart", "-shortest", args.out,
    ]
    encoder = subprocess.Popen(encode, stdin=subprocess.PIPE)

    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    n = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            cx, cy, w = track.region_at(n / fps)
            scale = out_w / w
            matrix = np.float32([[scale, 0, out_w / 2.0 - scale * cx],
                                 [0, scale, out_h / 2.0 - scale * cy]])
            out = cv2.warpAffine(frame, matrix, (out_w, out_h),
                                 flags=cv2.INTER_LINEAR)
            encoder.stdin.write(out.tobytes())
            n += 1
            if n % 300 == 0:
                pct = f" ({100 * n // total}%)" if total else ""
                print(f"  rendered {n} frames{pct}", file=sys.stderr)
    finally:
        capture.release()
        encoder.stdin.close()
        encoder.wait()
    if encoder.returncode != 0:
        die("ffmpeg encoder failed")
    print(f"done: {args.out} ({n} frames, {out_w}x{out_h}, encoder {enc['codec']})")


if __name__ == "__main__":
    main()
