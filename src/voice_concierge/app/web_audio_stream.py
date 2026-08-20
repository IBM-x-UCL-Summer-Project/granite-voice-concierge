"""Bounded binary WebSocket transport for local browser microphone PCM."""

from __future__ import annotations

import json
import logging
import secrets
import socket
import struct
import time
from collections.abc import Mapping, Sequence
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from threading import Thread
from typing import Any, Protocol

from websockets.exceptions import ConnectionClosed
from websockets.sync.server import Server, ServerConnection, serve

from voice_concierge.app.web_routine_commands import (
    RoutineCommandSessionInactiveError,
    WebRoutineCommandService,
)
from voice_concierge.app.web_wake_word import (
    WakeWordSessionInactiveError,
    WebWakeWordService,
)

LOGGER = logging.getLogger(__name__)

AUDIO_STREAM_PATH = "/api/audio-stream"
AUDIO_STREAM_SUBPROTOCOL = "granite-audio-v1"
AUDIO_STREAM_HEADER_BYTES = 4
MAX_AUDIO_STREAM_PCM_BYTES = 64 * 1024
MAX_AUDIO_STREAM_MESSAGE_BYTES = AUDIO_STREAM_HEADER_BYTES + MAX_AUDIO_STREAM_PCM_BYTES
START_TIMEOUT_SECONDS = 5
SESSION_COOKIE_NAME = "granite_session"


class SessionLookup(Protocol):
    """Trusted session operation required by the stream transport."""

    def get(self, session_id: str | None) -> object | None:
        """Return a session only when it is active."""


def local_web_origins(host: str, port: int) -> tuple[str, ...]:
    """Return the browser origins allowed to open the local stream port."""

    hosts = {host}
    if host in {"0.0.0.0", "::", ""}:
        hosts = {"127.0.0.1", "localhost", "[::1]"}
    origins = {
        f"{scheme}://{origin_host}:{port}"
        for scheme in ("http", "https")
        for origin_host in hosts
    }
    return tuple(sorted(origins))


class WebAudioStreamServer:
    """Run the official threaded WebSocket server beside the local HTTP UI."""

    def __init__(
        self,
        server_address: tuple[str, int],
        *,
        sessions: SessionLookup,
        allowed_origins: Sequence[str],
        wake_word_service: WebWakeWordService | None = None,
        routine_command_service: WebRoutineCommandService | None = None,
        session_cookie_name: str = SESSION_COOKIE_NAME,
    ) -> None:
        self._sessions = sessions
        self._allowed_origins = tuple(allowed_origins)
        self._wake_word_service = wake_word_service
        self._routine_command_service = routine_command_service
        self._session_cookie_name = session_cookie_name
        self._listener = socket.create_server(server_address)
        bound_host, bound_port = self._listener.getsockname()[:2]
        self.server_address = (str(bound_host), int(bound_port))
        self._server: Server | None = None
        self._thread: Thread | None = None

    def start(self) -> None:
        """Bind the protocol handler and begin accepting connections."""

        if self._server is not None:
            return
        self._server = serve(
            self._handle_connection,
            sock=self._listener,
            origins=self._allowed_origins,
            subprotocols=[AUDIO_STREAM_SUBPROTOCOL],
            compression=None,
            max_size=MAX_AUDIO_STREAM_MESSAGE_BYTES,
            max_queue=(4, 1),
            open_timeout=START_TIMEOUT_SECONDS,
            ping_interval=20,
            ping_timeout=20,
            server_header=None,
            process_request=self._process_request,
        )
        self._thread = Thread(
            target=self._server.serve_forever,
            name="browser-audio-stream",
            daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        """Stop accepting streams and close active connections."""

        if self._server is None:
            self._listener.close()
            return
        self._server.shutdown()
        if self._thread is not None:
            self._thread.join(timeout=3)
        self._server = None
        self._thread = None

    def _process_request(
        self,
        connection: ServerConnection,
        request: Any,
    ) -> Any | None:
        if request.path != AUDIO_STREAM_PATH:
            return connection.respond(
                HTTPStatus.NOT_FOUND, "Unknown stream endpoint.\n"
            )
        return None

    def _handle_connection(self, connection: ServerConnection) -> None:
        stream_id = secrets.token_hex(12)
        if connection.subprotocol != AUDIO_STREAM_SUBPROTOCOL:
            connection.close(4406, "The audio stream subprotocol is required.")
            return
        session_id = self._session_id(connection)
        if session_id is None or self._sessions.get(session_id) is None:
            connection.close(4401, "An active local browser session is required.")
            return
        mode: str | None = None
        try:
            start_payload = self._receive_start(connection)
            mode = self._start_mode(connection, session_id, stream_id, start_payload)
            for message in connection:
                if isinstance(message, str):
                    self._handle_control(
                        connection,
                        session_id,
                        stream_id,
                        mode,
                        message,
                    )
                else:
                    self._handle_pcm_frame(
                        connection,
                        session_id,
                        stream_id,
                        mode,
                        message,
                    )
        except ConnectionClosed:
            pass
        except TimeoutError:
            LOGGER.info(
                "web_audio_stream_start_timed_out session_id=%s",
                session_id,
            )
            connection.close(4408, "The microphone stream did not start in time.")
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            LOGGER.warning(
                "web_audio_stream_rejected session_id=%s mode=%s detail=%s",
                session_id,
                mode or "none",
                exc,
            )
            connection.close(4400, str(exc)[:120])
        except (WakeWordSessionInactiveError, RoutineCommandSessionInactiveError):
            LOGGER.info(
                "web_audio_stream_replaced session_id=%s mode=%s",
                session_id,
                mode or "none",
            )
            connection.close(4409, "This microphone stream was replaced.")
        except Exception:
            LOGGER.exception(
                "web_audio_stream_failed session_id=%s mode=%s",
                session_id,
                mode or "none",
            )
            connection.close(4410, "The local audio stream failed.")
        finally:
            self._stop_mode(session_id, stream_id, mode)

    def _session_id(self, connection: ServerConnection) -> str | None:
        raw_cookie = (
            connection.request.headers.get("Cookie") if connection.request else None
        )
        if not raw_cookie:
            return None
        cookies = SimpleCookie()
        try:
            cookies.load(raw_cookie)
        except CookieError:
            return None
        session = cookies.get(self._session_cookie_name)
        return session.value if session is not None else None

    def _receive_start(self, connection: ServerConnection) -> Mapping[str, Any]:
        message = connection.recv(timeout=START_TIMEOUT_SECONDS)
        if not isinstance(message, str):
            raise ValueError("The first stream message must be JSON.")
        payload = json.loads(message)
        if not isinstance(payload, Mapping) or payload.get("type") != "start":
            raise ValueError("The first stream message must start the stream.")
        return payload

    def _start_mode(
        self,
        connection: ServerConnection,
        session_id: str,
        stream_id: str,
        payload: Mapping[str, Any],
    ) -> str:
        mode = payload.get("mode")
        if mode == "wake_word":
            if self._wake_word_service is None:
                raise ValueError("Wake-word streaming is unavailable.")
            sensitivity = payload.get("sensitivity")
            threshold = self._wake_word_service.start(
                session_id,
                sensitivity=sensitivity,
                stream_id=stream_id,
            )
            response: dict[str, Any] = {
                "type": "started",
                "mode": mode,
                "sample_rate": 16000,
                "confidence_threshold": threshold,
            }
        elif mode == "voice_command":
            if self._routine_command_service is None:
                raise ValueError("Voice-command streaming is unavailable.")
            self._routine_command_service.start(session_id, stream_id=stream_id)
            response = {"type": "started", "mode": mode, "sample_rate": 16000}
        else:
            raise ValueError("mode must be wake_word or voice_command.")
        LOGGER.debug(
            "web_audio_stream_started session_id=%s stream_id=%s mode=%s",
            session_id,
            stream_id,
            mode,
        )
        self._send_json_payload(connection, response)
        return mode

    def _send_json_payload(
        self,
        connection: ServerConnection,
        payload: Mapping[str, Any],
    ) -> None:
        # Kept as one serializer so protocol output remains deterministic in tests.
        connection.send(json.dumps(payload, separators=(",", ":"), sort_keys=True))

    def _handle_control(
        self,
        connection: ServerConnection,
        session_id: str,
        stream_id: str,
        mode: str,
        message: str,
    ) -> None:
        payload = json.loads(message)
        if not isinstance(payload, Mapping) or payload.get("type") != "reset":
            raise ValueError("Unknown audio stream control message.")
        token = payload.get("token")
        if not isinstance(token, str) or not token or len(token) > 100:
            raise ValueError("Audio stream reset token is invalid.")
        if mode == "wake_word":
            assert self._wake_word_service is not None
            threshold = self._wake_word_service.reset(
                session_id,
                stream_id=stream_id,
                sensitivity=payload.get("sensitivity"),
            )
        else:
            assert self._routine_command_service is not None
            self._routine_command_service.reset(session_id, stream_id=stream_id)
            threshold = None
        response = {"type": "reset", "token": token}
        if threshold is not None:
            response["confidence_threshold"] = threshold
        self._send_json_payload(connection, response)

    def _handle_pcm_frame(
        self,
        connection: ServerConnection,
        session_id: str,
        stream_id: str,
        mode: str,
        message: bytes,
    ) -> None:
        if len(message) <= AUDIO_STREAM_HEADER_BYTES:
            raise ValueError("Audio stream frame is empty.")
        pcm = message[AUDIO_STREAM_HEADER_BYTES:]
        if len(pcm) > MAX_AUDIO_STREAM_PCM_BYTES or len(pcm) % 2:
            raise ValueError("Audio stream frame size is invalid.")
        (sequence,) = struct.unpack(">I", message[:AUDIO_STREAM_HEADER_BYTES])
        started_at = time.monotonic()
        if mode == "wake_word":
            assert self._wake_word_service is not None
            result = self._wake_word_service.process_pcm(
                session_id,
                pcm,
                stream_id=stream_id,
            )
            payload: dict[str, Any] = {
                "type": "frame",
                "sequence": sequence,
                "detected": result.detected,
                "phrase": result.phrase,
                "confidence": result.confidence,
            }
        else:
            assert self._routine_command_service is not None
            event = self._routine_command_service.process_pcm(
                session_id,
                pcm,
                stream_id=stream_id,
            )
            payload = {
                "type": "frame",
                "sequence": sequence,
                "command": event.command if event is not None else None,
                "phrase": event.phrase if event is not None else None,
                "confidence": event.confidence if event is not None else None,
            }
        payload["processing_ms"] = round((time.monotonic() - started_at) * 1000, 1)
        self._send_json_payload(connection, payload)

    def _stop_mode(
        self,
        session_id: str,
        stream_id: str,
        mode: str | None,
    ) -> None:
        if mode == "wake_word" and self._wake_word_service is not None:
            self._wake_word_service.stop(session_id, stream_id=stream_id)
        elif mode == "voice_command" and self._routine_command_service is not None:
            self._routine_command_service.stop(session_id, stream_id=stream_id)
        if mode is not None:
            LOGGER.debug(
                "web_audio_stream_stopped session_id=%s stream_id=%s mode=%s",
                session_id,
                stream_id,
                mode,
            )
