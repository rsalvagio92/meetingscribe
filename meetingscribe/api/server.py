"""FastAPI backend. Serves the SPA and exposes the meeting API.

The desktop shell (pywebview) and a plain browser both talk to this server.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import service
from ..config import AppConfig
from ..paths import ensure_dirs
from ..store.db import MeetingStore
from ..store.secrets import SecretStore

# Thread pool for blocking operations like Whisper transcription.
_executor = ThreadPoolExecutor(max_workers=2)

UI_DIR = Path(__file__).resolve().parent.parent.parent / "ui"


# Request models live at module scope so FastAPI can resolve the (stringized,
# due to `from __future__ import annotations`) body type hints against globals.
class ConfigPatch(BaseModel):
    patch: dict


class SecretBody(BaseModel):
    key: str
    value: str


class StartBody(BaseModel):
    title: str = ""


class NotesBody(BaseModel):
    include_transcript: bool = True


class AppState:
    """Process-wide singletons + the at-most-one live session."""

    def __init__(self) -> None:
        ensure_dirs()
        self.cfg = AppConfig.load()
        self.store = MeetingStore()
        self.secrets = SecretStore()
        self.live = None  # LiveSession | None


def create_app(state: AppState | None = None) -> FastAPI:
    state = state or AppState()
    app = FastAPI(title="MeetingScribe", version="0.1.0")
    app.state.ms = state

    # ---- meta -----------------------------------------------------------
    @app.get("/api/health")
    def health():
        return {"ok": True, "version": "0.1.0", "recording": state.live is not None}

    @app.get("/api/config")
    def get_config():
        return state.cfg.to_dict()

    @app.put("/api/config")
    def put_config(body: ConfigPatch):
        state.cfg.update(body.patch)
        return state.cfg.to_dict()

    # ---- secrets (names only out; values only in) -----------------------
    @app.get("/api/secrets")
    def list_secrets():
        return {"names": state.secrets.names()}

    @app.post("/api/secrets")
    def set_secret(body: SecretBody):
        state.secrets.set(body.key, body.value)
        return {"ok": True, "names": state.secrets.names()}

    @app.delete("/api/secrets/{key}")
    def del_secret(key: str):
        state.secrets.delete(key)
        return {"ok": True, "names": state.secrets.names()}

    # ---- speech-to-text models -----------------------------------------
    @app.get("/api/stt/models")
    def stt_models():
        from ..stt.engine import KNOWN_MODELS

        return {
            "models": KNOWN_MODELS,
            "realtime": state.cfg.stt.realtime_model,
            "offline": state.cfg.stt.offline_model,
        }

    # ---- audio devices --------------------------------------------------
    @app.get("/api/devices")
    def devices():
        from ..audio import devices as dev

        return {
            "input": [d.__dict__ for d in dev.list_input_devices()],
            "loopback": [d.__dict__ for d in dev.list_loopback_devices()],
        }

    # ---- recording lifecycle -------------------------------------------
    @app.post("/api/record/start")
    def record_start(body: StartBody):
        if state.live is not None:
            raise HTTPException(409, "a recording is already in progress")
        from ..session import LiveSession

        sess = LiveSession(state.cfg, state.store, body.title)
        try:
            sess.start()
        except Exception as e:
            raise HTTPException(500, f"could not start recording: {e}")
        state.live = sess
        return {"id": sess.id, "title": sess.title, "started_at": sess.started_at}

    @app.get("/api/record/live")
    def record_live():
        if state.live is None:
            raise HTTPException(404, "no active recording")
        return {"id": state.live.id, "transcript": state.live.live_transcript()}

    @app.post("/api/record/stop")
    def record_stop():
        if state.live is None:
            raise HTTPException(404, "no active recording")
        result = state.live.stop()
        state.live = None
        return result

    # ---- processing -----------------------------------------------------
    @app.post("/api/meetings/{mid}/transcribe")
    async def transcribe(mid: str, model: str | None = None):
        try:
            # Run the blocking Whisper transcription in a thread pool so the
            # server can handle other requests while this runs.
            loop = asyncio.get_event_loop()
            transcript, model_used = await loop.run_in_executor(
                _executor,
                lambda: service.offline_transcribe(
                    state.cfg, state.store, mid, model=model
                ),
            )
        except (ValueError, FileNotFoundError) as e:
            raise HTTPException(400, str(e))
        return {"id": mid, "transcript": transcript, "quality": "offline", "model": model_used}

    @app.post("/api/meetings/{mid}/notes")
    async def notes(mid: str, body: NotesBody):
        from ..llm.base import LLMError

        try:
            return await service.make_notes(
                state.cfg, state.store, state.secrets, mid,
                include_transcript=body.include_transcript,
            )
        except ValueError as e:
            raise HTTPException(400, str(e))
        except LLMError as e:
            # LLM unreachable / misconfigured (e.g. Ollama not running, or no
            # provider token). Surface a clean message instead of a 500.
            raise HTTPException(502, f"LLM request failed: {e}")

    @app.post("/api/meetings/{mid}/export")
    def export(mid: str, fmt: str = "md"):
        try:
            path = service.export(state.cfg, state.store, mid, fmt)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"path": path}

    # ---- library --------------------------------------------------------
    @app.get("/api/meetings")
    def list_meetings():
        return {"meetings": state.store.list()}

    @app.get("/api/meetings/{mid}")
    def get_meeting(mid: str):
        m = state.store.get(mid)
        if not m:
            raise HTTPException(404, "not found")
        return m

    @app.delete("/api/meetings/{mid}")
    def delete_meeting(mid: str):
        state.store.delete(mid)
        return {"ok": True}

    # ---- copilot device-flow login -------------------------------------
    @app.post("/api/copilot/login/start")
    async def copilot_login_start():
        from ..llm import copilot_auth

        ghe = state.cfg.llm.copilot_ghe_host
        d = await copilot_auth.start_device_flow(ghe)
        # Stash device_code server-side keyed by user_code for the poll step.
        app.state.pending_device = d
        return {
            "user_code": d.user_code,
            "verification_uri": d.verification_uri,
            "expires_in": d.expires_in,
        }

    @app.post("/api/copilot/login/poll")
    async def copilot_login_poll():
        from ..llm import copilot_auth

        d = getattr(app.state, "pending_device", None)
        if d is None:
            raise HTTPException(400, "no device flow in progress")
        ghe = state.cfg.llm.copilot_ghe_host
        try:
            status, result = await copilot_auth.poll_once(d, ghe)
        except httpx.HTTPError as e:
            raise HTTPException(503, f"GitHub unreachable: {e}")

        if status == "ok":
            state.secrets.set("GITHUB_COPILOT_OAUTH_TOKEN", result)
            app.state.pending_device = None
            return {"status": "ok"}
        if status == "expired":
            app.state.pending_device = None
            raise HTTPException(400, f"device flow failed: {result}")
        # status == "pending"
        return {
            "status": "pending",
            "interval": d.interval,
            "expires_in": d.expires_in,
        }

    # ---- SPA static + index --------------------------------------------
    if (UI_DIR / "js").exists():
        app.mount("/js", StaticFiles(directory=UI_DIR / "js"), name="js")
    if (UI_DIR / "css").exists():
        app.mount("/css", StaticFiles(directory=UI_DIR / "css"), name="css")

    @app.get("/")
    def index():
        idx = UI_DIR / "index.html"
        if idx.exists():
            return FileResponse(idx)
        return {"error": "UI not built"}

    return app
