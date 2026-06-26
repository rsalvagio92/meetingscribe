"""User configuration (non-secret). JSON on disk, hot-readable.

Secrets (API keys, tokens) never live here — they go in the encrypted store.
This holds preferences: chosen provider, models, audio devices, output dir.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .paths import CONFIG_PATH, EXPORTS_DIR


@dataclass
class STTConfig:
    # Real-time model: small + fast for live captions.
    realtime_model: str = "base"
    # Offline model: heavier, higher accuracy, run on the saved recording.
    offline_model: str = "large-v3"
    language: str | None = None          # None = autodetect
    device: str = "auto"                 # auto|cpu|cuda
    compute_type: str = "auto"           # auto|int8|float16|float32
    vad_filter: bool = True


@dataclass
class LLMConfig:
    provider: str = "openai_compat"      # openai_compat|anthropic|copilot
    model: str = "gpt-4o-mini"
    # Generic OpenAI-compatible endpoint (Ollama, LM Studio, OpenRouter, ...).
    base_url: str = "http://localhost:11434/v1"
    # GitHub Copilot Enterprise (GHE) hosts. Leave blank for github.com Copilot.
    copilot_ghe_host: str = ""           # e.g. "ghe.mycorp.com"
    temperature: float = 0.2
    max_tokens: int = 2000


@dataclass
class AudioConfig:
    capture_mic: bool = True
    capture_system: bool = True          # loopback (other participants)
    mic_device: str | None = None        # None = default
    system_device: str | None = None     # None = autodetect loopback
    sample_rate: int = 16000             # Whisper-native
    chunk_seconds: float = 5.0           # live transcription cadence


@dataclass
class AppConfig:
    stt: STTConfig = field(default_factory=STTConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    output_dir: str = str(EXPORTS_DIR)
    ui_language: str = "it"

    @classmethod
    def load(cls) -> "AppConfig":
        if not CONFIG_PATH.exists():
            cfg = cls()
            cfg.save()
            return cfg
        raw = json.loads(CONFIG_PATH.read_text())
        return cls(
            stt=STTConfig(**raw.get("stt", {})),
            llm=LLMConfig(**raw.get("llm", {})),
            audio=AudioConfig(**raw.get("audio", {})),
            output_dir=raw.get("output_dir", str(EXPORTS_DIR)),
            ui_language=raw.get("ui_language", "it"),
        )

    def save(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(self.to_dict(), indent=2))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def update(self, patch: dict[str, Any]) -> None:
        """Shallow-merge a nested patch dict and persist."""
        for section in ("stt", "llm", "audio"):
            if section in patch and isinstance(patch[section], dict):
                obj = getattr(self, section)
                for k, v in patch[section].items():
                    if hasattr(obj, k):
                        setattr(obj, k, v)
        if "output_dir" in patch:
            self.output_dir = patch["output_dir"]
        if "ui_language" in patch:
            self.ui_language = patch["ui_language"]
        self.save()
