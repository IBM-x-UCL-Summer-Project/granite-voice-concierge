"""Tests for the same-origin browser UI server."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from voice_concierge.app.smoke import build_smoke_pipeline
from voice_concierge.app.web import PipelineWebServer


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
