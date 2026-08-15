"""Tests for the same-origin browser UI server."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
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

import pytest

from voice_concierge.app import web as web_module
from voice_concierge.app.memory import MemoryManagerGateway
from voice_concierge.app.pipeline import VoiceConciergePipeline
from voice_concierge.app.serialization import app_pipeline_state_to_dict
from voice_concierge.app.smoke import SmokeReasoningService, build_smoke_pipeline
from voice_concierge.app.types import AppPipelineState
from voice_concierge.app.web import PipelineWebServer
from voice_concierge.memory import LocalMemoryConfig, build_memory_manager
from voice_concierge.reasoning.types import MemoryAction

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class DeterministicEmbeddingService:
    def get_embedding(self, content: str) -> list[float]:
        return [1.0, 0.0, 0.0, 0.0]


@contextmanager
def running_server(
    pipeline: VoiceConciergePipeline | None = None,
) -> Iterator[str]:
    resolved_pipeline = pipeline or build_smoke_pipeline()
    server = PipelineWebServer(
        ("127.0.0.1", 0),
        resolved_pipeline,
        model_name="smoke model",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
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
        "capabilities": {
            "text_input": True,
            "voice_input": False,
            "voice_output": False,
            "wake_word": False,
        },
        "runtime": {"model": "smoke model"},
    }


def test_static_ui_disables_browser_cache() -> None:
    with running_server() as base_url:
        with urlopen(f"{base_url}/", timeout=2) as response:
            html = response.read().decode("utf-8")
            cache_control = response.headers.get("Cache-Control")

    assert cache_control == "no-store"
    assert "./playback-policy.js?v=20260815" in html
    assert "./app.js?v=20260815-2" in html
    assert "./styles.css?v=20260812" in html


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

    monkeypatch.setattr(web_module, "build_web_pipeline", missing_ollama)

    with pytest.raises(SystemExit) as error:
        web_module.main([])

    assert error.value.code == 2
    stderr = capsys.readouterr().err
    assert "python -m pip install -e ." in stderr
    assert "--demo" in stderr
