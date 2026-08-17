"""Small same-origin HTTP server for the browser UI and app pipeline."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import logging
import math
import secrets
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import RLock, Thread
from typing import Any
from urllib.parse import urlsplit

from voice_concierge.app.adapter import (
    captured_audio_from_payload,
    handle_audio_turn,
)
from voice_concierge.app.factory import build_voice_concierge_pipeline
from voice_concierge.app.memory import MemoryManagerGateway
from voice_concierge.app.pipeline import VoiceConciergePipeline
from voice_concierge.app.reasoning import AppReasoningConfig
from voice_concierge.app.serialization import (
    JsonDict,
    PayloadValidationError,
    app_pipeline_state_from_dict,
    app_pipeline_state_to_dict,
    app_turn_options_from_dict,
    app_turn_request_from_dict,
    app_turn_result_to_dict,
)
from voice_concierge.app.types import AppPipelineState, ConversationTurn
from voice_concierge.app.web_features import (
    WebFeatureServices,
    WebReminderNotifier,
    WebRoutineSessions,
    privacy_report_to_dict,
    reminder_to_dict,
    stored_memory_to_dict,
)
from voice_concierge.app.web_routine_commands import (
    RoutineCommandSessionInactiveError,
    WebRoutineCommandService,
)
from voice_concierge.app.web_wake_word import (
    WakeWordSessionInactiveError,
    WebWakeWordService,
)
from voice_concierge.privacy.errors import PrivacyError
from voice_concierge.reasoning.models import (
    DEFAULT_MODEL_SELECTION_PATH,
    load_model_selection,
)
from voice_concierge.reasoning.profiles import (
    STRICT_REASONING_POLICY_PROFILE,
    SUPPORTED_REASONING_POLICY_PROFILES,
    UAT_REASONING_POLICY_PROFILE,
    ReasoningPolicyProfile,
    validate_reasoning_policy_profile,
)
from voice_concierge.scheduling.errors import SchedulingError

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4173
MAX_REQUEST_BYTES = 16 * 1024 * 1024
MAX_WEB_SESSIONS = 32
MAX_WEB_SESSION_HISTORY = 200
MAX_WAKE_WORD_FRAME_BYTES = 64 * 1024
WAKE_TIMING_EVENTS = frozenset(
    {"wake_detected", "command_capture_started", "speech_started", "command_finished"}
)
WAKE_TIMING_METRICS = frozenset(
    {
        "wake_frame_ms",
        "wake_round_trip_ms",
        "buffered_audio_ms",
        "detection_to_capture_ms",
        "wake_to_speech_ms",
        "capture_elapsed_ms",
        "captured_audio_ms",
        "end_pause_target_ms",
    }
)
SESSION_COOKIE_NAME = "granite_session"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WEB_DIRECTORY = REPOSITORY_ROOT / "web"
LOGGER = logging.getLogger("voice_concierge.web")

SessionTurn = Callable[
    [str, AppPipelineState | None],
    tuple[JsonDict, AppPipelineState],
]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class PipelineSessionStore:
    """Keep authoritative pipeline state inside the local web process."""

    def __init__(
        self,
        *,
        max_sessions: int = MAX_WEB_SESSIONS,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if max_sessions <= 0:
            raise ValueError("max_sessions must be positive.")
        self._max_sessions = max_sessions
        self._clock = clock
        self._states: OrderedDict[str, AppPipelineState] = OrderedDict()
        self._histories: OrderedDict[str, tuple[ConversationTurn, ...]] = OrderedDict()
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
            user_sent_at = self._clock().astimezone(UTC).isoformat()
            response, next_state = turn(resolved_id, current_state)
            history = self._histories.get(resolved_id, ())
            completed_turn = _completed_conversation_turn(
                response,
                user_sent_at=user_sent_at,
                assistant_received_at=self._clock().astimezone(UTC).isoformat(),
            )
            if completed_turn is not None:
                history = (*history, completed_turn)[-MAX_WEB_SESSION_HISTORY:]
            self._states[resolved_id] = next_state
            self._histories[resolved_id] = history
            response["session_history"] = [
                _session_turn_to_dict(item) for item in history
            ]
            self._touch_and_evict(resolved_id)
            return resolved_id, response

    def reset(self, session_id: str | None) -> tuple[str, AppPipelineState]:
        """Replace one session's transient state without changing durable data."""

        with self._lock:
            resolved_id = self._resolve_id(session_id)
            state = AppPipelineState()
            self._states[resolved_id] = state
            self._histories[resolved_id] = ()
            self._touch_and_evict(resolved_id)
            return resolved_id, state

    def ensure(self, session_id: str | None) -> str:
        """Return a valid server-owned session without changing its state."""

        with self._lock:
            resolved_id = self._resolve_id(session_id)
            if resolved_id not in self._states:
                self._states[resolved_id] = AppPipelineState()
                self._histories[resolved_id] = ()
            self._touch_and_evict(resolved_id)
            return resolved_id

    def get(self, session_id: str | None) -> AppPipelineState | None:
        """Return one trusted transient state without creating a session."""

        with self._lock:
            if session_id is None:
                return None
            return self._states.get(session_id)

    def history(self, session_id: str | None) -> tuple[ConversationTurn, ...]:
        """Return the complete bounded display transcript for one session."""

        with self._lock:
            if session_id is None:
                return ()
            return self._histories.get(session_id, ())

    def snapshot(
        self,
        session_id: str | None,
    ) -> tuple[str, AppPipelineState, tuple[ConversationTurn, ...]]:
        """Return or create one transient browser session for page restoration."""

        with self._lock:
            resolved_id = self.ensure(session_id)
            return (
                resolved_id,
                self._states[resolved_id],
                self._histories[resolved_id],
            )

    def _touch_and_evict(self, session_id: str) -> None:
        self._states.move_to_end(session_id)
        self._histories.move_to_end(session_id)
        while len(self._states) > self._max_sessions:
            evicted_id, _ = self._states.popitem(last=False)
            self._histories.pop(evicted_id, None)

    def _resolve_id(self, session_id: str | None) -> str:
        if session_id is not None and session_id in self._states:
            return session_id
        while True:
            generated = secrets.token_urlsafe(24)
            if generated not in self._states:
                return generated


def _completed_conversation_turn(
    response: Mapping[str, Any],
    *,
    user_sent_at: str,
    assistant_received_at: str,
) -> ConversationTurn | None:
    """Extract the completed exchange already validated by the app boundary."""

    transcript = response.get("transcript")
    spoken_response = response.get("spoken_response")
    if response.get("automatic_routine") is True and isinstance(spoken_response, str):
        return ConversationTurn(
            user_transcript="",
            assistant_response=spoken_response,
            assistant_received_at=assistant_received_at,
        )
    if not isinstance(transcript, Mapping) or not isinstance(spoken_response, str):
        return None
    text = transcript.get("text")
    if not isinstance(text, str) or not text.strip() or not spoken_response.strip():
        return None
    return ConversationTurn(
        user_transcript=" ".join(text.strip().split()),
        assistant_response=spoken_response,
        user_sent_at=user_sent_at,
        assistant_received_at=assistant_received_at,
    )


def _session_turn_to_dict(turn: ConversationTurn) -> JsonDict:
    """Serialize display history with ephemeral send/receive timestamps."""

    return {
        "user_transcript": turn.user_transcript,
        "assistant_response": turn.assistant_response,
        "user_sent_at": turn.user_sent_at,
        "assistant_received_at": turn.assistant_received_at,
    }


class StartupReadiness:
    """Run local model warm-up in the background and expose safe UI status."""

    def __init__(self, warm_up: Callable[[], None] | None = None) -> None:
        self._warm_up = warm_up
        self._status = "ready" if warm_up is None else "starting"
        self._message = (
            "Local engine is ready."
            if warm_up is None
            else "Loading the local reasoning model…"
        )
        self._lock = RLock()
        if warm_up is not None:
            Thread(target=self._run, name="web-startup-warmup", daemon=True).start()

    @property
    def ready(self) -> bool:
        with self._lock:
            return self._status == "ready"

    def snapshot(self) -> dict[str, str]:
        with self._lock:
            return {"status": self._status, "message": self._message}

    def _run(self) -> None:
        try:
            assert self._warm_up is not None
            self._warm_up()
        except Exception:
            LOGGER.exception("web_startup_warmup_failed")
            with self._lock:
                self._status = "error"
                self._message = (
                    "The local engine could not start. "
                    "Check the server log, then retry."
                )
            return
        with self._lock:
            self._status = "ready"
            self._message = "Local engine is ready."


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
        policy_profile: ReasoningPolicyProfile = STRICT_REASONING_POLICY_PROFILE,
        features: WebFeatureServices | None = None,
        wake_word_service: WebWakeWordService | None = None,
        routine_command_service: WebRoutineCommandService | None = None,
        warm_up: Callable[[], None] | None = None,
    ) -> None:
        resolved_policy_profile = validate_reasoning_policy_profile(policy_profile)
        self.pipeline = pipeline
        self.features = features or WebFeatureServices()
        self.wake_word_service = wake_word_service
        self.routine_command_service = routine_command_service
        self.web_directory = web_directory
        self.capabilities = {
            "text_input": True,
            "voice_input": voice_input_enabled,
            "voice_output": voice_output_enabled,
            "wake_word": wake_word_service is not None and voice_input_enabled,
            "routine_barge_in": (
                routine_command_service is not None and voice_input_enabled
            ),
            **self.features.capabilities,
        }
        self.runtime = {
            "model": model_name,
            "policy_profile": resolved_policy_profile,
        }
        self.sessions = PipelineSessionStore()
        super().__init__(server_address, PipelineRequestHandler)
        self.readiness = StartupReadiness(warm_up)


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
            readiness = self.server.readiness.snapshot()
            self._write_json(
                HTTPStatus.OK,
                {
                    **readiness,
                    "capabilities": self.server.capabilities,
                    "runtime": self.server.runtime,
                },
            )
            return
        if path == "/api/session":
            session_id, state, history = self.server.sessions.snapshot(
                self._posted_session_id()
            )
            self._write_json(
                HTTPStatus.OK,
                {
                    "state": app_pipeline_state_to_dict(state),
                    "routine": self.server.features.routine_snapshot(session_id),
                    "session_history": [
                        _session_turn_to_dict(turn) for turn in history
                    ],
                },
                session_id=session_id,
            )
            return
        if path == "/api/session/export":
            state = self.server.sessions.get(self._posted_session_id())
            history = self.server.sessions.history(self._posted_session_id())
            if state is None or not history:
                self._write_json(
                    HTTPStatus.BAD_REQUEST,
                    {
                        "error": {
                            "code": "empty_conversation",
                            "message": "There is no conversation to export yet.",
                        }
                    },
                )
                return
            exported_at = datetime.now(UTC)
            self._write_json_download(
                {
                    "format": "granite-chat",
                    "version": 2,
                    "exported_at": exported_at.isoformat(),
                    "privacy": {
                        "session_scope": "temporary",
                        "persisted_by_application": False,
                        "audio_included": False,
                    },
                    "context": {"mode": state.context.mode},
                    "messages": [
                        message
                        for turn in history
                        for message in (
                            {
                                "role": "user",
                                "content": turn.user_transcript,
                                "timestamp": turn.user_sent_at,
                            },
                            {
                                "role": "assistant",
                                "content": turn.assistant_response,
                                "timestamp": turn.assistant_received_at,
                            },
                        )
                        if message["content"]
                    ],
                },
                filename=f"granite-chat-{exported_at.date().isoformat()}.json",
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

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        """Keep continuous local wake-word frames out of terminal noise."""

        if urlsplit(self.path).path in {
            "/api/wake-word/frame",
            "/api/routine-command/frame",
            "/api/diagnostics/wake-timing",
        }:
            return
        super().log_request(code, size)

    def do_POST(self) -> None:  # noqa: N802
        request_id = secrets.token_hex(4)
        started_at = time.monotonic()
        path = urlsplit(self.path).path
        if path in {"/api/turn", "/api/audio"} and not self.server.readiness.ready:
            readiness = self.server.readiness.snapshot()
            self._write_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {
                    "error": {
                        "code": f"engine_{readiness['status']}",
                        "message": readiness["message"],
                    }
                },
            )
            return
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
            automatic_routine = (
                trusted_payload.get("automatic_routine") is True
                and request.transcript.strip().casefold() == "next"
                and bool(
                    self.server.features.routine_snapshot(session_id).get("active")
                )
            )
            response = self.server.features.route_transcript(
                self.server.pipeline,
                session_id,
                request.transcript,
                request.state,
                request.options,
                record_conversation=not automatic_routine,
            )
            if response is None:
                response = app_turn_result_to_dict(
                    self.server.pipeline.process_request(request)
                )
            elif automatic_routine:
                response["automatic_routine"] = True
        else:
            response = self._run_audio_turn(trusted_payload, session_id, state)
        response["routine"] = self.server.features.routine_snapshot(session_id)
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
            "/api/wake-word/start",
            "/api/wake-word/frame",
            "/api/wake-word/stop",
            "/api/routine-command/start",
            "/api/routine-command/frame",
            "/api/routine-command/reset",
            "/api/routine-command/stop",
            "/api/diagnostics/wake-timing",
        }
        if path not in known_paths:
            return False
        try:
            payload = self._read_json_body()
            if path == "/api/diagnostics/wake-timing":
                self._handle_wake_timing_post(payload)
                return True
            if path.startswith("/api/wake-word/"):
                self._handle_wake_word_post(path, payload)
                return True
            if path.startswith("/api/routine-command/"):
                self._handle_routine_command_post(path, payload)
                return True
            if path == "/api/session/reset":
                session_id, state = self.server.sessions.reset(
                    self._posted_session_id()
                )
                if self.server.routine_command_service is not None:
                    self.server.routine_command_service.stop(session_id)
                self.server.features.reset_session(session_id)
                self._write_json(
                    HTTPStatus.OK,
                    {
                        "state": app_pipeline_state_to_dict(state),
                        "session_history": [],
                    },
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
        except WakeWordSessionInactiveError as exc:
            self._write_json(
                HTTPStatus.CONFLICT,
                {"error": {"code": "wake_word_inactive", "message": str(exc)}},
            )
        except RoutineCommandSessionInactiveError as exc:
            self._write_json(
                HTTPStatus.CONFLICT,
                {"error": {"code": "routine_command_inactive", "message": str(exc)}},
            )
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

    def _handle_wake_timing_post(self, payload: Mapping[str, Any]) -> None:
        """Write privacy-safe browser wake/VAD timings at DEBUG level."""

        event = payload.get("event")
        if not isinstance(event, str) or event not in WAKE_TIMING_EVENTS:
            raise PayloadValidationError("event is not a supported wake timing event.")
        metrics: dict[str, float] = {}
        for name in sorted(WAKE_TIMING_METRICS):
            value = payload.get(name)
            if value is None:
                continue
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
                or value > 300_000
            ):
                raise PayloadValidationError(
                    f"{name} must be a finite duration between 0 and 300000 ms."
                )
            metrics[name] = round(float(value), 1)
        diagnostic = " ".join(f"{name}={value:.1f}" for name, value in metrics.items())
        LOGGER.debug(
            "web_wake_timing event=%s%s",
            event,
            f" {diagnostic}" if diagnostic else "",
        )
        self._write_json(HTTPStatus.OK, {"recorded": True})

    def _handle_routine_command_post(
        self,
        path: str,
        payload: Mapping[str, Any],
    ) -> None:
        service = self.server.routine_command_service
        if service is None:
            self._feature_unavailable(
                "routine_barge_in",
                "Hands-free routine controls require local voice I/O.",
            )
            return

        posted_session_id = self._posted_session_id()
        if path == "/api/routine-command/start":
            session_id = self.server.sessions.ensure(posted_session_id)
            service.start(session_id)
            self._write_json(
                HTTPStatus.OK,
                {"active": True, "sample_rate": 16000},
                session_id=session_id,
            )
            return
        if path == "/api/routine-command/stop":
            self._write_json(
                HTTPStatus.OK,
                {"active": not service.stop(posted_session_id)},
            )
            return
        if path == "/api/routine-command/reset":
            service.reset(posted_session_id)
            self._write_json(HTTPStatus.OK, {"active": True})
            return

        encoded = payload.get("pcm_base64")
        if not isinstance(encoded, str) or not encoded:
            raise PayloadValidationError("pcm_base64 must be a non-empty string.")
        try:
            pcm = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise PayloadValidationError("pcm_base64 must be valid base64.") from exc
        if len(pcm) > MAX_WAKE_WORD_FRAME_BYTES:
            raise PayloadValidationError("Routine command audio frame is too large.")
        try:
            event = service.process_pcm(posted_session_id, pcm)
        except ValueError as exc:
            raise PayloadValidationError(str(exc)) from exc
        self._write_json(
            HTTPStatus.OK,
            {
                "command": event.command if event is not None else None,
                "phrase": event.phrase if event is not None else None,
                "confidence": event.confidence if event is not None else None,
            },
        )

    def _handle_wake_word_post(
        self,
        path: str,
        payload: Mapping[str, Any],
    ) -> None:
        service = self.server.wake_word_service
        if service is None:
            self._feature_unavailable(
                "wake_word",
                "Wake-word mode is disabled. Restart the server with --voice-io.",
            )
            return

        posted_session_id = self._posted_session_id()
        if path == "/api/wake-word/start":
            session_id = self.server.sessions.ensure(posted_session_id)
            sensitivity = payload.get("sensitivity", 60)
            try:
                threshold = service.start(session_id, sensitivity=sensitivity)
            except ValueError as exc:
                raise PayloadValidationError(str(exc)) from exc
            self._write_json(
                HTTPStatus.OK,
                {
                    "active": True,
                    "sample_rate": 16000,
                    "confidence_threshold": threshold,
                },
                session_id=session_id,
            )
            return

        if path == "/api/wake-word/stop":
            self._write_json(
                HTTPStatus.OK,
                {"active": not service.stop(posted_session_id)},
            )
            return

        encoded = payload.get("pcm_base64")
        if not isinstance(encoded, str) or not encoded:
            raise PayloadValidationError("pcm_base64 must be a non-empty string.")
        try:
            pcm = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise PayloadValidationError("pcm_base64 must be valid base64.") from exc
        if len(pcm) > MAX_WAKE_WORD_FRAME_BYTES:
            raise PayloadValidationError("Wake-word audio frame is too large.")
        processing_started_at = time.monotonic()
        try:
            result = service.process_pcm(posted_session_id, pcm)
        except ValueError as exc:
            raise PayloadValidationError(str(exc)) from exc
        processing_ms = (time.monotonic() - processing_started_at) * 1000
        if result.detected:
            LOGGER.debug(
                "web_wake_detection server_processing_ms=%.1f confidence=%.3f",
                processing_ms,
                result.confidence or 0.0,
            )
        self._write_json(
            HTTPStatus.OK,
            {
                "detected": result.detected,
                "phrase": result.phrase,
                "confidence": result.confidence,
            },
        )

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

    def _write_json_download(
        self,
        payload: Mapping[str, Any],
        *,
        filename: str,
    ) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def build_web_pipeline(
    *,
    load_memory: bool = True,
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
    load_memory: bool = True,
    load_voice_io: bool = False,
    load_reminders: bool = True,
    load_guided_routines: bool = True,
    demo: bool = False,
    policy_profile: ReasoningPolicyProfile = UAT_REASONING_POLICY_PROFILE,
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
        AppReasoningConfig(policy_profile=policy_profile),
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
            engine = build_reasoning_engine(policy_profile=policy_profile)
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
        reminder_notifier = WebReminderNotifier(text_to_speech)
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
    memory_group = parser.add_mutually_exclusive_group()
    memory_group.add_argument(
        "--memory",
        dest="memory",
        action="store_true",
        help="Enable local memory (the default).",
    )
    memory_group.add_argument(
        "--no-memory",
        dest="memory",
        action="store_false",
        help="Disable local memory and the browser privacy centre.",
    )
    parser.set_defaults(memory=True)
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Use deterministic in-memory adapters for UI review.",
    )
    parser.add_argument(
        "--policy-profile",
        choices=sorted(SUPPORTED_REASONING_POLICY_PROFILES),
        default=UAT_REASONING_POLICY_PROFILE,
        help=(
            "Reasoning safeguards: uat_relaxed favors natural test responses; "
            "strict enforces exact provenance metadata."
        ),
    )
    parser.add_argument(
        "--voice-io",
        action="store_true",
        help="Load local STT, TTS, and browser wake-word audio support.",
    )
    parser.add_argument(
        "--no-wake-word",
        action="store_true",
        help="Disable browser wake-word mode while keeping push-to-talk voice I/O.",
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
            policy_profile=args.policy_profile,
        )
    except ModuleNotFoundError as exc:
        if exc.name != "ollama":
            raise
        parser.error(
            "the real pipeline requires the 'ollama' Python package; activate "
            "the project virtual environment or run 'python -m pip install -e .'. "
            "Use '--demo' to start without Ollama."
        )
    wake_word_service = None
    wake_word_enabled = voice_io_enabled and not args.no_wake_word
    if wake_word_enabled:
        from voice_concierge.voice_input.wake_word_detector import WakeWordDetector

        wake_word_service = WebWakeWordService(WakeWordDetector(download_models=False))
    routine_command_service = None
    if voice_io_enabled and not args.no_guided_routines:
        from voice_concierge.command_control.factory import build_vosk_command_spotter
        from voice_concierge.command_control.stabilizer import StableCommandSpotter

        routine_command_service = WebRoutineCommandService(
            lambda: StableCommandSpotter(build_vosk_command_spotter())
        )
    server = PipelineWebServer(
        (args.host, args.port),
        pipeline,
        voice_input_enabled=voice_io_enabled,
        voice_output_enabled=voice_io_enabled,
        model_name=model_name,
        policy_profile=args.policy_profile,
        features=features,
        wake_word_service=wake_word_service,
        routine_command_service=routine_command_service,
        warm_up=None if args.demo else pipeline.warm_up,
    )
    features.start()
    print(f"Granite web UI: http://{args.host}:{args.port}")
    LOGGER.info(
        "web_server_started host=%s port=%s memory=%s voice_io=%s "
        "model=%s policy_profile=%s reminders=%s guided_routines=%s wake_word=%s",
        args.host,
        args.port,
        args.memory,
        voice_io_enabled,
        model_name,
        args.policy_profile,
        not args.no_reminders and not args.demo,
        not args.no_guided_routines and not args.demo,
        wake_word_enabled,
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
