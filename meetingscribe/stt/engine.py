"""Speech-to-text via faster-whisper.

Two tiers:
  * realtime — a small, fast model transcribing short live chunks during a call.
  * offline  — a heavier, more accurate model run on the full saved recording
               afterwards, when the live captions weren't precise enough.

faster-whisper is an optional dependency. Importing this module never requires
it; the model only loads on first use, raising a clear message if missing.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from ..config import STTConfig
from ..paths import MODELS_DIR

# Whisper model sizes faster-whisper can fetch by name, smallest → most accurate.
# Offered to the UI so the user can pick a heavier model for the deferred pass
# when the real-time captions weren't precise enough. Any other string (a custom
# path or HuggingFace id) is still accepted; this list is only for the picker.
KNOWN_MODELS = [
    "tiny",
    "base",
    "small",
    "medium",
    "large-v2",
    "large-v3",
    "large-v3-turbo",
    "distil-large-v3",
]


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str


def _load_faster_whisper():
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError as e:  # pragma: no cover - depends on optional dep
        raise RuntimeError(
            "faster-whisper is not installed. Install it with:\n"
            "  pip install 'meetingscribe[stt]'\n"
            "or  pip install faster-whisper"
        ) from e
    return WhisperModel


class WhisperEngine:
    """Holds up to two cached models (realtime + offline) and serializes access."""

    def __init__(self, cfg: STTConfig) -> None:
        self.cfg = cfg
        self._models: dict[str, object] = {}
        self._lock = threading.Lock()

    def _get_model(self, model_name: str):
        with self._lock:
            if model_name in self._models:
                return self._models[model_name]
            WhisperModel = _load_faster_whisper()
            device = None if self.cfg.device == "auto" else self.cfg.device
            compute = self.cfg.compute_type
            kwargs = {"download_root": str(MODELS_DIR)}
            if device:
                kwargs["device"] = device
            if compute and compute != "auto":
                kwargs["compute_type"] = compute
            model = WhisperModel(model_name, **kwargs)
            self._models[model_name] = model
            return model

    def _transcribe(self, source, model_name: str) -> list[TranscriptSegment]:
        model = self._get_model(model_name)
        segments, _info = model.transcribe(
            source,
            language=self.cfg.language,
            vad_filter=self.cfg.vad_filter,
            beam_size=5,
        )
        return [
            TranscriptSegment(start=s.start, end=s.end, text=s.text.strip())
            for s in segments
        ]

    def transcribe_realtime(self, audio) -> list[TranscriptSegment]:
        """audio: float32 numpy array at 16 kHz mono (a live chunk)."""
        return self._transcribe(audio, self.cfg.realtime_model)

    def transcribe_file(
        self,
        path: str | Path,
        *,
        offline: bool = True,
        model: str | None = None,
    ) -> list[TranscriptSegment]:
        """Transcribe a saved recording.

        offline=True picks the configured high-accuracy model. An explicit
        ``model`` overrides that, letting the deferred pass run a heavier model
        on demand when the real-time captions weren't precise enough.
        """
        model_name = model or (self.cfg.offline_model if offline else self.cfg.realtime_model)
        return self._transcribe(str(path), model_name)

    def warmup(self, model_name: str | None = None) -> None:
        self._get_model(model_name or self.cfg.realtime_model)
