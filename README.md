# MeetingScribe

Cross-platform meeting recorder with local Whisper transcription and vendor-agnostic LLM note generation. Runs entirely on your machine — no cloud transcription, no data leaves your network.

## Features

- **Real-time captions** during a call (small/fast Whisper model)
- **High-accuracy offline re-transcription** after the call (large model, on demand)
- **Structured note generation** — summary, decisions, action items, open questions
- **Markdown + PDF export**
- **GitHub Copilot support** — works with Copilot subscription (no OpenAI API key needed), including GitHub Enterprise (GHE)
- **Vendor-agnostic LLM** — Copilot, Anthropic Claude, or any OpenAI-compatible endpoint (Ollama, OpenRouter, etc.)
- **Cross-platform audio** — mic + system loopback on Windows (WASAPI), macOS, and Linux
- **Local REST API** — headless-friendly, SPA dashboard included

## Quick Start

```bash
# 1. Clone
git clone https://github.com/rsalvagio92/meetingscribe.git
cd meetingscribe

# 2. Create virtualenv and install
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e ".[stt,audio]"

# 3. Run
meetingscribe
# → opens http://localhost:8765
```

> **Windows:** also install the loopback driver: `pip install pyaudiowpatch`

## Requirements

- Python 3.10+
- For real transcription: `faster-whisper` (pulled by `[stt]` extra — needs ~1 GB for `base` model, ~3 GB for `large-v3`)
- For audio capture: `sounddevice` + `numpy` (pulled by `[audio]`)

## Installation Options

```bash
# Minimal (API + notes only, no transcription or audio)
pip install -e .

# With speech-to-text
pip install -e ".[stt]"

# With audio capture
pip install -e ".[audio]"

# Full (everything + PDF export)
pip install -e ".[stt,audio,pdf]"

# Windows full install
pip install -e ".[stt,audio,audio-windows,pdf]"
```

## Configuration

Data lives in a per-user directory:

| Platform | Path |
|----------|------|
| Windows  | `%APPDATA%\MeetingScribe\` |
| macOS    | `~/Library/Application Support/MeetingScribe/` |
| Linux    | `~/.local/share/meetingscribe/` |

Override with `MEETINGSCRIBE_DATA_DIR=/path`.

### LLM Providers

Configure via `PUT /api/config` or the dashboard Settings panel.

#### GitHub Copilot (recommended — no API key needed)

```json
{
  "llm": {
    "provider": "copilot",
    "model": "gpt-4o"
  }
}
```

Then authenticate: `POST /api/copilot/login/start` → open the URL shown → poll `POST /api/copilot/login/poll` until `{"status": "ok"}`.

#### GitHub Enterprise

```json
{
  "llm": {
    "provider": "copilot",
    "copilot_ghe_host": "ghe.yourcorp.com",
    "model": "gpt-4o"
  }
}
```

#### OpenAI-compatible (Ollama, OpenRouter, LM Studio…)

```json
{
  "llm": {
    "provider": "openai_compat",
    "base_url": "http://localhost:11434/v1",
    "model": "llama3"
  }
}
```

#### Anthropic Claude

```json
{
  "llm": {
    "provider": "anthropic",
    "model": "claude-sonnet-4-6"
  }
}
```

Set the API key: `POST /api/secrets` with `{"key": "ANTHROPIC_API_KEY", "value": "sk-ant-..."}`.

### Whisper Models

Two tiers run independently:

| Tier | Config key | Default | Use |
|------|-----------|---------|-----|
| Real-time | `stt.realtime_model` | `base` | Live captions during a call |
| Offline | `stt.offline_model` | `large-v3` | Accurate re-transcription after a call |

Switch the offline model on a per-transcription basis:

```
POST /api/meetings/{id}/transcribe?model=large-v3-turbo
```

Available models (fastest → most accurate): `tiny`, `base`, `small`, `medium`, `large-v2`, `large-v3`, `large-v3-turbo`, `distil-large-v3`.

## API Reference

### Config

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/config` | Get current config |
| `PUT` | `/api/config` | Patch config (`{"patch": {...}}`) |

### Secrets

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/secrets` | List stored secret names (values never returned) |
| `POST` | `/api/secrets` | Set a secret `{"key": "...", "value": "..."}` |
| `DELETE` | `/api/secrets/{key}` | Delete a secret |

### Recording

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/record/start` | Start recording `{"title": "..."}` |
| `GET` | `/api/record/live` | Get live transcript of active recording |
| `POST` | `/api/record/stop` | Stop and save recording |

### Meetings

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/meetings` | List all meetings |
| `GET` | `/api/meetings/{id}` | Get a meeting |
| `DELETE` | `/api/meetings/{id}` | Delete a meeting |
| `POST` | `/api/meetings/{id}/transcribe` | Re-transcribe with high-accuracy model. `?model=large-v3` overrides the configured offline model |
| `POST` | `/api/meetings/{id}/notes` | Generate structured notes via LLM |
| `POST` | `/api/meetings/{id}/export` | Export to file. `?fmt=md` (default) or `?fmt=pdf` |

### Copilot Login

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/copilot/login/start` | Start device-flow. Returns `user_code` + `verification_uri` |
| `POST` | `/api/copilot/login/poll` | Poll once. Returns `{"status": "pending"\|"ok"}`. Call every `interval` seconds |

### Audio Devices

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/devices` | List available input and loopback devices |
| `GET` | `/api/stt/models` | List available Whisper models and current config |

## Architecture

```
meetingscribe/
├── api/server.py       FastAPI backend — all endpoints, AppState singleton
├── audio/
│   ├── recorder.py     Two-source capture (mic + system), WAV writer, chunk emitter
│   ├── devices.py      Device enumeration (sounddevice + pyaudiowpatch)
│   └── dsp.py          Mono mix, resample, float32↔int16
├── stt/engine.py       WhisperEngine — two cached models, thread-safe
├── llm/
│   ├── copilot.py      GitHub Copilot provider (OAuth token exchange + chat)
│   ├── copilot_auth.py Device-flow login helpers (github.com + GHE)
│   ├── anthropic.py    Anthropic provider
│   ├── openai_compat.py OpenAI-compatible provider (Ollama, LM Studio…)
│   └── factory.py      build_provider() — picks provider from config
├── notes/
│   ├── builder.py      LLM prompt + JSON parsing → NoteResult dataclass
│   └── prompts.py      System + user prompts for note generation
├── store/
│   ├── db.py           SQLite meeting library (WAL mode)
│   └── secrets.py      AES-256-GCM encrypted secrets store
├── session.py          LiveSession — wires recorder → realtime STT → store
├── service.py          Stateless helpers: offline_transcribe, make_notes, export
├── config.py           AppConfig (JSON on disk, non-secret preferences)
└── paths.py            Cross-platform data directories
```

## Development

```bash
# Install dev extras
pip install -e ".[dev]"

# Run tests (no tokens or hardware needed — all mocked)
.venv/bin/python -m pytest

# Run with auto-reload
uvicorn meetingscribe.api.server:create_app --factory --reload
```

Tests use `respx` to mock HTTP calls and `monkeypatch` for WhisperEngine — the full suite (37 tests) runs without any API tokens or audio hardware.

## License

MIT
