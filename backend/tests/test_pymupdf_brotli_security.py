"""Check the Linux PDF runtime's actual bundled decoder and rendering behavior."""

import ctypes
from pathlib import Path
import sys

import pymupdf
import pytest


# contract-test: infrastructure
@pytest.mark.skipif(sys.platform != "linux", reason="Production PDF runtime images use Linux")
def test_mupdf_bundled_brotli_contains_block_switch_fix() -> None:
    libraries = list(Path(pymupdf.__file__).parent.glob("libmupdf.so*"))
    assert len(libraries) == 1
    decoder = ctypes.CDLL(str(libraries[0]))
    decoder.BrotliDecoderErrorString.argtypes = [ctypes.c_int]
    decoder.BrotliDecoderErrorString.restype = ctypes.c_char_p
    # Safe introspection: never pass malformed data to a potentially old decoder.
    # The upstream fix introduces error -17; vulnerable builds return INVALID.
    assert decoder.BrotliDecoderErrorString(-17).decode().endswith("BLOCK_SWITCH")
    decoder.BrotliDecoderCreateInstance.argtypes = [ctypes.c_void_p] * 3
    decoder.BrotliDecoderCreateInstance.restype = ctypes.c_void_p
    decoder.BrotliDecoderDestroyInstance.argtypes = [ctypes.c_void_p]
    decoder.BrotliDecoderDestroyInstance.restype = None
    decoder.BrotliDecoderGetErrorCode.argtypes = [ctypes.c_void_p]
    decoder.BrotliDecoderGetErrorCode.restype = ctypes.c_int
    byte_pointer = ctypes.POINTER(ctypes.c_uint8)
    size_pointer = ctypes.POINTER(ctypes.c_size_t)
    decoder.BrotliDecoderDecompressStream.argtypes = [
        ctypes.c_void_p, size_pointer, ctypes.POINTER(byte_pointer),
        size_pointer, ctypes.POINTER(byte_pointer), size_pointer,
    ]
    decoder.BrotliDecoderDecompressStream.restype = ctypes.c_int
    # Exercise Node's public regression vector only after confirming the backport.
    data = bytes.fromhex("200010414141fcffff07002228f00b60f7f41f000000")
    source, output = ctypes.create_string_buffer(data), ctypes.create_string_buffer(65536)
    next_in, next_out = ctypes.cast(source, byte_pointer), ctypes.cast(output, byte_pointer)
    available_in, available_out = ctypes.c_size_t(len(data)), ctypes.c_size_t(len(output))
    total_out = ctypes.c_size_t()
    state = decoder.BrotliDecoderCreateInstance(None, None, None)
    assert state
    try:
        # This vector emits repeated literals before reaching the invalid switch.
        # Drain into one reused buffer, with a hard 32 MiB work bound.
        for _ in range(512):
            available_out.value = len(output)
            next_out = ctypes.cast(output, byte_pointer)
            result = decoder.BrotliDecoderDecompressStream(
                state, ctypes.byref(available_in), ctypes.byref(next_in),
                ctypes.byref(available_out), ctypes.byref(next_out), ctypes.byref(total_out),
            )
            if result != 3:  # BROTLI_DECODER_RESULT_NEEDS_MORE_OUTPUT
                break
        else:
            pytest.fail("Brotli regression exceeded its bounded output allowance")
        assert result == 0
        assert decoder.BrotliDecoderGetErrorCode(state) == -17
    finally:
        decoder.BrotliDecoderDestroyInstance(state)


# contract-test: infrastructure
def test_pdf_text_and_page_preview_round_trip() -> None:
    with pymupdf.open() as document:
        page = document.new_page(width=300, height=200)
        page.insert_text((30, 50), "OpenMates native PDF security regression")
        encoded = document.tobytes()

    with pymupdf.open(stream=encoded, filetype="pdf") as document:
        assert "native PDF security regression" in document[0].get_text()
        thumbnail = document[0].get_pixmap(matrix=pymupdf.Matrix(0.5, 0.5))
        assert (thumbnail.width, thumbnail.height) == (150, 100)
        assert thumbnail.tobytes("png").startswith(b"\x89PNG\r\n\x1a\n")
