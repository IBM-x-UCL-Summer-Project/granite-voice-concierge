"""Tests for the fake app-pipeline smoke runner."""

from __future__ import annotations

import json

from voice_concierge.app.smoke import main, run_smoke_turns


def test_run_smoke_turns_maintains_state_across_memory_confirmation() -> None:
    turns = run_smoke_turns(
        [
            "remember that I prefer tea",
            "yes",
            "what do you remember",
        ]
    )

    first_response = turns[0]["response"]
    second_response = turns[1]["response"]
    third_response = turns[2]["response"]

    assert first_response["state"]["pending_memory_action"] == {
        "action": "store",
        "content": "I prefer tea",
        "rationale": "Smoke runner detected a remember request.",
        "requires_confirmation": True,
    }
    assert second_response["spoken_response"] == "I've saved that."
    assert second_response["memory_operation"] == {
        "attempted": True,
        "succeeded": True,
        "status": "stored_successfully",
        "memory_id": 1,
        "detail": None,
        "similarity_advisories": [],
        "reason": "stored_successfully",
    }
    assert second_response["state"]["pending_memory_action"] is None
    assert len(second_response["state"]["conversation_history"]) == 2
    assert third_response["spoken_response"] == (
        "I found this in local memory: I prefer tea"
    )
    assert len(third_response["state"]["conversation_history"]) == 3


def test_main_prints_json_turn_payload(capsys) -> None:
    exit_code = main(["--compact", "hello"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["turns"][0]["request"]["transcript"] == "hello"
    assert payload["turns"][0]["response"]["spoken_response"] == (
        "Fake pipeline response for: hello"
    )
