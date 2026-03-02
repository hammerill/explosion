from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

from PIL import Image, ImageSequence


def _default_gif_path() -> Path:
    return Path(__file__).resolve().parents[2] / "explosion.gif"


def _fit_size(src_w: int, src_h: int, max_w: int, max_h: int) -> tuple[int, int]:
    scale = min(max_w / src_w, max_h / src_h)
    width = max(1, int(src_w * scale))
    height = max(1, int(src_h * scale))
    return width, height


def _render_frame(frame: Image.Image, cols: int, rows: int) -> str:
    max_w = max(cols, 1)
    max_h = max(rows * 2, 2)

    frame = frame.convert("RGB")
    new_w, new_h = _fit_size(frame.width, frame.height, max_w, max_h)
    resized = frame.resize((new_w, new_h), Image.Resampling.BOX)

    canvas = Image.new("RGB", (max_w, max_h), (0, 0, 0))
    x = (max_w - new_w) // 2
    y = (max_h - new_h) // 2
    canvas.paste(resized, (x, y))
    pixels = canvas.load()

    lines: list[str] = []
    for py in range(0, max_h, 2):
        parts: list[str] = []
        for px in range(max_w):
            top = pixels[px, py]
            bottom = pixels[px, min(py + 1, max_h - 1)]
            parts.append(
                f"\x1b[38;2;{top[0]};{top[1]};{top[2]}m"
                f"\x1b[48;2;{bottom[0]};{bottom[1]};{bottom[2]}m"
                "▀"
            )
        parts.append("\x1b[0m")
        lines.append("".join(parts))
    return "\n".join(lines)


def _load_frames(gif_path: Path) -> tuple[list[Image.Image], list[float]]:
    frames: list[Image.Image] = []
    durations: list[float] = []
    with Image.open(gif_path) as img:
        for frame in ImageSequence.Iterator(img):
            frames.append(frame.copy())
            duration_ms = frame.info.get("duration", 100)
            duration_s = max(float(duration_ms) / 1000.0, 0.01)
            durations.append(duration_s)
    if not frames:
        raise ValueError(f"No frames found in {gif_path}")
    return frames, durations


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Play a GIF in a truecolor terminal loop."
    )
    parser.add_argument(
        "gif",
        nargs="?",
        type=Path,
        default=_default_gif_path(),
        help="Path to GIF file (default: explosion.gif).",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Play the GIF once instead of looping forever.",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=None,
        help="Force a fixed frame rate (overrides GIF timings).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    gif_path = args.gif.expanduser().resolve()

    if not gif_path.exists():
        print(f"GIF not found: {gif_path}", file=sys.stderr)
        raise SystemExit(1)

    frames, delays = _load_frames(gif_path)
    if args.fps is not None:
        if args.fps <= 0:
            print("--fps must be greater than 0.", file=sys.stderr)
            raise SystemExit(2)
        delays = [1.0 / args.fps] * len(frames)

    sys.stdout.write("\x1b[2J\x1b[H\x1b[?25l")
    sys.stdout.flush()

    try:
        while True:
            for frame, delay in zip(frames, delays):
                term = shutil.get_terminal_size(fallback=(80, 24))
                rendered = _render_frame(frame, term.columns, term.lines)
                sys.stdout.write("\x1b[H")
                sys.stdout.write(rendered)
                sys.stdout.flush()
                time.sleep(delay)
            if args.once:
                break
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[0m\x1b[?25h\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
