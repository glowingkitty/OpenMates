"""Numbers and stitch data read back from the delivered machine file (standard library only).

Every number in the summary is decoded from the DST file Ink/Stitch wrote, so it
describes the delivered files, never the source graphic. DST stores moves in
0.1 mm units with +y pointing up; points here use +y down like SVG.

Estimated sewing time: ``ceil(stitches / 480 + thread_changes * 1)`` minutes,
at least 1, and ``ceil(stitches / 480)`` per thread. 480 stitches per minute is
what a home machine reported for a real 47,000-stitch design; one minute per
thread change for rethreading. It is a rough figure for any machine: real time
varies with the machine and its speed setting.

Estimated upper thread: the sewn path of a thread plus 1 mm per stitch for the
thread that goes into the fabric and back, in metres with one decimal. Travel
with the needle up is not counted. Bobbin thread is not part of the figure.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field

STITCHES_PER_MINUTE = 480
MINUTES_PER_THREAD_CHANGE = 1
THREAD_MM_PER_STITCH = 1.0
DST_HEADER_BYTES = 512
LONG_JUMP_TENTHS = 30  # pen-up travel longer than 3 mm counts as a jump

_BITS_B0 = ((0x01, 1, 0), (0x02, -1, 0), (0x04, 9, 0), (0x08, -9, 0),
            (0x80, 0, 1), (0x40, 0, -1), (0x20, 0, 9), (0x10, 0, -9))
_BITS_B1 = ((0x01, 3, 0), (0x02, -3, 0), (0x04, 27, 0), (0x08, -27, 0),
            (0x80, 0, 3), (0x40, 0, -3), (0x20, 0, 27), (0x10, 0, -27))
_BITS_B2 = ((0x04, 81, 0), (0x08, -81, 0), (0x20, 0, 81), (0x10, 0, -81))
# Ink/Stitch thread list line: "<n> <name> #<number> - <manufacturer> (#rrggbb)".
THREAD_LINE_RE = re.compile(
    r"^\s*\d+\s+(?P<name>.*?) #(?P<number>\S*) - (?P<maker>.*?) \((?P<hex>#[0-9a-fA-F]{6})\)\s*$"
)


@dataclass
class Block:
    """One colour block: stitch points in 0.1 mm (y down); None marks pen-up."""

    points: list[tuple[int, int] | None] = field(default_factory=list)
    stitches: int = 0
    jumps: int = 0
    sewn_tenths: float = 0.0  # length of the sewn path, needle down, in 0.1 mm


def decode_dst(data: bytes) -> list[Block]:
    """Decode a Tajima DST body into colour blocks."""
    if len(data) < DST_HEADER_BYTES:
        raise ValueError("DST file is shorter than its header")
    blocks = [Block()]
    x = y = 0
    pen_up_from: tuple[int, int] | None = None
    body = data[DST_HEADER_BYTES:]
    for offset in range(0, len(body) - 2, 3):
        b0, b1, b2 = body[offset], body[offset + 1], body[offset + 2]
        if b2 & 0xF3 == 0xF3:
            break
        dx = dy = 0
        for byte, table in ((b0, _BITS_B0), (b1, _BITS_B1), (b2, _BITS_B2)):
            for mask, step_x, step_y in table:
                if byte & mask:
                    dx += step_x
                    dy += step_y
        x += dx
        y += dy
        block = blocks[-1]
        if b2 & 0xC3 == 0xC3:
            blocks.append(Block())
            pen_up_from = (x, -y)
            continue
        if b2 & 0x83 == 0x83:
            if pen_up_from is None:
                pen_up_from = block.points[-1] if block.points and block.points[-1] else (x - dx, -(y - dy))
            continue
        if pen_up_from is not None:
            if block.points:
                block.points.append(None)
                if math.dist(pen_up_from, (x, -y)) > LONG_JUMP_TENTHS:
                    block.jumps += 1
            pen_up_from = None
        elif block.points and block.points[-1] is not None:
            block.sewn_tenths += math.dist(block.points[-1], (x, -y))
        block.points.append((x, -y))
        block.stitches += 1
    return [block for block in blocks if block.stitches]


def parse_threadlist(text: str) -> list[dict[str, str]]:
    """Read the 'Thread Order' section of Ink/Stitch's thread list."""
    threads: list[dict[str, str]] = []
    in_order = False
    for line in text.splitlines():
        if line.strip().startswith("Thread Order"):
            in_order = True
            continue
        if in_order and line.strip().startswith("Thread Used"):
            break
        match = THREAD_LINE_RE.match(line) if in_order else None
        if match:
            colour = match.group("hex").lower()
            name, number, maker = (match.group(key).strip() for key in ("name", "number", "maker"))
            if name and name != "None":
                label = " ".join(part for part in (maker, number) if part and part != "None")
                name = f"{name} ({label})" if label else name
            else:
                name = colour
            threads.append({"colour_hex": colour, "name": name})
    return threads


def estimated_minutes(stitch_count: int, thread_changes: int) -> int:
    return max(1, math.ceil(stitch_count / STITCHES_PER_MINUTE + thread_changes * MINUTES_PER_THREAD_CHANGE))


def thread_minutes(stitch_count: int) -> int:
    """Rough sewing minutes of one thread, without rethreading."""
    return max(1, math.ceil(stitch_count / STITCHES_PER_MINUTE))


def thread_metres(sewn_tenths: float, stitch_count: int) -> float:
    """Rough upper thread of one colour in metres, at least 0.1."""
    return max(0.1, round((sewn_tenths / 10.0 + stitch_count * THREAD_MM_PER_STITCH) / 1000.0, 1))


def extent(blocks: list[Block]) -> tuple[int, int, int, int]:
    points = [point for block in blocks for point in block.points if point is not None]
    if not points:
        raise ValueError("no stitches")
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def sewn_width_mm(dst: bytes) -> float:
    """Width of the stitched design in millimetres, read from the DST file."""
    x0, _, x1, _ = extent(decode_dst(dst))
    return (x1 - x0) / 10.0


def build_report(dst: bytes, threadlist: str) -> tuple[dict[str, object], dict[str, object]]:
    """Return (partial summary, stitches document) from the delivered DST and thread list."""
    blocks = decode_dst(dst)
    threads = parse_threadlist(threadlist)
    if not blocks:
        raise ValueError("the DST file holds no stitches")
    if len(threads) != len(blocks):
        raise ValueError(f"thread list has {len(threads)} colours but the DST has {len(blocks)} blocks")
    x0, y0, x1, y1 = extent(blocks)
    stitch_count = sum(block.stitches for block in blocks)
    thread_changes = len(blocks) - 1
    lengths = [thread_metres(block.sewn_tenths, block.stitches) for block in blocks]
    thread_rows: list[dict[str, object]] = [
        dict(thread, stitch_count=block.stitches, estimated_minutes=thread_minutes(block.stitches),
             thread_length_m=length)
        for thread, block, length in zip(threads, blocks, lengths)
    ]
    summary: dict[str, object] = {
        "width_mm": round((x1 - x0) / 10.0, 1),
        "height_mm": round((y1 - y0) / 10.0, 1),
        "stitch_count": stitch_count,
        "thread_changes": thread_changes,
        "estimated_minutes": estimated_minutes(stitch_count, thread_changes),
        "threads": thread_rows,
        "thread_length_m": round(sum(lengths), 1),
        "jumps": sum(block.jumps for block in blocks),
    }
    stitches = {
        "width_mm": summary["width_mm"],
        "height_mm": summary["height_mm"],
        "blocks": [
            {"colour_hex": thread["colour_hex"],
             "points": [None if p is None else [p[0] - x0, p[1] - y0] for p in block.points]}
            for thread, block in zip(threads, blocks)
        ],
    }
    return summary, stitches


def stitches_json(stitches: dict[str, object]) -> bytes:
    """Compact, whitespace-free JSON for clients that draw the stitches."""
    return json.dumps(stitches, separators=(",", ":")).encode("utf-8")
