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
from urllib.parse import urlsplit

from voice_concierge.app.adapter import (
    captured_audio_from_payload,
    handle_audio_turn,
)
from voice_concierge.app.factory import build_voice_concierge_pipeline
from voice_concierge.app.memory import MemoryManagerGateway
from voice_concierge.app.pipeline import VoiceConciergePipeline
from voice_concierge.app.serialization import (
    JsonDict,
    PayloadValidationError,
    app_pipeline_state_from_dict,
    app_pipeline_state_to_dict,
    app_turn_options_from_dict,
    app_turn_request_from_dict,
    app_turn_result_to_dict,
)
from voice_concierge.app.types import AppPipelineState
from voice_concierge.app.web_features import (
    WebFeatureServices,
    WebReminderNotifier,
    WebRoutineSessions,
    privacy_report_to_dict,
    reminder_to_dict,
    stored_memory_to_dict,
)
from voice_concierge.privacy.errors import PrivacyError
from voice_concierge.reasoning.models import (
    DEFAULT_MODEL_SELECTION_PATH,
    load_model_selection,
)
from voice_concierge.scheduling.errors import SchedulingError

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4173
MAX_REQUEST_BYTES = 16 * 1024 * 1024
MAX_WEB_SESSIONS = 32
SESSION_COOKIE_NAME = "granite_session"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WEB_DIRECTORY = REPOSITORY_ROOT / "web"
LOGGER = logging.getLogger("voice_concierge.web")

SessionTurn = Callable[
    [str, AppPipelineState | None],
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
            response, next_state = turn(resolved_id, current_state)
            self._states[resolved_id] = next_state
            self._states.move_to_end(resolved_id)
            while len(self._states) > self._max_sessions:
                self._states.popitem(last=False)
            return resolved_id, response

    def reset(self, session_id: str | None) -> tuple[str, AppPipelineState]:
        """Replace one session's transient state without changing durable data."""

        with self._lock:
            resolved_id = self._resolve_id(session_id)
            state = AppPipelineState()
            self._states[resolved_id] = state
            self._states.move_to_end(resolved_id)
            while len(self._states) > self._max_sessions:
                self._states.popitem(last=False)
            return resolved_id, state

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
        features: WebFeatureServices | None = None,
    ) -> None:
        self.pipeline = pipeline
        self.features = features or WebFeatureServices()
        self.web_directory = web_directory
        self.capabilities = {
            "text_input": True,
            "voice_input": voice_input_enabled,
            "voice_output": voice_output_enabled,
            "wake_word": False,
            **self.features.capabilities,
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
        path = urlsplit(self.path).path
        if path == "/api/health":
            self._write_json(
                HTTPStatus.OK,
                {
                    "status": "ready",
                    "capabilities": self.server.capabilities,
                    "runtime": self.server.runtime,
                },
            )
            return
        if path == "/api/privacy":
            centre = self.server.features.privacy_centre
            if centre is None:
                self._feature_unavailable("privacy_centre", "Local memory is disabled.")
                return
            try:
                self._write_json(HTTPStatus.OK, privacy_report_to_dict(centre))
            except PrivacyError as exc:
                self._domain_error("privacy_unavailable", str(exc))
            return
        if path == "/api/privacy/export":
            centre = self.server.features.privacy_centre
            if centre is None:
                self._feature_unavailable("privacy_centre", "Local memory is disabled.")
                return
            try:
                self._write_json(
                    HTTPStatus.OK,
                    {"memories": centre.export_memories()},
                )
            except PrivacyError as exc:
                self._domain_error("privacy_unavailable", str(exc))
            return
        if path == "/api/reminders":
            handler = self.server.features.reminder_handler
            if handler is None:
                self._feature_unavailable("reminders", "Local reminders are disabled.")
                return
            self._write_json(
                HTTPStatus.OK,
                {
                    "reminders": [
                        reminder_to_dict(reminder)
                        for reminder in handler.service.upcoming()
                    ]
                },
            )
            return
        if path == "/api/reminders/due":
            self._write_json(
                HTTPStatus.OK,
                {"notifications": self.server.features.due_notifications()},
            )
            return
        if path.startswith("/api/"):
            self._write_json(
                HTTPStatus.NOT_FOUND,
                {"error": {"code": "not_found", "message": "Unknown endpoint."}},
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
        path = urlsplit(self.path).path
        if path not in {"/api/turn", "/api/audio"}:
            if self._handle_control_post(path):
                return
            LOGGER.warning(
                "web_request_rejected request_id=%s endpoint=%s reason=not_found",
                request_id,
                path,
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
                lambda resolved_id, state: self._run_turn(
                    path,
                    payload,
                    resolved_id,
                    state,
                ),
            )
        except PayloadValidationError as exc:
            LOGGER.warning(
                "web_request_rejected request_id=%s endpoint=%s "
                "reason=invalid_request detail=%s",
                request_id,
                path,
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
                path,
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
            path,
            round((time.monotonic() - started_at) * 1000),
            errors if errors else "none",
            memory_status or "none",
            memory_detail or "none",
        )
        self._write_json(HTTPStatus.OK, response, session_id=session_id)

    def _run_turn(
        self,
        endpoint: str,
        payload: Mapping[str, Any],
        session_id: str,
        state: AppPipelineState | None,
    ) -> tuple[JsonDict, AppPipelineState]:
        """Replace untrusted posted state with the session's trusted state."""

        trusted_payload = dict(payload)
        trusted_payload["state"] = (
            app_pipeline_state_to_dict(state) if state is not None else None
        )
        if endpoint == "/api/turn":
            request = app_turn_request_from_dict(trusted_payload)
            response = self.server.features.route_transcript(
                self.server.pipeline,
                session_id,
                request.transcript,
                request.state,
                request.options,
            )
            if response is None:
                response = app_turn_result_to_dict(
                    self.server.pipeline.process_request(request)
                )
        else:
            response = self._run_audio_turn(trusted_payload, session_id, state)
        next_state = app_pipeline_state_from_dict(response.get("state"))
        if next_state is None:
            raise RuntimeError("Pipeline response did not contain state.")
        return response, next_state

    def _run_audio_turn(
        self,
        payload: Mapping[str, Any],
        session_id: str,
        state: AppPipelineState | None,
    ) -> JsonDict:
        """Route transcribed browser audio through the same integrated features."""

        speech_to_text = self.server.pipeline.speech_to_text
        if speech_to_text is None:
            return handle_audio_turn(payload, self.server.pipeline)
        audio = captured_audio_from_payload(payload)
        options = app_turn_options_from_dict(payload.get("options"))
        try:
            transcript = speech_to_text.transcribe(audio)
        except Exception:
            return handle_audio_turn(payload, self.server.pipeline)
        routed = self.server.features.route_transcript(
            self.server.pipeline,
            session_id,
            transcript.text,
            state,
            options,
        )
        if routed is not None:
            return routed
        return app_turn_result_to_dict(
            self.server.pipeline.process_transcript_result(
                transcript,
                state,
                synthesize=options.synthesize,
                play=options.play,
                response_length=options.response_length,
            )
        )

    def _handle_control_post(self, path: str) -> bool:
        known_paths = {
            "/api/session/reset",
            "/api/privacy/memories/edit",
            "/api/privacy/memories/delete",
            "/api/privacy/memories/forget-all",
            "/api/reminders/create",
            "/api/reminders/edit",
            "/api/reminders/snooze",
            "/api/reminders/cancel",
            "/api/reminders/cancel-all",
        }
        if path not in known_paths:
            return False
        try:
            payload = self._read_json_body()
            if path == "/api/session/reset":
                session_id, state = self.server.sessions.reset(
                    self._posted_session_id()
                )
                self.server.features.reset_session(session_id)
                self._write_json(
                    HTTPStatus.OK,
                    {"state": app_pipeline_state_to_dict(state)},
                    session_id=session_id,
                )
                return True

            if path.startswith("/api/privacy/"):
                self._handle_privacy_post(path, payload)
                return True
            self._handle_reminder_post(path, payload)
        except PayloadValidationError as exc:
            self._write_json(
                HTTPStatus.BAD_REQUEST,
                {"error": {"code": "invalid_request", "message": str(exc)}},
            )
        except (PrivacyError, SchedulingError) as exc:
            self._domain_error("operation_failed", str(exc))
        except Exception:
            LOGGER.exception("web_control_request_failed endpoint=%s", path)
            self._write_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "local_service_unavailable",
                        "message": "The requested local service is unavailable.",
                    }
                },
            )
        return True

    def _handle_privacy_post(
        self,
        path: str,
        payload: Mapping[str, Any],
    ) -> None:
        centre = self.server.features.privacy_centre
        if centre is None:
            self._feature_unavailable("privacy_centre", "Local memory is disabled.")
            return
        if path == "/api/privacy/memories/edit":
            identifier = _required_positive_int(payload, "id")
            content = _required_nonblank_string(payload, "content")
            memory = centre.edit_memory(identifier, content)
            self._write_json(
                HTTPStatus.OK,
                {"memory": stored_memory_to_dict(memory)},
            )
            return
        if path == "/api/privacy/memories/delete":
            identifier = _required_positive_int(payload, "id")
            centre.delete_memory(identifier)
            self._write_json(
                HTTPStatus.OK,
                {"deleted": True, "id": identifier},
            )
            return
        if payload.get("confirmation") != "DELETE":
            raise PayloadValidationError(
                "confirmation must be DELETE before all memories are removed."
            )
        removed = centre.delete_all()
        self._write_json(HTTPStatus.OK, {"deleted": removed})

    def _handle_reminder_post(
        self,
        path: str,
        payload: Mapping[str, Any],
    ) -> None:
        handler = self.server.features.reminder_handler
        if handler is None:
            self._feature_unavailable("reminders", "Local reminders are disabled.")
            return
        service = handler.service
        if path == "/api/reminders/create":
            transcript = _required_nonblank_string(payload, "transcript")
            reminder = service.create_from_speech(transcript)
            if reminder is None:
                raise PayloadValidationError(
                    "The reminder request must include a time."
                )
            self._write_json(
                HTTPStatus.CREATED,
                {
                    "reminder": reminder_to_dict(reminder),
                    "message": service.confirmation(reminder),
                },
            )
            return

        if path == "/api/reminders/cancel-all":
            if payload.get("confirmation") != "DELETE":
                raise PayloadValidationError(
                    "confirmation must be DELETE before all reminders are removed."
                )
            self._write_json(HTTPStatus.OK, {"cancelled": service.cancel_all()})
            return

        identifier = _required_positive_int(payload, "id")
        if path == "/api/reminders/cancel":
            service.cancel(identifier)
            self._write_json(
                HTTPStatus.OK,
                {"cancelled": True, "id": identifier},
            )
            return
        if path == "/api/reminders/snooze":
            reminder = service.snooze(
                identifier,
                _required_positive_int(payload, "seconds"),
            )
            self._write_json(
                HTTPStatus.OK,
                {"reminder": reminder_to_dict(reminder)},
            )
            return

        text = _optional_nonblank_string(payload, "text")
        due_at = _optional_int(payload, "due_at")
        if text is None and due_at is None:
            raise PayloadValidationError("text or due_at is required.")
        reminder = service.edit(identifier, text=text, due_at=due_at)
        self._write_json(
            HTTPStatus.OK,
            {"reminder": reminder_to_dict(reminder)},
        )

    def _feature_unavailable(self, code: str, message: str) -> None:
        self._write_json(
            HTTPStatus.SERVICE_UNAVAILABLE,
            {"error": {"code": code, "message": message}},
        )

    def _domain_error(self, code: str, message: str) -> None:
        self._write_json(
            HTTPStatus.BAD_REQUEST,
            {"error": {"code": code, "message": message}},
        )

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


def build_web_application(
    *,
    load_memory: bool = False,
    load_voice_io: bool = False,
    load_reminders: bool = True,
    load_guided_routines: bool = True,
    demo: bool = False,
) -> tuple[VoiceConciergePipeline, WebFeatureServices]:
    """Build the browser pipeline and the local services it exposes."""

    if demo:
        return build_web_pipeline(demo=True), WebFeatureServices()

    speech_to_text = None
    text_to_speech = None
    if load_voice_io:
        from voice_concierge.voice_input.stt.factory import build_speech_to_text
        from voice_concierge.voice_output.factory import build_text_to_speech

        speech_to_text = build_speech_to_text()
        text_to_speech = build_text_to_speech()

    memory_manager = None
    memory_gateway = None
    privacy_centre = None
    if load_memory:
        from voice_concierge.memory.factory import build_memory_manager
        from voice_concierge.privacy.centre import PrivacyCentre

        memory_manager = build_memory_manager()
        memory_gateway = MemoryManagerGateway(memory_manager)
        privacy_centre = PrivacyCentre(memory_manager)

    pipeline = build_voice_concierge_pipeline(
        memory=memory_gateway,
        speech_to_text=speech_to_text,
        text_to_speech=text_to_speech,
    )

    routine_sessions = None
    if load_guided_routines:
        from voice_concierge.reasoning.factory import build_reasoning_engine
        from voice_concierge.routines.adapter import RoutineCommandAdapter
        from voice_concierge.routines.factory import build_routine_adapter
        from voice_concierge.routines.providers import LLMRoutineProvider

        def build_adapter() -> RoutineCommandAdapter:
            engine = build_reasoning_engine()
            if memory_manager is not None:
                return build_routine_adapter(
                    memory_manager=memory_manager,
                    reasoning_engine=engine,
                )
            return RoutineCommandAdapter(LLMRoutineProvider(engine))

        routine_sessions = WebRoutineSessions(build_adapter)

    reminder_handler = None
    reminder_notifier = None
    reminder_runner = None
    if load_reminders:
        from voice_concierge.app.reminders import ReminderTurnHandler
        from voice_concierge.scheduling.factory import build_reminder_service
        from voice_concierge.scheduling.runner import ReminderRunner

        reminder_handler = ReminderTurnHandler(build_reminder_service())
        reminder_notifier = WebReminderNotifier()
        reminder_runner = ReminderRunner(
            reminder_handler.service,
            reminder_notifier,
        )

    return pipeline, WebFeatureServices(
        reminder_handler=reminder_handler,
        privacy_centre=privacy_centre,
        routine_sessions=routine_sessions,
        reminder_notifier=reminder_notifier,
        reminder_runner=reminder_runner,
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
        "--no-reminders",
        action="store_true",
        help="Disable local reminders and due-reminder delivery.",
    )
    parser.add_argument(
        "--no-guided-routines",
        action="store_true",
        help="Disable interactive guided routines.",
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
        pipeline, features = build_web_application(
            load_memory=args.memory,
            load_voice_io=voice_io_enabled,
            load_reminders=not args.no_reminders,
            load_guided_routines=not args.no_guided_routines,
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
        features=features,
    )
    features.start()
    print(f"Granite web UI: http://{args.host}:{args.port}")
    LOGGER.info(
        "web_server_started host=%s port=%s memory=%s voice_io=%s "
        "model=%s reminders=%s guided_routines=%s wake_word=false",
        args.host,
        args.port,
        args.memory,
        voice_io_enabled,
        model_name,
        not args.no_reminders and not args.demo,
        not args.no_guided_routines and not args.demo,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nGranite web UI stopped.")
    finally:
        server.server_close()
        features.close()
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


def _required_positive_int(payload: Mapping[str, Any], field: str) -> int:
    value = payload.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise PayloadValidationError(f"{field} must be a positive integer.")
    return value


def _optional_int(payload: Mapping[str, Any], field: str) -> int | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise PayloadValidationError(f"{field} must be an integer or null.")
    return value


def _required_nonblank_string(payload: Mapping[str, Any], field: str) -> str:
    value = _optional_nonblank_string(payload, field)
    if value is None:
        raise PayloadValidationError(f"{field} must be a non-empty string.")
    return value


def _optional_nonblank_string(
    payload: Mapping[str, Any],
    field: str,
) -> str | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise PayloadValidationError(f"{field} must be a non-empty string or null.")
    return value.strip()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
