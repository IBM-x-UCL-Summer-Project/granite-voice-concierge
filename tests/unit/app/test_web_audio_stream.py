"""Protocol tests for bounded binary browser microphone streaming."""

from __future__ import annotations

import json
import struct
from collections.abc import Iterator
from contextlib import contextmanager

import numpy as np
import pytest
from websockets.exceptions import ConnectionClosedError, InvalidStatus
from websockets.sync.client import ClientConnection, connect

from voice_concierge.app.web_audio_stream import (
    AUDIO_STREAM_PATH,
    AUDIO_STREAM_SUBPROTOCOL,
    WebAudioStreamServer,
    local_web_origins,
)
from voice_concierge.app.web_routine_commands import WebRoutineCommandService
from voice_concierge.app.web_wake_word import WebWakeWordService
from voice_concierge.command_control.types import CommandEvent
from voice_concierge.voice_input.wake_word_detector import WakeWordPrediction

ORIGIN = "http://127.0.0.1:4173"
SESSION_ID = "active-session"


class ActiveSessions:
    def get(self, session_id: str | None) -> object | None:
        return object() if session_id == SESSION_ID else None


class DetectingWakeWord:
    def __init__(self) -> None:
        self.thresholds: list[float | None] = []
        self.reset_count = 0

    def process_audio(
        self,
        audio: np.ndarray,
        *,
        confidence_threshold: float | None = None,
    ) -> WakeWordPrediction:
        self.thresholds.append(confidence_threshold)
        return WakeWordPrediction("hey_jarvis", 0.82)

    def reset(self) -> None:
        self.reset_count += 1


class DetectingCommandSpotter:
    def __init__(self) -> None:
        self.frames: list[bytes] = []
        self.reset_count = 0

    def process(self, frame: bytes) -> CommandEvent:
        self.frames.append(frame)
        return CommandEvent(command="pause", phrase="pause", confidence=0.91)

    def reset(self) -> None:
        self.reset_count += 1


@contextmanager
def running_audio_stream(
    *,
    wake_word_service: WebWakeWordService | None = None,
    routine_command_service: WebRoutineCommandService | None = None,
) -> Iterator[str]:
    server = WebAudioStreamServer(
        ("127.0.0.1", 0),
        sessions=ActiveSessions(),
        allowed_origins=(ORIGIN,),
        wake_word_service=wake_word_service,
        routine_command_service=routine_command_service,
    )
    server.start()
    host, port = server.server_address
    try:
        yield f"ws://{host}:{port}{AUDIO_STREAM_PATH}"
    finally:
        server.close()


def open_stream(uri: str, *, session_id: str = SESSION_ID) -> ClientConnection:
    return connect(
        uri,
        origin=ORIGIN,
        subprotocols=[AUDIO_STREAM_SUBPROTOCOL],
        additional_headers={"Cookie": f"granite_session={session_id}"},
        proxy=None,
        close_timeout=1,
    )


def decode_json(connection: ClientConnection) -> dict[str, object]:
    message = connection.recv(timeout=2)
    assert isinstance(message, str)
    payload = json.loads(message)
    assert isinstance(payload, dict)
    return payload


def pcm_frame(sequence: int, sample_count: int = 3200) -> bytes:
    return struct.pack(">I", sequence) + np.zeros(sample_count, dtype="<i2").tobytes()


def test_wake_word_stream_negotiates_binary_pcm_and_updates_sensitivity() -> None:
    detector = DetectingWakeWord()
    service = WebWakeWordService(detector)
    with running_audio_stream(wake_word_service=service) as uri:
        with open_stream(uri) as connection:
            connection.send(
                json.dumps({"type": "start", "mode": "wake_word", "sensitivity": 60})
            )
            assert decode_json(connection) == {
                "confidence_threshold": 0.3,
                "mode": "wake_word",
                "sample_rate": 16000,
                "type": "started",
            }

            connection.send(pcm_frame(7))
            result = decode_json(connection)
            processing_ms = result.pop("processing_ms")
            assert isinstance(processing_ms, int | float)
            assert processing_ms >= 0
            assert result == {
                "confidence": 0.82,
                "detected": True,
                "phrase": "hey_jarvis",
                "sequence": 7,
                "type": "frame",
            }

            connection.send(
                json.dumps({"type": "reset", "token": "settings", "sensitivity": 80})
            )
            assert decode_json(connection) == {
                "confidence_threshold": 0.2,
                "token": "settings",
                "type": "reset",
            }
            connection.send(pcm_frame(8))
            assert decode_json(connection)["sequence"] == 8

    assert detector.thresholds == [0.3, 0.2]
    assert detector.reset_count == 3


def test_voice_command_stream_returns_spotted_command() -> None:
    spotter = DetectingCommandSpotter()
    service = WebRoutineCommandService(lambda: spotter)
    with running_audio_stream(routine_command_service=service) as uri:
        with open_stream(uri) as connection:
            connection.send(json.dumps({"type": "start", "mode": "voice_command"}))
            assert decode_json(connection) == {
                "mode": "voice_command",
                "sample_rate": 16000,
                "type": "started",
            }
            connection.send(pcm_frame(23, sample_count=1600))
            result = decode_json(connection)

    assert result["type"] == "frame"
    assert result["sequence"] == 23
    assert result["command"] == "pause"
    assert result["phrase"] == "pause"
    assert result["confidence"] == 0.91
    assert spotter.frames == [np.zeros(1600, dtype="<i2").tobytes()]


def test_replaced_stream_cannot_process_or_stop_the_new_owner() -> None:
    detector = DetectingWakeWord()
    service = WebWakeWordService(detector)
    with running_audio_stream(wake_word_service=service) as uri:
        with open_stream(uri) as first, open_stream(uri) as second:
            first.send(
                json.dumps({"type": "start", "mode": "wake_word", "sensitivity": 60})
            )
            assert decode_json(first)["type"] == "started"
            second.send(
                json.dumps({"type": "start", "mode": "wake_word", "sensitivity": 60})
            )
            assert decode_json(second)["type"] == "started"

            first.send(pcm_frame(1))
            with pytest.raises(ConnectionClosedError) as closed:
                first.recv(timeout=2)
            assert closed.value.rcvd is not None
            assert closed.value.rcvd.code == 4409

            second.send(pcm_frame(2))
            assert decode_json(second)["sequence"] == 2


def test_stream_requires_allowed_origin_session_path_and_subprotocol() -> None:
    service = WebWakeWordService(DetectingWakeWord())
    with running_audio_stream(wake_word_service=service) as uri:
        with pytest.raises(InvalidStatus) as wrong_path:
            connect(
                uri.replace(AUDIO_STREAM_PATH, "/wrong"),
                origin=ORIGIN,
                subprotocols=[AUDIO_STREAM_SUBPROTOCOL],
                proxy=None,
            )
        assert wrong_path.value.response.status_code == 404

        with pytest.raises(InvalidStatus) as wrong_origin:
            connect(
                uri,
                origin="http://malicious.invalid",
                subprotocols=[AUDIO_STREAM_SUBPROTOCOL],
                proxy=None,
            )
        assert wrong_origin.value.response.status_code == 403

        with connect(
            uri,
            origin=ORIGIN,
            subprotocols=[AUDIO_STREAM_SUBPROTOCOL],
            proxy=None,
        ) as connection:
            with pytest.raises(ConnectionClosedError) as unauthorized:
                connection.recv(timeout=2)
            assert unauthorized.value.rcvd is not None
            assert unauthorized.value.rcvd.code == 4401

        with pytest.raises(InvalidStatus) as missing_protocol:
            connect(
                uri,
                origin=ORIGIN,
                additional_headers={"Cookie": f"granite_session={SESSION_ID}"},
                proxy=None,
            )
        assert missing_protocol.value.response.status_code == 400


def test_local_web_origins_never_advertise_wildcard_bind_address() -> None:
    assert local_web_origins("0.0.0.0", 4173) == (
        "http://127.0.0.1:4173",
        "http://[::1]:4173",
        "http://localhost:4173",
        "https://127.0.0.1:4173",
        "https://[::1]:4173",
        "https://localhost:4173",
    )
