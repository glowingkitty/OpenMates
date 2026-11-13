"""Measure the length of generated audio files (MP3 and WAV) without extra dependencies.

The Remotion Sequence of a clip needs its real length in frames. MP3 length is
summed from the MPEG frame headers (works for constant and variable bit rate);
WAV length comes from the RIFF ``fmt `` and ``data`` chunks. ``None`` means the
format is not recognised and the caller must decide what to use instead.
"""

from __future__ import annotations

import struct
from typing import Optional

_MPEG1_L3_BITRATES = (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320)
_MPEG2_L3_BITRATES = (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160)
_SAMPLE_RATES = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}


def _id3_end(data: bytes) -> int:
    if data.startswith(b"ID3") and len(data) >= 10:
        size = ((data[6] & 0x7F) << 21) | ((data[7] & 0x7F) << 14) | ((data[8] & 0x7F) << 7) | (data[9] & 0x7F)
        return 10 + size
    return 0


def mp3_duration_seconds(data: bytes) -> Optional[float]:
    """Sum the durations of all Layer III frames; ``None`` when no frame is found."""
    position, total, frames = _id3_end(data), 0.0, 0
    while position + 4 <= len(data):
        header = struct.unpack(">I", data[position:position + 4])[0]
        version, layer = (header >> 19) & 3, (header >> 17) & 3
        bitrate_index, rate_index = (header >> 12) & 15, (header >> 10) & 3
        valid = (header >> 21) == 0x7FF and version != 1 and layer == 1 and 0 < bitrate_index < 15 and rate_index < 3
        if not valid:
            position += 1
            continue
        bitrate = (_MPEG1_L3_BITRATES if version == 3 else _MPEG2_L3_BITRATES)[bitrate_index] * 1000
        rate = _SAMPLE_RATES[version][rate_index]
        samples = 1152 if version == 3 else 576
        padding = (header >> 9) & 1
        length = samples // 8 * bitrate // rate + padding
        total += samples / rate
        frames += 1
        position += max(length, 4)
    return round(total, 3) if frames else None


def wav_duration_seconds(data: bytes) -> Optional[float]:
    """Length of a PCM WAV file from its header; ``None`` when it is not a readable WAV."""
    if not (data.startswith(b"RIFF") and data[8:12] == b"WAVE"):
        return None
    position, byte_rate, data_size = 12, 0, None
    while position + 8 <= len(data):
        chunk, size = data[position:position + 4], struct.unpack("<I", data[position + 4:position + 8])[0]
        if chunk == b"fmt " and position + 20 <= len(data):
            byte_rate = struct.unpack("<I", data[position + 16:position + 20])[0]
        elif chunk == b"data":
            data_size = min(size, len(data) - position - 8)
            break
        position += 8 + size + (size % 2)
    if not byte_rate or data_size is None:
        return None
    return round(data_size / byte_rate, 3)


def audio_duration_seconds(data: bytes, mime_type: str) -> Optional[float]:
    """Measured length for ``audio/mpeg`` or ``audio/wav`` content (decided by the bytes, then the mime type)."""
    wav = wav_duration_seconds(data)
    if wav is not None:
        return wav
    return mp3_duration_seconds(data)
