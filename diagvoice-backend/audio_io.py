"""
Ses dosyası yükleme: önce librosa, başarısızsa pydub+ffmpeg ile WAV’a çevirip librosa.
AAC (.aac) gibi librosa’nın doğrudan okuyamadığı formatlar için kullanılır.
"""

from __future__ import annotations

import io
import os
import tempfile
from pathlib import Path
from typing import BinaryIO

import librosa
import numpy as np

try:
    from pydub import AudioSegment
except ImportError:  # pragma: no cover
    AudioSegment = None  # type: ignore[misc, assignment]


def load_mono_float32(path: str, *, sr: int | None, mono: bool = True) -> tuple[np.ndarray, int]:
    """
    Disk yolundan mono float32 waveform + örnekleme hızı.
    `sr` None ise librosa özgün hızda döner (pydub yolunda export sonrası da).
    """
    try:
        y, s_out = librosa.load(path, sr=sr, mono=mono)
        if y is None or y.size == 0:
            raise RuntimeError("empty audio")
        return np.asarray(y, dtype=np.float32), int(s_out)
    except Exception:
        if AudioSegment is None:
            raise
    seg = AudioSegment.from_file(path)
    seg = seg.set_channels(1)
    if sr is not None:
        seg = seg.set_frame_rate(int(sr))
    buf = io.BytesIO()
    seg.export(buf, format="wav")
    buf.seek(0)
    y2, s2 = librosa.load(buf, sr=sr, mono=mono)
    if y2 is None or y2.size == 0:
        raise RuntimeError("empty audio after pydub decode")
    return np.asarray(y2, dtype=np.float32), int(s2)


def load_mono_float32_from_buffer(
    data: bytes | BinaryIO,
    *,
    sr: int | None,
    mono: bool = True,
    filename_hint: str = "audio.wav",
) -> tuple[np.ndarray, int]:
    """Bellekteki ses: uzantıya göre geçici dosyada decode (pydub format tespiti için)."""
    raw = data if isinstance(data, bytes) else data.read()
    suf = Path(filename_hint).suffix or ".wav"
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suf) as tmp:
            tmp.write(raw)
            tmp_path = tmp.name
        return load_mono_float32(tmp_path, sr=sr, mono=mono)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
