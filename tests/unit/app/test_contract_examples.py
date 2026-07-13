"""Tests for checked-in app pipeline contract examples."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from voice_concierge.app.adapter import handle_turn
from voice_concierge.app.smoke import build_smoke_pipeline

_REPO_ROOT = Path(__file__).resolve().parents[3]
_EXAMPLES = _REPO_ROOT / "docs" / "app-pipeline" / "examples"


@pytest.mark.parametrize(
    ("request_name", "response_name"),
    (
        (
            "context-confirmation-request.json",
            "context-confirmation-response.json",
        ),
        (
            "memory-proposal-request.json",
            "memory-proposal-response.json",
        ),
    ),
)
def test_contract_example_matches_smoke_pipeline(
    request_name: str,
    response_name: str,
) -> None:
    request_payload = _load_example(request_name)
    expected_response = _load_example(response_name)

    response = handle_turn(request_payload, build_smoke_pipeline())

    assert response == expected_response


def _load_example(name: str) -> dict[str, object]:
    return json.loads((_EXAMPLES / name).read_text())
