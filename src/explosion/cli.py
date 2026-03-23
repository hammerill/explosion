from __future__ import annotations

import argparse
import bisect
import shutil
import sys
import time
from collections.abc import Callable
from pathlib import Path

import ntplib
from PIL import Image, ImageSequence


def _default_gif_path() -> Path:
    return Path(__file__).resolve().with_name("assets") / "explosion.gif"


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


def _build_timeline(delays: list[float]) -> tuple[list[float], float]:
    edges: list[float] = []
    total = 0.0
    for delay in delays:
        total += delay
        edges.append(total)
    return edges, total


def _frame_index_for_phase(phase: float, edges: list[float]) -> int:
    index = bisect.bisect_right(edges, phase)
    return min(index, len(edges) - 1)


def _sleep_until_loop_start(global_now: Callable[[], float], loop_duration: float) -> None:
    phase = global_now() % loop_duration
    if phase <= 0:
        return
    time.sleep(loop_duration - phase)


class GlobalClock:
    def __init__(self, server: str, timeout: float, refresh_interval: float) -> None:
        self.server = server
        self.timeout = timeout
        self.refresh_interval = refresh_interval
        self._client = ntplib.NTPClient()
        self._offset_seconds = 0.0
        self._last_sync_mono = 0.0
        self._has_synced = False

    def sync(self) -> bool:
        try:
            response = self._client.request(self.server, version=3, timeout=self.timeout)
        except Exception:
            return False
        self._offset_seconds = float(response.offset)
        self._last_sync_mono = time.monotonic()
        self._has_synced = True
        return True

    def now(self) -> float:
        should_refresh = (
            (not self._has_synced)
            or (time.monotonic() - self._last_sync_mono >= self.refresh_interval)
        )
        if should_refresh:
            self.sync()
        return time.time() + self._offset_seconds


def _global_now_factory(args: argparse.Namespace) -> Callable[[], float]:
    if args.no_time_sync:
        return time.time

    clock = GlobalClock(
        server=args.time_server,
        timeout=args.sync_timeout,
        refresh_interval=args.sync_refresh,
    )
    if not clock.sync():
        print(
            f"warning: failed to sync with {args.time_server}; using local clock.",
            file=sys.stderr,
        )
        return time.time
    return clock.now


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
    parser.add_argument(
        "--no-time-sync",
        action="store_true",
        help="Disable global clock sync and use local system time.",
    )
    parser.add_argument(
        "--time-server",
        type=str,
        default="time.google.com",
        help="NTP server used for global playback anchoring.",
    )
    parser.add_argument(
        "--sync-timeout",
        type=float,
        default=1.5,
        help="NTP query timeout in seconds.",
    )
    parser.add_argument(
        "--sync-refresh",
        type=float,
        default=300.0,
        help="How often to refresh NTP offset in seconds.",
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
    if args.sync_timeout <= 0:
        print("--sync-timeout must be greater than 0.", file=sys.stderr)
        raise SystemExit(2)
    if args.sync_refresh <= 0:
        print("--sync-refresh must be greater than 0.", file=sys.stderr)
        raise SystemExit(2)

    frame_edges, loop_duration = _build_timeline(delays)
    global_now = _global_now_factory(args)

    sys.stdout.write("\x1b[2J\x1b[H\x1b[?25l")
    sys.stdout.flush()

    try:
        if args.once:
            for frame, delay in zip(frames, delays):
                term = shutil.get_terminal_size(fallback=(80, 24))
                rendered = _render_frame(frame, term.columns, term.lines)
                sys.stdout.write("\x1b[H")
                sys.stdout.write(rendered)
                sys.stdout.flush()
                time.sleep(delay)
            return

        _sleep_until_loop_start(global_now, loop_duration)

        while True:
            phase = global_now() % loop_duration
            frame_index = _frame_index_for_phase(phase, frame_edges)

            term = shutil.get_terminal_size(fallback=(80, 24))
            rendered = _render_frame(frames[frame_index], term.columns, term.lines)
            sys.stdout.write("\x1b[H")
            sys.stdout.write(rendered)
            sys.stdout.flush()

            next_edge = frame_edges[frame_index]
            sleep_for = next_edge - phase
            if sleep_for > 0:
                time.sleep(sleep_for)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[0m\x1b[?25h\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
