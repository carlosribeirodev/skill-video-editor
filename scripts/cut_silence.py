#!/usr/bin/env python3
"""Remove silences/pauses from a video by cutting out the quiet stretches.

Detects silence in the audio track (ffmpeg silencedetect), keeps a small
padding around the speech so words are not clipped, and re-encodes the kept
segments into a single continuous video.

Run with --analyze-only first: it prints what would be removed (JSON) without
touching the video, so the cut can be reviewed before it happens.

Usage:
    python cut_silence.py final.mp4 --out final_cut.mp4 \
        [--threshold -35] [--min-silence 0.8] [--pad 0.15] [--analyze-only]
"""

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path

from common import check_binaries, die, run, video_info

MIN_KEEP = 0.10  # segments shorter than this are noise, drop them


def detect_silences(path: str, threshold: float, min_silence: float) -> list:
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", path, "-map", "0:a:0",
         "-af", f"silencedetect=noise={threshold}dB:d={min_silence}",
         "-f", "null", "-"],
        capture_output=True, text=True)
    if proc.returncode != 0:
        die(f"silence detection failed:\n{proc.stderr[-500:]}")
    silences, start = [], None
    for line in proc.stderr.splitlines():
        m = re.search(r"silence_start:\s*(-?[\d.]+)", line)
        if m:
            start = float(m.group(1))
        m = re.search(r"silence_end:\s*(-?[\d.]+)", line)
        if m and start is not None:
            silences.append((max(0.0, start), float(m.group(1))))
            start = None
    return silences


def keep_segments(silences: list, duration: float, pad: float) -> list:
    """Complement of the silences, with `pad` seconds of breathing room kept
    on each side of the speech."""
    keeps, cursor = [], 0.0
    for s, e in silences:
        if e - s <= 2 * pad:  # too short to cut once padding is kept
            continue
        end = min(s + pad, duration)
        if end - cursor > MIN_KEEP:
            keeps.append((cursor, end))
        cursor = max(e - pad, end)
    if duration - cursor > MIN_KEEP:
        keeps.append((cursor, duration))
    return keeps


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video")
    parser.add_argument("--out", help="output path (required unless --analyze-only)")
    parser.add_argument("--threshold", type=float, default=-35,
                        help="volume below this (dBFS) counts as silence (default -35)")
    parser.add_argument("--min-silence", type=float, default=0.8,
                        help="only cut pauses at least this long, in seconds (default 0.8)")
    parser.add_argument("--pad", type=float, default=0.15,
                        help="seconds of silence kept around speech so words "
                             "are not clipped (default 0.15)")
    parser.add_argument("--analyze-only", action="store_true",
                        help="just print the detected pauses and totals as JSON")
    parser.add_argument("--crf", type=int, default=19)
    parser.add_argument("--preset", default="medium")
    args = parser.parse_args()

    check_binaries()
    info = video_info(args.video)
    if not info["video"]:
        die(f"no video stream in {args.video}")
    if not info["audio"]:
        die(f"{args.video} has no audio track — silence removal needs audio")
    duration = info["duration"]

    silences = detect_silences(args.video, args.threshold, args.min_silence)
    keeps = keep_segments(silences, duration, args.pad)
    kept = sum(e - s for s, e in keeps)

    report = {
        "duration": round(duration, 2),
        "output_duration": round(kept, 2),
        "removed": round(duration - kept, 2),
        "cuts": max(0, len(keeps) - 1),
        "pauses": [{"start": round(s, 2), "end": round(e, 2)} for s, e in silences],
    }
    print(json.dumps(report, indent=2))

    if args.analyze_only:
        return
    if not args.out:
        die("--out is required (or use --analyze-only)")
    if not keeps:
        die("nothing would be kept — raise --threshold or check the audio")
    if not silences or duration - kept < 0.5:
        print("note: less than 0.5s of pauses found; copying the video unchanged")
        run(["ffmpeg", "-y", "-v", "error", "-i", args.video, "-c", "copy",
             "-movflags", "+faststart", args.out])
        return

    parts, labels = [], []
    for i, (s, e) in enumerate(keeps):
        parts.append(
            f"[0:v]trim=start={s:.4f}:end={e:.4f},setpts=PTS-STARTPTS[v{i}];"
            f"[0:a]atrim=start={s:.4f}:end={e:.4f},asetpts=PTS-STARTPTS[a{i}];")
        labels.append(f"[v{i}][a{i}]")
    graph = "".join(parts) + \
        f"{''.join(labels)}concat=n={len(keeps)}:v=1:a=1[v][a]"

    # The graph can exceed the command-line limit on long videos; use a file.
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(graph)
        script = f.name
    try:
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-i", args.video, "-filter_complex_script", script,
             "-map", "[v]", "-map", "[a]",
             "-c:v", "libx264", "-preset", args.preset, "-crf", str(args.crf),
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
             "-movflags", "+faststart", args.out])
    finally:
        Path(script).unlink(missing_ok=True)
    print(f"done: {args.out} ({report['duration']}s -> {report['output_duration']}s, "
          f"{report['cuts']} cuts)")


if __name__ == "__main__":
    main()
