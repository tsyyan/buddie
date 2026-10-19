"""Draw assets/icon.png (512x512): a check mark on a rounded square, no image library needed.

    python scripts/make_icon.py
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

SIZE, RADIUS = 512, 96
BG, FG = (31, 41, 55), (52, 211, 153)  # slate, emerald


def _dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return ((px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2) ** 0.5


def pixel(x, y):
    cx, cy = min(max(x, RADIUS), SIZE - RADIUS), min(max(y, RADIUS), SIZE - RADIUS)
    if (x - cx) ** 2 + (y - cy) ** 2 > RADIUS ** 2:
        return (0, 0, 0, 0)
    d = min(_dist(x, y, 140, 270, 222, 352), _dist(x, y, 222, 352, 378, 168))
    return (*FG, 255) if d < 30 else (*BG, 255)


def png(path: Path) -> None:
    rows = b"".join(b"\x00" + bytes(c for x in range(SIZE) for c in pixel(x, y)) for y in range(SIZE))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    head = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", head) + chunk(b"IDAT", zlib.compress(rows, 9))
                     + chunk(b"IEND", b""))


if __name__ == "__main__":
    png(Path(__file__).resolve().parents[1] / "assets" / "icon.png")
