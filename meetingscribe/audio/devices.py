"""Cross-platform audio device discovery.

Microphone input is the same everywhere (sounddevice / PortAudio). Capturing the
*other participants* (system output) differs per OS:

  * Windows : WASAPI loopback via pyaudiowpatch — a real loopback device.
  * Linux   : PulseAudio/PipeWire expose a ".monitor" source per output sink;
              it shows up as a normal input device in PortAudio.
  * macOS   : no OS loopback; the user installs a virtual device (BlackHole /
              Loopback) and selects it as the system device.

This module only enumerates and resolves; capture lives in recorder.py.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass


@dataclass
class Device:
    index: int
    name: str
    max_input_channels: int
    default_samplerate: float
    is_loopback: bool = False
    backend: str = "sounddevice"  # or "pyaudiowpatch"


def list_input_devices() -> list[Device]:
    try:
        import sounddevice as sd  # type: ignore
    except ImportError:
        return []
    out: list[Device] = []
    for i, d in enumerate(sd.query_devices()):
        if d.get("max_input_channels", 0) > 0:
            name = d["name"]
            out.append(
                Device(
                    index=i,
                    name=name,
                    max_input_channels=d["max_input_channels"],
                    default_samplerate=d.get("default_samplerate", 44100.0),
                    is_loopback=(".monitor" in name.lower()),
                )
            )
    return out


def list_loopback_devices() -> list[Device]:
    """System-output capture devices (other participants)."""
    if sys.platform == "win32":
        return _windows_loopback()
    if sys.platform == "darwin":
        # Virtual devices show up as normal inputs; surface likely candidates.
        return [
            d
            for d in list_input_devices()
            if any(k in d.name.lower() for k in ("blackhole", "loopback", "soundflower"))
        ]
    # Linux: PulseAudio monitor sources.
    return [d for d in list_input_devices() if d.is_loopback]


def _windows_loopback() -> list[Device]:
    try:
        import pyaudiowpatch as pyaudio  # type: ignore
    except ImportError:
        return []
    out: list[Device] = []
    p = pyaudio.PyAudio()
    try:
        for info in p.get_loopback_device_info_generator():
            out.append(
                Device(
                    index=info["index"],
                    name=info["name"],
                    max_input_channels=info["maxInputChannels"],
                    default_samplerate=info["defaultSampleRate"],
                    is_loopback=True,
                    backend="pyaudiowpatch",
                )
            )
    finally:
        p.terminate()
    return out


def default_loopback() -> Device | None:
    devs = list_loopback_devices()
    return devs[0] if devs else None
