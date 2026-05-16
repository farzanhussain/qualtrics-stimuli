#!/usr/bin/env python3
"""Generate solid-colour PNG icons for iOS PWA install.

iOS Safari doesn't reliably honour SVG icons for `apple-touch-icon`, so we
ship plain PNGs alongside the SVG. The text-on-icon is decorative; a flat
red square installs cleanly on the home screen and is what she'll see on
the install sheet.

Pure stdlib so this runs anywhere (no Pillow). Re-run only if you change
the colour or sizes; the outputs are committed.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "src" / "rednote_kb" / "site" / "pwa"
COLOUR = (0xFF, 0x24, 0x42)   # RedNote red
SIZES = [180, 192, 512]       # 180 = apple-touch-icon canonical; 192/512 = maskable


def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(
        ">I", zlib.crc32(tag + data) & 0xFFFFFFFF
    )


def solid_png(size: int, rgb: tuple[int, int, int]) -> bytes:
    """Emit a valid PNG: signature + IHDR + IDAT + IEND."""
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)   # 8-bit RGB

    row = b"\x00" + bytes(rgb) * size                            # filter 0 + pixels
    raw = row * size
    idat = zlib.compress(raw, level=9)

    return sig + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for s in SIZES:
        path = OUT / f"icon-{s}.png"
        path.write_bytes(solid_png(s, COLOUR))
        print(f"wrote {path}  ({path.stat().st_size}B)")


if __name__ == "__main__":
    main()
