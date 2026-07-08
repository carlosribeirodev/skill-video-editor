#!/usr/bin/env python3
"""Extract screenshots from a video at a fixed interval, for visual analysis.

Writes numbered JPEGs plus a manifest.json mapping each file to its timestamp.

Usage:
    python extract_frames.py screen.mp4 --out frames/ [--interval 5] [--width 1024]
"""

import argparse
import json
import re
from pathlib import Path

from common import check_binaries, die, run, video_info


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video")
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument("--interval", type=float, default=5.0,
                        help="seconds between screenshots (default 5)")
    parser.add_argument("--width", type=int, default=1024,
                        help="downscale screenshots to this width (default 1024; "
                             "0 keeps the original size)")
    parser.add_argument("--quality", type=int, default=4,
                        help="JPEG quality, 2 (best) to 31 (default 4)")
    args = parser.parse_args()

    check_binaries()
    info = video_info(args.video)
    if not info["video"]:
        die(f"no video stream in {args.video}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("frame_*.jpg"):
        old.unlink()

    filters = [f"fps=1/{args.interval}"]
    if args.width and args.width < info["video"]["width"]:
        filters.append(f"scale={args.width}:-2")
    run([
        "ffmpeg", "-y", "-i", args.video,
        "-vf", ",".join(filters),
        "-q:v", str(args.quality), "-start_number", "0",
        str(out_dir / "frame_%05d.jpg"),
    ])

    frames = []
    for path in sorted(out_dir.glob("frame_*.jpg")):
        index = int(re.search(r"(\d+)", path.stem).group(1))
        frames.append({"file": path.name, "time": round(index * args.interval, 3)})

    manifest = {
        "video": args.video,
        "interval": args.interval,
        "source_width": info["video"]["width"],
        "source_height": info["video"]["height"],
        "screenshot_width": args.width or info["video"]["width"],
        "duration": info["duration"],
        "frames": frames,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
