"""Small same-origin HTTP server for the browser UI and app pipeline."""

from __future__ import annotations

import argparse
import json
import logging
import secrets
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import RLock
from typing import Any

from voice_concierge.app.adapter import handle_audio_turn, handle_turn
from voice_concierge.app.factory import build_voice_concierge_pipeline
from voice_concierge.app.pipeline import VoiceConciergePipeline
from voice_concierge.app.serialization import (
    JsonDict,
    PayloadValidationError,
    app_pipeline_state_from_dict,
    app_pipeline_state_to_dict,
)
from voice_concierge.app.types import AppPipelineState
from voice_concierge.reasoning.models import (
    DEFAULT_MODEL_SELECTION_PATH,
    load_model_selection,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4173
MAX_REQUEST_BYTES = 16 * 1024 * 1024
MAX_WEB_SESSIONS = 32
SESSION_COOKIE_NAME = "granite_session"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WEB_DIRECTORY = REPOSITORY_ROOT / "web"
LOGGER = logging.getLogger("voice_concierge.web")

SessionTurn = Callable[
    [AppPipelineState | None],
    tuple[JsonDict, AppPipelineState],
]


class PipelineSessionStore:
    """Keep authoritative pipeline state inside the local web process."""

    def __init__(self, *, max_sessions: int = MAX_WEB_SESSIONS) -> None:
        if max_sessions <= 0:
            raise ValueError("max_sessions must be positive.")
        self._max_sessions = max_sessions
        self._states: OrderedDict[str, AppPipelineState] = OrderedDict()
        self._lock = RLock()

    def process(
        self,
        session_id: str | None,
        turn: SessionTurn,
    ) -> tuple[str, JsonDict]:
        """Run one serialized turn atomically against server-owned state."""

        with self._lock:
            resolved_id = self._resolve_id(session_id)
            current_state = self._states.get(resolved_id)
            response, next_state = turn(current_state)
            self._states[resolved_id] = next_state
            self._states.move_to_end(resolved_id)
            while len(self._states) > self._max_sessions:
                self._states.popitem(last=False)
            return resolved_id, response

    def _resolve_id(self, session_id: str | None) -> str:
        if session_id is not None and session_id in self._states:
            return session_id
        while True:
            generated = secrets.token_urlsafe(24)
            if generated not in self._states:
                return generated


class PipelineWebServer(ThreadingHTTPServer):
    """HTTP server carrying the shared pipeline and capability metadata."""

    def __init__(
        self,
        server_address: tuple[str, int],
        pipeline: VoiceConciergePipeline,
        *,
        web_directory: Path = DEFAULT_WEB_DIRECTORY,
        voice_input_enabled: bool = False,
        voice_output_enabled: bool = False,
        model_name: str = "configured model",
    ) -> None:
        self.pipeline = pipeline
        self.web_directory = web_directory
        self.capabilities = {
            "text_input": True,
            "voice_input": voice_input_enabled,
            "voice_output": voice_output_enabled,
            "wake_word": False,
        }
        self.runtime = {"model": model_name}
        self.sessions = PipelineSessionStore()
        super().__init__(server_address, PipelineRequestHandler)


class PipelineRequestHandler(SimpleHTTPRequestHandler):
    """Serve static UI assets plus JSON turn endpoints."""

    server: PipelineWebServer

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(
            *args,
            directory=str(args[2].web_directory),
            **kwargs,
        )

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/health":
            self._write_json(
                HTTPStatus.OK,
                {
                    "status": "ready",
                    "capabilities": self.server.capabilities,
                    "runtime": self.server.runtime,
                },
            )
            return
        super().do_GET()

    def end_headers(self) -> None:
        """Prevent stale HTML, JavaScript, and CSS from being mixed in development."""

        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_POST(self) -> None:  # noqa: N802
        request_id = secrets.token_hex(4)
        started_at = time.monotonic()
        handlers = {
            "/api/turn": handle_turn,
            "/api/audio": handle_audio_turn,
        }
        handler = handlers.get(self.path)
        if handler is None:
            LOGGER.warning(
                "web_request_rejected request_id=%s endpoint=%s reason=not_found",
                request_id,
                self.path,
            )
            self._write_json(
                HTTPStatus.NOT_FOUND,
                {"error": {"code": "not_found", "message": "Unknown endpoint."}},
            )
            return

        try:
            payload = self._read_json_body()
            session_id, response = self.server.sessions.process(
                self._posted_session_id(),
                lambda state: self._run_turn(handler, payload, state),
            )
        except PayloadValidationError as exc:
            LOGGER.warning(
                "web_request_rejected request_id=%s endpoint=%s "
                "reason=invalid_request detail=%s",
                request_id,
                self.path,
                exc,
            )
            self._write_json(
                HTTPStatus.BAD_REQUEST,
                {"error": {"code": "invalid_request", "message": str(exc)}},
            )
            return
        except Exception:
            LOGGER.exception(
                "web_request_failed request_id=%s endpoint=%s",
                request_id,
                self.path,
            )
            self._write_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "pipeline_unavailable",
                        "message": "The local application pipeline is unavailable.",
                    }
                },
            )
            return

        memory_operation = response.get("memory_operation")
        memory_status = (
            memory_operation.get("status")
            if isinstance(memory_operation, Mapping)
            else None
        )
        memory_detail = (
            memory_operation.get("detail")
            if isinstance(memory_operation, Mapping)
            else None
        )
        errors = response.get("errors")
        LOGGER.info(
            "web_turn_completed request_id=%s endpoint=%s duration_ms=%d "
            "errors=%s memory_status=%s memory_detail=%s",
            request_id,
            self.path,
            round((time.monotonic() - started_at) * 1000),
            errors if errors else "none",
            memory_status or "none",
            memory_detail or "none",
        )
        self._write_json(HTTPStatus.OK, response, session_id=session_id)

    def _run_turn(
        self,
        handler: Callable[[Mapping[str, Any], VoiceConciergePipeline], JsonDict],
        payload: Mapping[str, Any],
        state: AppPipelineState | None,
    ) -> tuple[JsonDict, AppPipelineState]:
        """Replace untrusted posted state with the session's trusted state."""

        trusted_payload = dict(payload)
        trusted_payload["state"] = (
            app_pipeline_state_to_dict(state) if state is not None else None
        )
        response = handler(trusted_payload, self.server.pipeline)
        next_state = app_pipeline_state_from_dict(response.get("state"))
        if next_state is None:
            raise RuntimeError("Pipeline response did not contain state.")
        return response, next_state

    def _posted_session_id(self) -> str | None:
        raw_cookie = self.headers.get("Cookie")
        if not raw_cookie:
            return None
        cookies = SimpleCookie()
        try:
            cookies.load(raw_cookie)
        except CookieError:
            return None
        session = cookies.get(SESSION_COOKIE_NAME)
        return session.value if session is not None else None

    def _read_json_body(self) -> Mapping[str, Any]:
        content_length = self.headers.get("Content-Length")
        try:
            length = int(content_length or "0")
        except ValueError as exc:
            raise PayloadValidationError("Content-Length must be an integer.") from exc
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise PayloadValidationError("Request body size is invalid.")
        try:
            payload = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PayloadValidationError("Request body must be valid JSON.") from exc
        if not isinstance(payload, Mapping):
            raise PayloadValidationError("request must be an object.")
        return payload

    def _write_json(
        self,
        status: HTTPStatus,
        payload: Mapping[str, Any],
        *,
        session_id: str | None = None,
    ) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if session_id is not None:
            self.send_header(
                "Set-Cookie",
                (
                    f"{SESSION_COOKIE_NAME}={session_id}; "
                    "HttpOnly; SameSite=Strict; Path=/"
                ),
            )
        self.end_headers()
        self.wfile.write(body)


def build_web_pipeline(
    *,
    load_memory: bool = False,
    load_voice_io: bool = False,
    demo: bool = False,
) -> VoiceConciergePipeline:
    """Build the local pipeline configured for browser turns."""

    if demo:
        from voice_concierge.app.smoke import build_smoke_pipeline

        return build_smoke_pipeline()

    speech_to_text = None
    text_to_speech = None
    if load_voice_io:
        from voice_concierge.voice_input.stt.factory import build_speech_to_text
        from voice_concierge.voice_output.factory import build_text_to_speech

        speech_to_text = build_speech_to_text()
        text_to_speech = build_text_to_speech()
    return build_voice_concierge_pipeline(
        load_memory=load_memory,
        speech_to_text=speech_to_text,
        text_to_speech=text_to_speech,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the local browser UI and pipeline server."""

    parser = argparse.ArgumentParser(description="Serve the pipeline-connected web UI.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", default=DEFAULT_PORT, type=int)
    parser.add_argument("--memory", action="store_true", help="Enable local memory.")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Use deterministic in-memory adapters for UI review.",
    )
    parser.add_argument(
        "--voice-io",
        action="store_true",
        help="Load local STT and TTS for browser audio turns.",
    )
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
        help="Diagnostic detail written to the terminal and optional log file.",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Optional local diagnostic log file; transcript text is not logged.",
    )
    args = parser.parse_args(argv)
    _configure_logging(args.log_level, args.log_file)

    voice_io_enabled = args.voice_io and not args.demo
    model_name = (
        "deterministic demo"
        if args.demo
        else load_model_selection(DEFAULT_MODEL_SELECTION_PATH).model
    )
    try:
        pipeline = build_web_pipeline(
            load_memory=args.memory,
            load_voice_io=voice_io_enabled,
            demo=args.demo,
        )
    except ModuleNotFoundError as exc:
        if exc.name != "ollama":
            raise
        parser.error(
            "the real pipeline requires the 'ollama' Python package; activate "
            "the project virtual environment or run 'python -m pip install -e .'. "
            "Use '--demo' to start without Ollama."
        )
    server = PipelineWebServer(
        (args.host, args.port),
        pipeline,
        voice_input_enabled=voice_io_enabled,
        voice_output_enabled=voice_io_enabled,
        model_name=model_name,
    )
    print(f"Granite web UI: http://{args.host}:{args.port}")
    LOGGER.info(
        "web_server_started host=%s port=%s memory=%s voice_io=%s "
        "model=%s wake_word=false",
        args.host,
        args.port,
        args.memory,
        voice_io_enabled,
        model_name,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nGranite web UI stopped.")
    finally:
        server.server_close()
        pipeline.close()
    return 0


def _configure_logging(level: str, log_file: Path | None) -> None:
    """Configure privacy-conscious local diagnostics for the web process."""

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
        force=True,
    )
    # Keep application diagnostics focused on the local pipeline. Dependency
    # clients otherwise emit one INFO line per model-management request.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
