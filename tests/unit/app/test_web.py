"""Tests for the same-origin browser UI server."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from voice_concierge.app import web as web_module
from voice_concierge.app.smoke import build_smoke_pipeline
from voice_concierge.app.web import PipelineWebServer

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


@contextmanager
def running_server() -> Iterator[str]:
    pipeline = build_smoke_pipeline()
    server = PipelineWebServer(
        ("127.0.0.1", 0),
        pipeline,
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
        pipeline.close()
        thread.join(timeout=2)


def read_json(url: str, *, payload: dict[str, object] | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urlopen(request, timeout=2) as response:
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
        },
        "runtime": {"model": "smoke model"},
    }


def test_static_ui_disables_browser_cache() -> None:
    with running_server() as base_url:
        with urlopen(f"{base_url}/", timeout=2) as response:
            html = response.read().decode("utf-8")
            cache_control = response.headers.get("Cache-Control")

    assert cache_control == "no-store"
    assert "./app.js?v=20260812" in html
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
