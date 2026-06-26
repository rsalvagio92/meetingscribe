"""Recording engine: capture mic and/or system audio, mix to 16 kHz mono,
persist a WAV, and emit fixed-length chunks for live transcription.

Design notes
------------
* Two independent capture sources (mic via sounddevice, system via sounddevice
  on Linux/mac or pyaudiowpatch on Windows) each push frames into a queue.
* A mixer thread pulls ~chunk_seconds of audio from each source, resamples both
  to the target rate, mixes them, appends to the WAV, and calls on_chunk().
* All hardware imports are lazy so the rest of the app runs without audio libs.
"""
from __future__ import annotations

import queue
import threading
import wave
from pathlib import Path
from typing import Callable

import numpy as np

from ..config import AudioConfig
from . import devices as dev
from . import dsp

ChunkCallback = Callable[[np.ndarray], None]


class _Source:
    """One capture stream feeding a queue of (frames, rate) float32 mono blocks."""

    def __init__(self, q: "queue.Queue[np.ndarray]", target_rate: int) -> None:
        self.q = q
        self.target_rate = target_rate
        self._stream = None
        self._pa = None  # pyaudiowpatch handle, if used

    def _emit(self, audio: np.ndarray, src_rate: int) -> None:
        mono = dsp.to_mono(audio)
        res = dsp.resample_linear(mono, src_rate, self.target_rate)
        self.q.put(res)

    def stop(self) -> None:
        try:
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
        except Exception:
            pass
        try:
            if self._pa is not None:
                self._pa.terminate()
        except Exception:
            pass


def _start_sounddevice_source(
    q: "queue.Queue[np.ndarray]", target_rate: int, device_index: int | None
) -> _Source:
    import sounddevice as sd  # type: ignore

    src = _Source(q, target_rate)
    info = sd.query_devices(device_index) if device_index is not None else sd.query_devices(kind="input")
    src_rate = int(info["default_samplerate"])

    def callback(indata, frames, time_info, status):  # noqa: ANN001
        src._emit(np.array(indata, dtype=np.float32), src_rate)

    stream = sd.InputStream(
        samplerate=src_rate,
        device=device_index,
        channels=1,
        dtype="float32",
        callback=callback,
    )
    stream.start()
    src._stream = stream
    return src


def _start_windows_loopback_source(
    q: "queue.Queue[np.ndarray]", target_rate: int, device_index: int | None
) -> _Source:
    import pyaudiowpatch as pyaudio  # type: ignore

    src = _Source(q, target_rate)
    p = pyaudio.PyAudio()
    src._pa = p
    if device_index is None:
        info = p.get_default_wasapi_loopback()
        device_index = info["index"]
    else:
        info = p.get_device_info_by_index(device_index)
    src_rate = int(info["defaultSampleRate"])
    channels = int(info["maxInputChannels"]) or 2

    def callback(in_data, frame_count, time_info, status):  # noqa: ANN001
        audio = np.frombuffer(in_data, dtype=np.float32)
        if channels > 1:
            audio = audio.reshape(-1, channels)
        src._emit(audio, src_rate)
        return (None, pyaudio.paContinue)

    stream = p.open(
        format=pyaudio.paFloat32,
        channels=channels,
        rate=src_rate,
        frames_per_buffer=int(src_rate * 0.5),
        input=True,
        input_device_index=device_index,
        stream_callback=callback,
    )
    stream.start_stream()
    src._stream = stream
    return src


class Recorder:
    def __init__(self, cfg: AudioConfig, wav_path: str | Path, on_chunk: ChunkCallback | None = None):
        self.cfg = cfg
        self.wav_path = str(wav_path)
        self.on_chunk = on_chunk
        self._mic_q: "queue.Queue[np.ndarray]" = queue.Queue()
        self._sys_q: "queue.Queue[np.ndarray]" = queue.Queue()
        self._sources: list[_Source] = []
        self._mixer: threading.Thread | None = None
        self._stop = threading.Event()
        self._wav: wave.Wave_write | None = None
        self.frames_written = 0

    # --- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        import sys

        rate = self.cfg.sample_rate
        if self.cfg.capture_mic:
            idx = _resolve_index(self.cfg.mic_device, kind="mic")
            self._sources.append(_start_sounddevice_source(self._mic_q, rate, idx))
        if self.cfg.capture_system:
            idx = _resolve_index(self.cfg.system_device, kind="system")
            if sys.platform == "win32":
                self._sources.append(_start_windows_loopback_source(self._sys_q, rate, idx))
            else:
                self._sources.append(_start_sounddevice_source(self._sys_q, rate, idx))

        if not self._sources:
            raise RuntimeError("No audio sources enabled. Enable mic and/or system capture.")

        Path(self.wav_path).parent.mkdir(parents=True, exist_ok=True)
        self._wav = wave.open(self.wav_path, "wb")
        self._wav.setnchannels(1)
        self._wav.setsampwidth(2)  # int16
        self._wav.setframerate(rate)

        self._mixer = threading.Thread(target=self._mix_loop, daemon=True)
        self._mixer.start()

    def stop(self) -> None:
        self._stop.set()
        for s in self._sources:
            s.stop()
        if self._mixer:
            self._mixer.join(timeout=5)
        self._drain_remaining()
        if self._wav:
            self._wav.close()
            self._wav = None

    # --- mixing ------------------------------------------------------------
    def _collect(self, q: "queue.Queue[np.ndarray]", min_samples: int) -> np.ndarray:
        buf: list[np.ndarray] = []
        total = 0
        while total < min_samples and not self._stop.is_set():
            try:
                block = q.get(timeout=0.2)
            except queue.Empty:
                break
            buf.append(block)
            total += block.shape[0]
        return np.concatenate(buf) if buf else np.zeros(0, dtype=np.float32)

    def _mix_loop(self) -> None:
        rate = self.cfg.sample_rate
        chunk = int(rate * self.cfg.chunk_seconds)
        want_mic = self.cfg.capture_mic
        want_sys = self.cfg.capture_system
        while not self._stop.is_set():
            mic = self._collect(self._mic_q, chunk) if want_mic else np.zeros(0, dtype=np.float32)
            sysb = self._collect(self._sys_q, chunk) if want_sys else np.zeros(0, dtype=np.float32)
            if mic.size == 0 and sysb.size == 0:
                continue
            mixed = dsp.mix(mic, sysb) if (want_mic and want_sys) else (mic if mic.size else sysb)
            self._write_and_emit(mixed)

    def _drain_remaining(self) -> None:
        leftover_mic = self._collect(self._mic_q, 0) if self.cfg.capture_mic else np.zeros(0, dtype=np.float32)
        leftover_sys = self._collect(self._sys_q, 0) if self.cfg.capture_system else np.zeros(0, dtype=np.float32)
        if leftover_mic.size or leftover_sys.size:
            mixed = dsp.mix(leftover_mic, leftover_sys)
            self._write_and_emit(mixed)

    def _write_and_emit(self, mixed: np.ndarray) -> None:
        if mixed.size == 0:
            return
        if self._wav:
            self._wav.writeframes(dsp.float32_to_int16(mixed).tobytes())
            self.frames_written += mixed.shape[0]
        if self.on_chunk:
            try:
                self.on_chunk(mixed)
            except Exception:
                pass


def _resolve_index(device_ref: str | None, *, kind: str) -> int | None:
    """Map a configured device name/index to a PortAudio index (None = default)."""
    if device_ref is None or device_ref == "":
        if kind == "system":
            d = dev.default_loopback()
            return d.index if d else None
        return None
    try:
        return int(device_ref)
    except ValueError:
        pass
    pool = dev.list_loopback_devices() if kind == "system" else dev.list_input_devices()
    for d in pool:
        if device_ref.lower() in d.name.lower():
            return d.index
    return None
