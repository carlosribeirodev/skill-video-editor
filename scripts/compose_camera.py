#!/usr/bin/env python3
"""Overlay a camera (facecam) video on top of a base video, with effects.

Default look: rounded-rectangle card with a border and a soft drop shadow.
Also supports a circle crop and chroma key (green screen). The base video's
audio is passed through untouched — use mix_audio.py to blend the camera
microphone in afterwards.

Usage:
    python compose_camera.py base.mp4 camera.mp4 --out composed.mp4 \
        [--shape rounded|circle] [--position bottomright] [--size 0.30] \
        [--aspect source|1:1|4:3|16:9] [--offset 0] [--chroma-key 0x00FF00]
"""

import argparse
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from common import check_binaries, die, even, run, video_info

POSITIONS = ("topleft", "topcenter", "topright",
             "bottomleft", "bottomcenter", "bottomright")

SUPERSAMPLE = 4  # anti-aliasing factor for the Pillow-drawn masks


def rounded_mask(w: int, h: int, radius: int) -> Image.Image:
    """White rounded rectangle on black, used as the camera's alpha channel."""
    s = SUPERSAMPLE
    img = Image.new("L", (w * s, h * s), 0)
    ImageDraw.Draw(img).rounded_rectangle(
        [0, 0, w * s - 1, h * s - 1], radius=radius * s, fill=255)
    return img.resize((w, h), Image.LANCZOS)


def card_image(cam_w: int, cam_h: int, radius: int, border: int,
               border_color: str, pad: int) -> Image.Image:
    """Drop shadow + border ring, drawn on a transparent canvas larger than
    the camera. The camera video is overlaid at (pad, pad) on top of it."""
    s = SUPERSAMPLE
    size = ((cam_w + 2 * pad) * s, (cam_h + 2 * pad) * s)

    shadow = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        [pad * s, (pad + 8) * s, (pad + cam_w) * s - 1, (pad + cam_h + 8) * s - 1],
        radius=radius * s, fill=(0, 0, 0, 130))
    shadow = shadow.resize((size[0] // s, size[1] // s), Image.LANCZOS)
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))

    ring = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(ring).rounded_rectangle(
        [(pad - border) * s, (pad - border) * s,
         (pad + cam_w + border) * s - 1, (pad + cam_h + border) * s - 1],
        radius=(radius + border) * s, fill=border_color)
    ring = ring.resize((size[0] // s, size[1] // s), Image.LANCZOS)

    return Image.alpha_composite(shadow, ring)


def camera_crop(cam_info: dict, aspect: str) -> str | None:
    """Return an ffmpeg crop filter that center-crops the camera to the
    requested aspect, or None to keep the source aspect."""
    if aspect == "source":
        return None
    num, den = (int(v) for v in aspect.split(":"))
    target = num / den
    w, h = cam_info["width"], cam_info["height"]
    if w / h > target:
        cw, ch = even(h * target), even(h)
    else:
        cw, ch = even(w), even(w / target)
    return f"crop={cw}:{ch}"


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("base", help="base video (screen recording or the 9:16 render)")
    parser.add_argument("camera", help="camera (facecam) video")
    parser.add_argument("--out", required=True)
    parser.add_argument("--shape", choices=("rounded", "circle"), default="rounded")
    parser.add_argument("--position", choices=POSITIONS, default="bottomright")
    parser.add_argument("--size", type=float, default=0.30,
                        help="camera width as a fraction of the base width (default 0.30)")
    parser.add_argument("--aspect", default="source",
                        help="center-crop the camera to this aspect: source, 1:1, 4:3, 16:9")
    parser.add_argument("--margin", type=int, default=40,
                        help="distance from the frame edges in pixels (default 40)")
    parser.add_argument("--radius", type=int, default=0,
                        help="corner radius in pixels (default: 6%% of the camera size)")
    parser.add_argument("--border", type=int, default=6, help="border width (default 6)")
    parser.add_argument("--border-color", default="#FFFFFF")
    parser.add_argument("--offset", type=float, default=0.0,
                        help="camera sync offset in seconds: positive skips the start of "
                             "the camera (it began recording earlier), negative delays it")
    parser.add_argument("--chroma-key", default=None, metavar="COLOR",
                        help="remove this background color (e.g. 0x00FF00); disables the "
                             "card/border look and overlays the keyed camera directly")
    parser.add_argument("--chroma-similarity", type=float, default=0.20)
    parser.add_argument("--chroma-blend", type=float, default=0.10)
    parser.add_argument("--crf", type=int, default=19)
    parser.add_argument("--preset", default="medium")
    args = parser.parse_args()

    check_binaries()
    base_info = video_info(args.base)
    cam_info = video_info(args.camera)
    if not base_info["video"] or not cam_info["video"]:
        die("both inputs must contain a video stream")
    base_w, base_h = base_info["video"]["width"], base_info["video"]["height"]

    aspect = "1:1" if args.shape == "circle" else args.aspect
    crop = camera_crop(cam_info["video"], aspect)

    cam_w = even(base_w * args.size)
    if crop:
        num, den = (int(v) for v in aspect.split(":"))
        cam_h = even(cam_w * den / num)
    else:
        cam_h = even(cam_w * cam_info["video"]["height"] / cam_info["video"]["width"])

    # Position of the camera rectangle on the base frame.
    x = {"left": args.margin, "center": (base_w - cam_w) // 2,
         "right": base_w - cam_w - args.margin}[
        args.position.replace("top", "").replace("bottom", "")]
    y = args.margin if args.position.startswith("top") else base_h - cam_h - args.margin

    cam_filters = [f for f in (crop, f"scale={cam_w}:{cam_h}", "setsar=1") if f]

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", args.base]
    if args.offset > 0:
        cmd += ["-ss", f"{args.offset}"]
    cmd += ["-i", args.camera]
    if args.offset < 0:
        cam_filters.append(
            f"tpad=start_duration={-args.offset}:start_mode=clone")

    if args.chroma_key:
        cam_filters += [
            f"chromakey={args.chroma_key}:{args.chroma_similarity}:{args.chroma_blend}",
            "format=rgba",
        ]
        graph = (f"[1:v]{','.join(cam_filters)}[cam];"
                 f"[0:v][cam]overlay={x}:{y}:eof_action=pass[v]")
    else:
        radius = args.radius or max(10, int(0.06 * min(cam_w, cam_h)))
        if args.shape == "circle":
            radius = cam_w // 2
        pad = args.border + 44  # room for the shadow around the card
        tmp = Path(tempfile.mkdtemp(prefix="camcard_"))
        rounded_mask(cam_w, cam_h, radius).save(tmp / "mask.png")
        card_image(cam_w, cam_h, radius, args.border,
                   args.border_color, pad).save(tmp / "card.png")
        cmd += ["-loop", "1", "-i", str(tmp / "card.png"),
                "-loop", "1", "-i", str(tmp / "mask.png")]
        cam_filters.append("format=rgba")
        graph = (
            f"[1:v]{','.join(cam_filters)}[cam];"
            f"[3:v]format=gray[mask];"
            f"[cam][mask]alphamerge[camr];"
            f"[0:v][2:v]overlay={x - pad}:{y - pad}:eof_action=pass[bg];"
            f"[bg][camr]overlay={x}:{y}:eof_action=pass[v]"
        )

    cmd += [
        "-filter_complex", graph, "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", args.preset, "-crf", str(args.crf),
        "-pix_fmt", "yuv420p", "-c:a", "copy",
        "-movflags", "+faststart", "-shortest", args.out,
    ]
    run(cmd)
    print(f"done: {args.out} (camera {cam_w}x{cam_h} at {args.position})")


if __name__ == "__main__":
    main()
