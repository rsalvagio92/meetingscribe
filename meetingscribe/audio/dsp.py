"""Small DSP helpers: to-mono, linear resample, int16<->float32, mix.

Kept dependency-light (numpy only) and pure so it's unit-testable headless.
"""
from __future__ import annotations

import numpy as np


def to_mono(audio: np.ndarray) -> np.ndarray:
    """(frames, channels) or (frames,) float -> (frames,) float."""
    if audio.ndim == 2:
        return audio.mean(axis=1)
    return audio


def resample_linear(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Cheap linear resample. Fine for speech / transcription."""
    if src_rate == dst_rate or audio.size == 0:
        return audio.astype(np.float32, copy=False)
    duration = audio.shape[0] / src_rate
    dst_len = int(round(duration * dst_rate))
    if dst_len <= 0:
        return np.zeros(0, dtype=np.float32)
    src_idx = np.linspace(0.0, audio.shape[0] - 1, num=dst_len)
    out = np.interp(src_idx, np.arange(audio.shape[0]), audio)
    return out.astype(np.float32)


def int16_to_float32(audio: np.ndarray) -> np.ndarray:
    return (audio.astype(np.float32)) / 32768.0


def float32_to_int16(audio: np.ndarray) -> np.ndarray:
    clipped = np.clip(audio, -1.0, 1.0)
    return (clipped * 32767.0).astype(np.int16)


def mix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Additively mix two mono float streams, padding the shorter, then
    soft-limit to avoid clipping when both are loud."""
    n = max(a.shape[0], b.shape[0])
    pa = np.pad(a, (0, n - a.shape[0]))
    pb = np.pad(b, (0, n - b.shape[0]))
    mixed = pa + pb
    peak = np.max(np.abs(mixed)) if mixed.size else 0.0
    if peak > 1.0:
        mixed = mixed / peak
    return mixed.astype(np.float32)
