"""Replace Pillow's bundled Brotli decoder with the patched system decoder.

Pillow 13.0.0 manylinux wheels bundle libbrotlidec 1.2.0, which lacks the
upstream 1.2.1 memory-corruption fix. Pillow's bundled FreeType links it to
decode WOFF2 fonts. Image builds run this after installing requirements and
fail unless every Brotli library loaded through Pillow reports the fix marker.
Requires the Debian libbrotli1 package; see docs/plans/node2shell-security-update.
"""

from __future__ import annotations

import ctypes
import glob
import os
import subprocess
import sys
from pathlib import Path

FIXED_ERROR_CODE = -17  # BROTLI_DECODER_ERROR_FORMAT_BLOCK_SWITCH, added by the fix.
SYSTEM_LIB_GLOB = "/usr/lib/*-linux-gnu/{name}.so.1"
BUNDLED_PREFIXES = ("libbrotlidec", "libbrotlicommon")

VERIFY_LOADED = """
import ctypes, os, sys
from PIL import ImageFont, features
assert features.check("freetype2"), "Pillow FreeType support is missing"
ImageFont.load_default(size=12).getbbox("Brotli")
loaded = set()
with open("/proc/self/maps") as maps:
    for line in maps:
        path = line.split()[-1]
        if "libbrotlidec" in path:
            loaded.add(os.path.realpath(path))
assert loaded, "Pillow FreeType did not load a Brotli decoder"
for path in sorted(loaded):
    decoder = ctypes.CDLL(path)
    decoder.BrotliDecoderErrorString.argtypes = [ctypes.c_int]
    decoder.BrotliDecoderErrorString.restype = ctypes.c_char_p
    message = decoder.BrotliDecoderErrorString(int(sys.argv[1])).decode()
    assert message.endswith("BLOCK_SWITCH"), f"{path} lacks the Brotli fix: {message}"
    print(f"Pillow FreeType uses patched Brotli decoder {path}")
"""


def _system_lib(name: str) -> Path:
    matches = glob.glob(SYSTEM_LIB_GLOB.format(name=name))
    if len(matches) != 1:
        raise SystemExit(f"Expected one system {name}.so.1, found {matches}; install libbrotli1")
    return Path(os.path.realpath(matches[0]))


def _assert_fixed(decoder_path: Path) -> None:
    decoder = ctypes.CDLL(str(decoder_path))
    decoder.BrotliDecoderErrorString.argtypes = [ctypes.c_int]
    decoder.BrotliDecoderErrorString.restype = ctypes.c_char_p
    message = decoder.BrotliDecoderErrorString(FIXED_ERROR_CODE).decode()
    if not message.endswith("BLOCK_SWITCH"):
        raise SystemExit(f"System Brotli decoder {decoder_path} lacks the fix: {message}")


def main() -> int:
    import PIL

    system_libs = {name: _system_lib(name) for name in BUNDLED_PREFIXES}
    _assert_fixed(system_libs["libbrotlidec"])

    libs_dir = Path(PIL.__file__).resolve().parent.parent / "pillow.libs"
    for bundled in sorted(libs_dir.glob("libbrotli*.so*")):
        prefix = bundled.name.split("-", 1)[0]
        if prefix not in system_libs:
            raise SystemExit(f"Unexpected bundled Brotli library {bundled.name}")
        staged = bundled.with_name(f".{bundled.name}.patched")
        staged.unlink(missing_ok=True)
        staged.symlink_to(system_libs[prefix])
        os.replace(staged, bundled)
        print(f"Replaced {bundled.name} with {system_libs[prefix]}")

    subprocess.run([sys.executable, "-c", VERIFY_LOADED, str(FIXED_ERROR_CODE)], check=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
