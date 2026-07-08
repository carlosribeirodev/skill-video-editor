#!/usr/bin/env python3
"""Print a JSON summary (resolution, fps, duration, audio) of one or more videos.

Usage:
    python probe.py screen.mp4 [camera.mp4 ...]
"""

import json
import sys

from common import die, video_info


def main():
    paths = sys.argv[1:]
    if not paths:
        die("usage: probe.py <video> [<video> ...]")
    print(json.dumps([video_info(p) for p in paths], indent=2))


if __name__ == "__main__":
    main()
