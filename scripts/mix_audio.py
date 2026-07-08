#!/usr/bin/env python3
"""Set the audio of a video: mix the base track with the camera microphone,
or replace it with one of the two. The video stream is copied, not re-encoded.

Usage:
    python mix_audio.py composed.mp4 camera.mp4 --out final.mp4 \
        [--mode mix|camera|base] [--offset 0] [--base-vol 1.0] [--cam-vol 1.0]
"""

import argparse

from common import check_binaries, die, run, video_info


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("base", help="video whose picture (and base audio) to use")
    parser.add_argument("camera", help="video/file providing the second audio track")
    parser.add_argument("--out", required=True)
    parser.add_argument("--mode", choices=("mix", "camera", "base"), default="mix")
    parser.add_argument("--offset", type=float, default=0.0,
                        help="camera sync offset in seconds: positive skips the start "
                             "of the camera audio, negative delays it")
    parser.add_argument("--base-vol", type=float, default=1.0)
    parser.add_argument("--cam-vol", type=float, default=1.0)
    args = parser.parse_args()

    check_binaries()
    base_info = video_info(args.base)
    cam_info = video_info(args.camera)

    mode = args.mode
    if mode in ("mix", "base") and not base_info["audio"]:
        print("note: base video has no audio track, using camera audio only")
        mode = "camera"
    if mode in ("mix", "camera") and not cam_info["audio"]:
        if not base_info["audio"]:
            die("neither input has an audio track")
        print("note: camera video has no audio track, using base audio only")
        mode = "base"

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", args.base]

    if mode == "base":
        cmd += ["-map", "0:v:0", "-map", "0:a:0", "-c", "copy",
                "-movflags", "+faststart", args.out]
        run(cmd)
        print(f"done: {args.out} (audio: base)")
        return

    if args.offset > 0:
        cmd += ["-ss", f"{args.offset}"]
    cmd += ["-i", args.camera]

    cam_chain = [f"volume={args.cam_vol}"]
    if args.offset < 0:
        cam_chain.insert(0, f"adelay={int(-args.offset * 1000)}:all=1")

    if mode == "camera":
        graph = f"[1:a:0]{','.join(cam_chain)}[a]"
    else:
        graph = (f"[0:a:0]volume={args.base_vol}[a0];"
                 f"[1:a:0]{','.join(cam_chain)}[a1];"
                 f"[a0][a1]amix=inputs=2:duration=first:normalize=0[a]")

    cmd += [
        "-filter_complex", graph, "-map", "0:v:0", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", "-shortest", args.out,
    ]
    run(cmd)
    print(f"done: {args.out} (audio: {mode})")


if __name__ == "__main__":
    main()
