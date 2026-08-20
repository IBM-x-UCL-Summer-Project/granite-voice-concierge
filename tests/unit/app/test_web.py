"""Tests for the same-origin browser UI server."""

from __future__ import annotations

import base64
import json
import logging
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import (
    HTTPCookieProcessor,
    OpenerDirector,
    Request,
    build_opener,
    urlopen,
)

import numpy as np
import pytest

from voice_concierge.app import web as web_module
from voice_concierge.app.memory import MemoryManagerGateway
from voice_concierge.app.pipeline import VoiceConciergePipeline
from voice_concierge.app.reminders import ReminderTurnHandler
from voice_concierge.app.serialization import app_pipeline_state_to_dict
from voice_concierge.app.smoke import SmokeReasoningService, build_smoke_pipeline
from voice_concierge.app.types import AppPipelineState
from voice_concierge.app.web import PipelineWebServer
from voice_concierge.app.web_features import (
    WebFeatureServices,
    WebReminderNotifier,
    WebRoutineSessions,
)
from voice_concierge.app.web_routine_commands import WebRoutineCommandService
from voice_concierge.app.web_wake_word import WebWakeWordService
from voice_concierge.audio.types import CapturedAudio
from voice_concierge.command_control.types import CommandEvent
from voice_concierge.memory import LocalMemoryConfig, build_memory_manager
from voice_concierge.privacy.centre import PrivacyCentre
from voice_concierge.reasoning.types import MemoryAction
from voice_concierge.routines.adapter import RoutineCommandAdapter
from voice_concierge.routines.types import Routine, RoutineStep
from voice_concierge.scheduling.runner import ReminderRunner
from voice_concierge.scheduling.service import ReminderService
from voice_concierge.scheduling.store import ReminderStore
from voice_concierge.scheduling.types import Reminder, Schedule
from voice_concierge.voice_input.wake_word_detector import WakeWordPrediction

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
WEB_APPLICATION_SCRIPTS = (
    "app-context.js",
    "diagnostics.js",
    "settings.js",
    "conversation.js",
    "api-client.js",
    "playback.js",
    "audio-capture.js",
    "voice-input.js",
    "voice-commands.js",
    "wake-word.js",
    "session.js",
    "local-data.js",
    "app.js",
)


def read_web_application_scripts() -> str:
    return "\n".join(
        (REPOSITORY_ROOT / "web" / name).read_text(encoding="utf-8")
        for name in WEB_APPLICATION_SCRIPTS
    )


class DeterministicEmbeddingService:
    def get_embedding(self, content: str) -> list[float]:
        return [1.0, 0.0, 0.0, 0.0]


class DeterministicRoutineProvider:
    def get_routine(self, request: str) -> Routine:
        return Routine(
            name="morning stretch",
            steps=(RoutineStep("Stand comfortably."), RoutineStep("Reach up.")),
        )


class FakeWakeWordDetector:
    def __init__(self) -> None:
        self.detect = False
        self.reset_count = 0

    def process_audio(self, audio, *, confidence_threshold=None):
        if self.detect:
            return WakeWordPrediction("hey_jarvis", 0.8)
        return None

    def reset(self) -> None:
        self.reset_count += 1


@contextmanager
def running_server(
    pipeline: VoiceConciergePipeline | None = None,
    *,
    features: WebFeatureServices | None = None,
    wake_word_service: WebWakeWordService | None = None,
    routine_command_service: WebRoutineCommandService | None = None,
    warm_up: Callable[[], None] | None = None,
    voice_input_enabled: bool = False,
    diagnostics_enabled: bool = False,
) -> Iterator[str]:
    resolved_pipeline = pipeline or build_smoke_pipeline()
    server = PipelineWebServer(
        ("127.0.0.1", 0),
        resolved_pipeline,
        model_name="smoke model",
        features=features,
        wake_word_service=wake_word_service,
        routine_command_service=routine_command_service,
        warm_up=warm_up,
        voice_input_enabled=voice_input_enabled,
        diagnostics_enabled=diagnostics_enabled,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        if features is not None:
            features.close()
        resolved_pipeline.close()
        thread.join(timeout=2)


def read_json(
    url: str,
    *,
    payload: dict[str, object] | None = None,
    opener: OpenerDirector | None = None,
) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
    )
    open_request = opener.open if opener is not None else urlopen
    with open_request(request, timeout=2) as response:
        return json.load(response)


def test_health_reports_pipeline_capabilities() -> None:
    with running_server() as base_url:
        response = read_json(f"{base_url}/api/health")

    assert response == {
        "status": "ready",
        "message": "Local engine is ready.",
        "capabilities": {
            "text_input": True,
            "voice_input": False,
            "voice_output": False,
            "wake_word": False,
            "routine_barge_in": False,
            "playback_barge_in": False,
            "diagnostics": False,
            "reminders": False,
            "guided_routines": False,
            "privacy_centre": False,
        },
        "runtime": {"model": "smoke model", "policy_profile": "strict"},
    }


def test_speech_preview_uses_configured_local_synthesizer() -> None:
    class FakeSpeech:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def synthesize(self, text: str) -> CapturedAudio:
            self.calls.append(text)
            return CapturedAudio(samples=np.ones(160, dtype=np.int16))

    speech = FakeSpeech()
    pipeline = VoiceConciergePipeline(
        SmokeReasoningService(),
        text_to_speech=speech,
    )

    with running_server(pipeline) as base_url:
        response = read_json(f"{base_url}/api/speech/preview", payload={})

    assert speech.calls == ["Hello. This is how Granite will sound."]
    assert response["text"] == speech.calls[0]
    assert response["audio"]["wav_base64"]


def test_speech_preview_reports_when_local_voice_is_disabled() -> None:
    with running_server() as base_url:
        with pytest.raises(HTTPError) as error:
            read_json(f"{base_url}/api/speech/preview", payload={})
        response = json.load(error.value)

    assert error.value.code == 503
    assert response["error"]["code"] == "voice_output"


def test_speech_preview_reports_local_synthesis_failure() -> None:
    class FailingSpeech:
        def synthesize(self, text: str) -> CapturedAudio:
            raise RuntimeError("synthesis failed")

    pipeline = VoiceConciergePipeline(
        SmokeReasoningService(),
        text_to_speech=FailingSpeech(),
    )

    with running_server(pipeline) as base_url:
        with pytest.raises(HTTPError) as error:
            read_json(f"{base_url}/api/speech/preview", payload={})
        response = json.load(error.value)

    assert error.value.code == 503
    assert response["error"]["code"] == "voice_output_failed"


def test_debug_health_enables_browser_diagnostic_forwarding() -> None:
    with running_server(diagnostics_enabled=True) as base_url:
        response = read_json(f"{base_url}/api/health")

    assert response["capabilities"]["diagnostics"] is True


def test_api_response_echoes_valid_client_request_id() -> None:
    with running_server() as base_url:
        request = Request(
            f"{base_url}/api/health",
            headers={"X-Client-Request-ID": "browser-request-123"},
        )
        with urlopen(request, timeout=2) as response:
            request_id = response.headers.get("X-Request-ID")

    assert request_id == "browser-request-123"


def test_browser_diagnostic_event_logs_full_details(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG, logger="voice_concierge.web"):
        with running_server(diagnostics_enabled=True) as base_url:
            response = read_json(
                f"{base_url}/api/diagnostics/client-event",
                payload={
                    "timestamp": "2026-08-17T12:00:00.000Z",
                    "browser_id": "browser-123",
                    "level": "info",
                    "event": "turn_response_received",
                    "details": {
                        "transcript": "remember my appointment",
                        "spoken_response": "I can remember that.",
                    },
                },
            )

    assert response == {"recorded": True}
    assert "browser_event" in caplog.text
    assert "browser_id=browser-123" in caplog.text
    assert "event=turn_response_received" in caplog.text
    assert "remember my appointment" in caplog.text
    assert "I can remember that." in caplog.text


def test_diagnostic_payload_keeps_text_and_summarizes_encoded_audio() -> None:
    summarized = json.loads(
        web_module._diagnostic_json(
            {
                "transcript": "keep this prompt",
                "wav_base64": "QUJDRA==",
                "nested": {"pcm_base64": "AAAA"},
            }
        )
    )

    assert summarized == {
        "nested": {"pcm_base64": "<base64 characters=4>"},
        "transcript": "keep this prompt",
        "wav_base64": "<base64 characters=8>",
    }


def test_web_application_uses_relaxed_uat_policy_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = build_smoke_pipeline()
    captured: dict[str, object] = {}

    def fake_build_pipeline(config=None, **_kwargs: object):
        captured["config"] = config
        return pipeline

    monkeypatch.setattr(
        web_module, "build_voice_concierge_pipeline", fake_build_pipeline
    )

    built_pipeline, features = web_module.build_web_application(
        load_memory=False,
        load_reminders=False,
        load_guided_routines=False,
    )

    try:
        assert built_pipeline is pipeline
        assert captured["config"].policy_profile == "uat_relaxed"
    finally:
        features.close()
        pipeline.close()


def test_static_ui_disables_browser_cache() -> None:
    with running_server() as base_url:
        with urlopen(f"{base_url}/", timeout=2) as response:
            html = response.read().decode("utf-8")
            cache_control = response.headers.get("Cache-Control")
        worklet_assets = []
        for asset in ("audio-capture-worklet.mjs", "audio-resampler.mjs"):
            with urlopen(f"{base_url}/{asset}", timeout=2) as response:
                worklet_assets.append(
                    (response.status, response.headers.get("Cache-Control"))
                )

    assert cache_control == "no-store"
    assert "./playback-policy.js?v=20260820" in html
    assert "./wake-capture-policy.js?v=20260820" in html
    for name in WEB_APPLICATION_SCRIPTS:
        assert f"./{name}?v=20260820-" in html
    assert "./app.js?v=20260820-3" in html
    assert "./styles.css?v=20260820-2" in html

    assert worklet_assets == [(200, "no-store"), (200, "no-store")]


def test_browser_microphone_capture_uses_audio_worklet() -> None:
    script = read_web_application_scripts()

    assert "openMicrophoneCapture({" in script
    assert "getSupportedConstraints" in script
    assert "getSettings" in script
    assert "createScriptProcessor" not in script
    assert "onaudioprocess" not in script


def test_browser_never_persists_conversation_state() -> None:
    script = read_web_application_scripts()

    assert "localStorage.setItem(LEGACY_PIPELINE_STORAGE_KEY" not in script
    assert "localStorage.removeItem(LEGACY_PIPELINE_STORAGE_KEY)" in script
    assert 'connection: "connecting"' in script
    assert "The local assistant is disconnected. Reconnecting…" in script


def test_browser_tts_fallback_only_uses_a_local_voice() -> None:
    playback = (REPOSITORY_ROOT / "web" / "playback.js").read_text(encoding="utf-8")

    assert ".filter((voice) => voice.localService)" in playback
    assert 'response.errors.includes("tts_failed")' in playback


def test_setup_voice_preview_checks_local_synthesis_before_browser_fallback() -> None:
    html = (REPOSITORY_ROOT / "web" / "index.html").read_text(encoding="utf-8")
    script = read_web_application_scripts()

    assert "Preview browser voice" not in html
    assert "Test local voice" in html
    assert 'requestJson("/api/speech/preview", {})' in script
    assert "Piper preview failed; using the offline browser voice" in script


def test_local_data_actions_use_an_application_owned_dialog() -> None:
    html = (REPOSITORY_ROOT / "web" / "index.html").read_text(encoding="utf-8")
    script = read_web_application_scripts()

    assert 'id="action-dialog"' in html
    assert 'id="action-input"' in html
    assert "requestAction({" in script
    assert "window.prompt(" not in script
    assert "window.confirm(" not in script


def test_browser_exposes_waiting_wake_mode_and_private_chat_export() -> None:
    html = (REPOSITORY_ROOT / "web" / "index.html").read_text(encoding="utf-8")
    script = read_web_application_scripts()

    assert 'id="wake-word-screen"' in html
    assert 'id="wake-push-button"' in html
    assert 'id="wake-quick-pause"' in html
    assert 'id="wake-quick-follow-up"' in html
    assert 'id="wake-quick-auto-follow-up"' in html
    assert 'id="wake-auto-follow-up"' in html
    assert 'id="wake-conversation-toggle"' in html
    assert 'id="wake-conversation-panel"' in html
    assert 'id="startup-screen"' in html
    assert 'id="export-chat-button"' in html
    assert "Transcribing and thinking locally" in script
    assert "beginWakeCommand({ followUp: true })" in script
    assert "response && state.settings.wake_auto_follow_up" in script
    assert "WAKE_COMMAND_ARM_DELAY_MILLISECONDS" in script
    assert "preRollChunks" in script
    assert "state.wakeWord.commandChunks = capture.retainedChunks" in script
    assert "renderWakeConversation();" in script
    assert 'suppressPlayback: command === "pause"' in script
    assert (
        "playback.audio.pause();\n    state.routine.playbackPaused = true" not in script
    )
    assert 'link.href = "/api/session/export"' in script
    assert "localStorage.setItem(LEGACY_PIPELINE_STORAGE_KEY" not in script


def test_wake_mode_keeps_header_actions_interactive() -> None:
    html = (REPOSITORY_ROOT / "web" / "index.html").read_text(encoding="utf-8")
    script = read_web_application_scripts()
    styles = (REPOSITORY_ROOT / "web" / "styles.css").read_text(encoding="utf-8")

    assert "elements.wakeWordScreen.show();" in script
    assert "elements.wakeWordScreen.showModal();" not in script
    assert 'id="wake-word-button" type="button" aria-pressed="false"' in html
    assert "if (elements.wakeWordScreen.open) stopWakeWordMode();" in script
    assert ".topbar {\n  z-index: 40;" in styles
    assert ".wake-word-screen { z-index: 35;" in styles


def test_browser_applies_stop_pause_and_resume_to_every_spoken_response() -> None:
    script = read_web_application_scripts()

    assert "async function handlePlaybackVoiceCommand(command)" in script
    assert 'command === "stop"' in script
    assert 'command === "pause"' in script
    assert "await resumePlayback()" in script
    assert "playbackActive: Boolean(state.playback)" in script
    assert "if (commandControlActive) enqueueVoiceCommandFrame(samples)" in script


def test_browser_entry_point_is_not_a_monolith() -> None:
    entry_point = (REPOSITORY_ROOT / "web" / "app.js").read_text(encoding="utf-8")

    assert len(entry_point.splitlines()) < 300
    assert len(WEB_APPLICATION_SCRIPTS) >= 10


def test_startup_warmup_exposes_loading_before_ready() -> None:
    started = threading.Event()
    release = threading.Event()

    def warm_up() -> None:
        started.set()
        release.wait(timeout=2)

    with running_server(warm_up=warm_up) as base_url:
        assert started.wait(timeout=1)
        loading = read_json(f"{base_url}/api/health")
        with pytest.raises(HTTPError) as error:
            read_json(f"{base_url}/api/turn", payload={"transcript": "hello"})
        release.set()
        deadline = time.monotonic() + 1
        ready = loading
        while ready["status"] != "ready" and time.monotonic() < deadline:
            time.sleep(0.01)
            ready = read_json(f"{base_url}/api/health")

    assert loading["status"] == "starting"
    assert "Loading" in loading["message"]
    assert error.value.code == 503
    assert ready["status"] == "ready"


def test_browser_wake_word_api_keeps_detector_on_session(
    caplog: pytest.LogCaptureFixture,
) -> None:
    detector = FakeWakeWordDetector()
    service = WebWakeWordService(detector)
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    with caplog.at_level(logging.DEBUG, logger="voice_concierge.web"):
        with running_server(
            wake_word_service=service,
            voice_input_enabled=True,
        ) as base_url:
            started = read_json(
                f"{base_url}/api/wake-word/start",
                payload={"sensitivity": 60},
                opener=opener,
            )
            detector.detect = True
            frame = read_json(
                f"{base_url}/api/wake-word/frame",
                payload={"pcm_base64": "AAAAAA=="},
                opener=opener,
            )
            stopped = read_json(
                f"{base_url}/api/wake-word/stop",
                payload={},
                opener=opener,
            )

    assert started["active"] is True
    assert started["confidence_threshold"] == 0.3
    assert frame == {
        "detected": True,
        "phrase": "hey_jarvis",
        "confidence": 0.8,
    }
    assert stopped == {"active": False}
    assert "web_wake_detection server_processing_ms=" in caplog.text


def test_browser_wake_timing_diagnostics_log_durations_without_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG, logger="voice_concierge.web"):
        with running_server() as base_url:
            response = read_json(
                f"{base_url}/api/diagnostics/wake-timing",
                payload={
                    "event": "command_capture_started",
                    "wake_round_trip_ms": 83.27,
                    "buffered_audio_ms": 96,
                    "transcript": "this value must never be logged",
                },
            )

    assert response == {"recorded": True}
    assert "web_wake_timing event=command_capture_started" in caplog.text
    assert "buffered_audio_ms=96.0" in caplog.text
    assert "wake_round_trip_ms=83.3" in caplog.text
    assert "this value must never be logged" not in caplog.text


def test_browser_wake_timing_rejects_invalid_duration() -> None:
    with running_server() as base_url:
        with pytest.raises(HTTPError) as error:
            read_json(
                f"{base_url}/api/diagnostics/wake-timing",
                payload={
                    "event": "speech_started",
                    "wake_to_speech_ms": -1,
                },
            )

    assert error.value.code == 400


def test_browser_routine_command_api_returns_local_spotter_event() -> None:
    class FakeSpotter:
        def __init__(self) -> None:
            self.reset_count = 0

        def process(self, frame: bytes) -> CommandEvent:
            assert frame == b"\0\0"
            return CommandEvent(command="next", phrase="next", confidence=0.9)

        def reset(self) -> None:
            self.reset_count += 1

    spotter = FakeSpotter()
    service = WebRoutineCommandService(lambda: spotter)
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    with running_server(
        routine_command_service=service,
        voice_input_enabled=True,
    ) as base_url:
        started = read_json(
            f"{base_url}/api/routine-command/start",
            payload={},
            opener=opener,
        )
        result = read_json(
            f"{base_url}/api/routine-command/frame",
            payload={"pcm_base64": base64.b64encode(b"\0\0").decode("ascii")},
            opener=opener,
        )
        reset = read_json(
            f"{base_url}/api/routine-command/reset",
            payload={},
            opener=opener,
        )
        stopped = read_json(
            f"{base_url}/api/routine-command/stop",
            payload={},
            opener=opener,
        )

    assert started == {"active": True, "sample_rate": 16000}
    assert result == {"command": "next", "phrase": "next", "confidence": 0.9}
    assert reset == {"active": True}
    assert spotter.reset_count == 2
    assert stopped == {"active": False}


def test_unknown_api_get_returns_json_404() -> None:
    with running_server() as base_url:
        with pytest.raises(HTTPError) as error:
            read_json(f"{base_url}/api/not-real")

        assert error.value.code == 404
        assert error.value.headers.get_content_type() == "application/json"
        response = json.load(error.value)

    assert response == {"error": {"code": "not_found", "message": "Unknown endpoint."}}


def test_text_turn_runs_through_serialized_pipeline_contract() -> None:
    with running_server() as base_url:
        response = read_json(
            f"{base_url}/api/turn",
            payload={
                "transcript": "hello",
                "state": None,
                "options": {"synthesize": False, "play": False},
            },
        )

    assert response["transcript"]["text"] == "hello"
    assert response["spoken_response"] == "Fake pipeline response for: hello"
    assert response["state"]["conversation_history"] == [
        {
            "user_transcript": "hello",
            "assistant_response": "Fake pipeline response for: hello",
        }
    ]


def test_chat_export_downloads_transient_text_without_audio() -> None:
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    with running_server() as base_url:
        read_json(
            f"{base_url}/api/turn",
            payload={"transcript": "hello"},
            opener=opener,
        )
        with opener.open(f"{base_url}/api/session/export", timeout=2) as response:
            exported = json.load(response)
            disposition = response.headers.get("Content-Disposition")

    assert disposition is not None
    assert disposition.startswith('attachment; filename="granite-chat-')
    assert exported["format"] == "granite-chat"
    assert exported["version"] == 2
    assert exported["privacy"] == {
        "session_scope": "temporary",
        "persisted_by_application": False,
        "audio_included": False,
    }
    assert [
        {"role": message["role"], "content": message["content"]}
        for message in exported["messages"]
    ] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "Fake pipeline response for: hello"},
    ]
    sent_at, received_at = (
        datetime.fromisoformat(message["timestamp"]) for message in exported["messages"]
    )
    assert sent_at <= received_at


def test_web_session_keeps_full_display_history_beyond_reasoning_window() -> None:
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    with running_server() as base_url:
        response = {}
        for index in range(8):
            response = read_json(
                f"{base_url}/api/turn",
                payload={"transcript": f"message {index}"},
                opener=opener,
            )
        restored = read_json(f"{base_url}/api/session", opener=opener)
        with opener.open(f"{base_url}/api/session/export", timeout=2) as download:
            exported = json.load(download)

    assert len(response["state"]["conversation_history"]) == 6
    assert len(response["session_history"]) == 8
    assert restored["session_history"] == response["session_history"]
    assert restored["session_history"][0]["user_transcript"] == "message 0"
    assert restored["session_history"][-1]["user_transcript"] == "message 7"
    assert len(exported["messages"]) == 16


def test_web_turn_applies_response_length_to_server_owned_session() -> None:
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    with running_server() as base_url:
        configured = read_json(
            f"{base_url}/api/turn",
            payload={
                "transcript": "hello",
                "options": {"response_length": "detailed"},
            },
            opener=opener,
        )
        retained = read_json(
            f"{base_url}/api/turn",
            payload={"transcript": "hello again"},
            opener=opener,
        )

    assert configured["state"]["context"]["accessibility"]["verbosity"] == ("detailed")
    assert retained["state"]["context"]["accessibility"]["verbosity"] == "detailed"


def test_turn_log_reports_pipeline_status_without_transcript(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="voice_concierge.web")
    private_transcript = "remember my private appointment"

    with running_server() as base_url:
        read_json(
            f"{base_url}/api/turn",
            payload={"transcript": private_transcript},
        )

    assert "web_turn_completed" in caplog.text
    assert "errors=none" in caplog.text
    assert private_transcript not in caplog.text


def test_debug_turn_log_reports_prompt_response_and_route(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="voice_concierge.web")
    transcript = "hello from detailed diagnostics"

    with running_server(diagnostics_enabled=True) as base_url:
        response = read_json(
            f"{base_url}/api/turn",
            payload={"transcript": transcript},
        )

    assert transcript in caplog.text
    assert response["spoken_response"] in caplog.text
    assert "route=reasoning" in caplog.text
    assert "web_turn_response" in caplog.text


def test_web_session_retains_confirmation_when_client_omits_state() -> None:
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    with running_server() as base_url:
        proposal = read_json(
            f"{base_url}/api/turn",
            payload={"transcript": "remember that I prefer tea"},
            opener=opener,
        )
        confirmation = read_json(
            f"{base_url}/api/turn",
            payload={"transcript": "yes", "state": None},
            opener=opener,
        )

    assert proposal["state"]["pending_memory_action"] is not None
    assert confirmation["memory_operation"]["succeeded"] is True
    assert confirmation["state"]["pending_memory_action"] is None


def test_new_conversation_clears_transient_state_only() -> None:
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    with running_server() as base_url:
        read_json(
            f"{base_url}/api/turn",
            payload={"transcript": "hello"},
            opener=opener,
        )
        reset = read_json(
            f"{base_url}/api/session/reset",
            payload={},
            opener=opener,
        )
        next_turn = read_json(
            f"{base_url}/api/turn",
            payload={"transcript": "hello again"},
            opener=opener,
        )

    assert reset["state"]["conversation_history"] == []
    assert next_turn["state"]["conversation_history"] == [
        {
            "user_transcript": "hello again",
            "assistant_response": "Fake pipeline response for: hello again",
        }
    ]


def test_reminders_are_routed_and_managed_through_web_api(tmp_path: Path) -> None:
    service = ReminderService(ReminderStore(tmp_path / "reminders.sqlite3"))
    features = WebFeatureServices(
        reminder_handler=ReminderTurnHandler(service),
    )
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    with running_server(features=features) as base_url:
        created = read_json(
            f"{base_url}/api/turn",
            payload={"transcript": "remind me in ten minutes to check the oven"},
            opener=opener,
        )
        listed = read_json(f"{base_url}/api/reminders", opener=opener)
        identifier = listed["reminders"][0]["id"]
        edited = read_json(
            f"{base_url}/api/reminders/edit",
            payload={"id": identifier, "text": "check the bread"},
            opener=opener,
        )
        cancelled = read_json(
            f"{base_url}/api/reminders/cancel",
            payload={"id": identifier},
            opener=opener,
        )

    assert created["spoken_response"].startswith("I'll remind you")
    assert edited["reminder"]["text"] == "check the bread"
    assert cancelled == {"cancelled": True, "id": identifier}


def test_natural_timer_wording_is_stored_and_visible_in_local_data(
    tmp_path: Path,
) -> None:
    service = ReminderService(ReminderStore(tmp_path / "reminders.sqlite3"))
    features = WebFeatureServices(
        reminder_handler=ReminderTurnHandler(service),
    )
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    with running_server(features=features) as base_url:
        created = read_json(
            f"{base_url}/api/turn",
            payload={"transcript": "Set the timer for 5 minutes."},
            opener=opener,
        )
        listed = read_json(f"{base_url}/api/reminders", opener=opener)

    assert created["spoken_response"] == "Timer set for 5 minutes."
    assert len(listed["reminders"]) == 1
    assert listed["reminders"][0]["kind"] == "timer"


def test_misheard_timer_request_is_stored_instead_of_reaching_reasoning(
    tmp_path: Path,
) -> None:
    service = ReminderService(ReminderStore(tmp_path / "reminders.sqlite3"))
    features = WebFeatureServices(
        reminder_handler=ReminderTurnHandler(service),
    )
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    with running_server(features=features) as base_url:
        created = read_json(
            f"{base_url}/api/turn",
            payload={"transcript": "It says a timer for three minutes."},
            opener=opener,
        )
        checked = read_json(
            f"{base_url}/api/turn",
            payload={"transcript": "Do I have a timer set?"},
            opener=opener,
        )
        listed = read_json(f"{base_url}/api/reminders", opener=opener)

    assert created["spoken_response"] == "Timer set for 3 minutes."
    assert checked["spoken_response"].startswith("You have one: three minutes,")
    assert len(listed["reminders"]) == 1
    assert listed["reminders"][0]["kind"] == "timer"


def test_guided_routine_keeps_its_place_in_web_session() -> None:
    features = WebFeatureServices(
        routine_sessions=WebRoutineSessions(
            lambda: RoutineCommandAdapter(DeterministicRoutineProvider())
        )
    )
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    with running_server(features=features) as base_url:
        started = read_json(
            f"{base_url}/api/turn",
            payload={"transcript": "guide me through a morning stretch"},
            opener=opener,
        )
        advanced = read_json(
            f"{base_url}/api/turn",
            payload={"transcript": "next", "automatic_routine": True},
            opener=opener,
        )

    assert started["spoken_response"] == "Step 1 of 2. Stand comfortably."
    assert started["routine"]["active"] is True
    assert advanced["spoken_response"] == "Step 2 of 2. Reach up."
    assert advanced["automatic_routine"] is True
    assert advanced["session_history"][-1] == {
        "user_transcript": "",
        "assistant_response": "Step 2 of 2. Reach up.",
        "user_sent_at": None,
        "assistant_received_at": advanced["session_history"][-1][
            "assistant_received_at"
        ],
    }
    datetime.fromisoformat(advanced["session_history"][-1]["assistant_received_at"])


def test_active_routine_does_not_hijack_ordinary_or_safety_questions() -> None:
    features = WebFeatureServices(
        routine_sessions=WebRoutineSessions(
            lambda: RoutineCommandAdapter(DeterministicRoutineProvider())
        )
    )
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    with running_server(features=features) as base_url:
        started = read_json(
            f"{base_url}/api/turn",
            payload={"transcript": "guide me through a morning stretch"},
            opener=opener,
        )
        ordinary = read_json(
            f"{base_url}/api/turn",
            payload={"transcript": "spell accommodation"},
            opener=opener,
        )
        safety = read_json(
            f"{base_url}/api/turn",
            payload={"transcript": "I smell gas. What should I do?"},
            opener=opener,
        )
        advanced = read_json(
            f"{base_url}/api/turn",
            payload={"transcript": "next"},
            opener=opener,
        )

    assert started["spoken_response"] == "Step 1 of 2. Stand comfortably."
    assert (
        ordinary["spoken_response"] == "Fake pipeline response for: spell accommodation"
    )
    assert safety["spoken_response"].startswith("Leave the building immediately")
    assert advanced["spoken_response"] == "Step 2 of 2. Reach up."


def test_web_routine_supports_pause_pacing_and_confirmed_back() -> None:
    sessions = WebRoutineSessions(
        lambda: RoutineCommandAdapter(DeterministicRoutineProvider())
    )
    session_id = "session-a"

    assert sessions.route(session_id, "guide me through stretching").startswith(
        "Step 1"
    )
    assert sessions.route(session_id, "next").startswith("Step 2")
    assert sessions.route(session_id, "back") == "Go back a step? Say yes to confirm."
    assert sessions.snapshot(session_id)["awaiting_confirmation"] is True
    assert sessions.route(session_id, "yes").startswith("Step 1")
    assert sessions.route(session_id, "pause").startswith("Paused.")
    assert sessions.snapshot(session_id)["status"] == "paused"
    assert sessions.route(session_id, "continue").startswith("Resuming.")
    assert sessions.route(session_id, "slower").startswith("Step 1")
    assert sessions.snapshot(session_id)["pace_delta"] == -0.1
    assert "pace_delta" not in sessions.snapshot(session_id)


def test_due_reminder_is_queued_until_browser_collects_it(
    tmp_path: Path,
) -> None:
    store = ReminderStore(tmp_path / "reminders.sqlite3")
    service = ReminderService(store)
    stored = store.add(Reminder(text="check the oven", schedule=Schedule(1)), now=1)
    notifier = WebReminderNotifier()
    runner = ReminderRunner(service, notifier)
    features = WebFeatureServices(
        reminder_handler=ReminderTurnHandler(service),
        reminder_notifier=notifier,
        reminder_runner=runner,
    )

    assert runner.check_now() == (stored,)
    assert service.upcoming() == ()
    with running_server(features=features) as base_url:
        delivered = read_json(f"{base_url}/api/reminders/due")
        repeated = read_json(f"{base_url}/api/reminders/due")

    assert delivered["notifications"][0]["announcement"] == (
        "Reminder: check the oven."
    )
    assert repeated == {"notifications": []}


def test_due_reminder_uses_configured_local_speech_synthesizer() -> None:
    class FakeSpeech:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def synthesize(self, text: str) -> CapturedAudio:
            self.calls.append(text)
            return CapturedAudio(samples=np.zeros(160, dtype=np.int16))

    speech = FakeSpeech()
    notifier = WebReminderNotifier(speech)
    reminder = Reminder(text="check the oven", schedule=Schedule(1))

    notifier.notify(reminder)
    queued = notifier.drain()

    assert speech.calls == ["Reminder: check the oven."]
    assert queued[0]["audio"]["wav_base64"]


def test_privacy_centre_exposes_edit_and_delete_controls(tmp_path: Path) -> None:
    manager = build_memory_manager(
        LocalMemoryConfig(
            memory_db_path=tmp_path / "memories.sqlite3",
            vector_db_path=tmp_path / "vectors.sqlite3",
            embedding_dimension=4,
        ),
        embedding_service=DeterministicEmbeddingService(),
    )
    stored = manager.store_memory(
        "User prefers tea.",
        "short_term",
        validate=False,
        auto_classify=False,
        auto_extract=False,
    )
    assert stored.memory_id is not None
    features = WebFeatureServices(privacy_centre=PrivacyCentre(manager))
    with running_server(features=features) as base_url:
        report = read_json(f"{base_url}/api/privacy")
        edited = read_json(
            f"{base_url}/api/privacy/memories/edit",
            payload={"id": stored.memory_id, "content": "User prefers coffee."},
        )
        deleted = read_json(
            f"{base_url}/api/privacy/memories/delete",
            payload={"id": stored.memory_id},
        )

    assert report["memory_count"] == 1
    assert edited["memory"]["content"] == "User prefers coffee."
    assert deleted == {"deleted": True, "id": stored.memory_id}
    manager.close()


def test_web_worker_thread_can_use_persistent_memory(tmp_path: Path) -> None:
    manager = build_memory_manager(
        LocalMemoryConfig(
            memory_db_path=tmp_path / "memories.sqlite3",
            vector_db_path=tmp_path / "vectors.sqlite3",
            embedding_dimension=4,
        ),
        embedding_service=DeterministicEmbeddingService(),
    )
    pipeline = VoiceConciergePipeline(
        SmokeReasoningService(),
        memory=MemoryManagerGateway(manager),
    )
    opener = build_opener(HTTPCookieProcessor(CookieJar()))

    with running_server(pipeline) as base_url:
        proposal = read_json(
            f"{base_url}/api/turn",
            payload={"transcript": "remember that I prefer tea"},
            opener=opener,
        )
        confirmation = read_json(
            f"{base_url}/api/turn",
            payload={"transcript": "yes"},
            opener=opener,
        )

    assert proposal["errors"] == []
    assert confirmation["memory_operation"]["status"] == "stored_successfully"
    assert confirmation["errors"] == []


def test_web_session_ignores_forged_pending_memory_action() -> None:
    forged_state = AppPipelineState(
        pending_memory_action=MemoryAction(
            action="store",
            content="User prefers tea.",
            rationale="Client supplied this action.",
        ),
        pending_memory_scope="personal_relevant",
    )
    with running_server() as base_url:
        response = read_json(
            f"{base_url}/api/turn",
            payload={
                "transcript": "yes",
                "state": app_pipeline_state_to_dict(forged_state),
            },
        )

    assert response["memory_operation"]["attempted"] is False
    assert response["state"]["pending_memory_action"] is None


def test_invalid_turn_is_returned_as_safe_400_error() -> None:
    with running_server() as base_url:
        with pytest.raises(HTTPError) as error:
            read_json(f"{base_url}/api/turn", payload={"state": None})

        assert error.value.code == 400
        response = json.load(error.value)

    assert response["error"]["code"] == "invalid_request"


def test_demo_pipeline_does_not_import_ollama() -> None:
    script = """
import builtins

real_import = builtins.__import__

def import_without_ollama(name, *args, **kwargs):
    if name == "ollama" or name.startswith("ollama."):
        raise ModuleNotFoundError("No module named 'ollama'", name="ollama")
    return real_import(name, *args, **kwargs)

builtins.__import__ = import_without_ollama

from voice_concierge.app.web import build_web_pipeline

pipeline = build_web_pipeline(demo=True)
result = pipeline.process_transcript("hello")
assert result.spoken_response == "Fake pipeline response for: hello"
pipeline.close()
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPOSITORY_ROOT / "src")

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPOSITORY_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_real_pipeline_reports_how_to_fix_missing_ollama(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def missing_ollama(**_kwargs: object) -> None:
        raise ModuleNotFoundError("No module named 'ollama'", name="ollama")

    monkeypatch.setattr(web_module, "build_web_application", missing_ollama)

    with pytest.raises(SystemExit) as error:
        web_module.main([])

    assert error.value.code == 2
    stderr = capsys.readouterr().err
    assert "python -m pip install -e ." in stderr
    assert "--demo" in stderr
