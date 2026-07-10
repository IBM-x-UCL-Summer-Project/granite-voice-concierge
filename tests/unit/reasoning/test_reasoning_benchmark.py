"""Tests for reasoning benchmark helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.reasoning.suite import (
    iter_benchmark_cases,
    load_prompt_suite,
    run_reasoning_benchmark,
    write_benchmark_report,
)
from voice_concierge.reasoning import DeterministicReasoningFake
from voice_concierge.reasoning.types import (
    MemoryAction,
    ReasoningRequest,
    ReasoningResponse,
    ReasoningTrace,
)

PROMPT_SUITE = Path("benchmarks/reasoning/prompts/v0.json")


def test_prompt_suite_loads_all_cases() -> None:
    suite = load_prompt_suite(PROMPT_SUITE)
    cases = list(iter_benchmark_cases(suite))

    assert len(cases) == 15
    assert cases[0].case_id == "cooking_scrambled_eggs_first_step"
    assert cases[0].category == "cooking"
    assert cases[0].mode == "cooking"
    assert cases[0].checks is not None


def test_benchmark_report_contains_core_metrics() -> None:
    suite = load_prompt_suite(PROMPT_SUITE)

    report = run_reasoning_benchmark(DeterministicReasoningFake(), suite)

    assert report["suite"]["name"] == "reasoning_prompts_v0"
    assert report["engine"] == "DeterministicReasoningFake"
    assert report["total_cases"] == 15
    assert report["elapsed_ms"] >= 0
    assert len(report["results"]) == 15

    first_result = report["results"][0]
    assert first_result["case_id"] == "cooking_scrambled_eggs_first_step"
    assert first_result["latency_ms"] >= 0
    assert first_result["response_words"] > 0
    assert "spoken_response" in first_result
    assert "passed_checks" in first_result
    assert "issues" in first_result


def test_benchmark_report_flags_failed_checks() -> None:
    suite = {
        "name": "test_suite",
        "categories": {
            "memory_action_policy": [
                {
                    "transcript": "Hello.",
                    "mode": "home",
                    "expected_behavior": "Require a memory action.",
                    "checks": {
                        "needs_confirmation": True,
                        "memory_action": "store",
                    },
                }
            ]
        },
    }

    report = run_reasoning_benchmark(DeterministicReasoningFake(), suite)

    result = report["results"][0]
    assert result["passed_checks"] is False
    assert "memory_action_expected_store" in result["issues"]


def test_benchmark_report_checks_all_required_terms() -> None:
    class MilkOnlyEngine:
        def generate(self, request: ReasoningRequest) -> ReasoningResponse:
            return ReasoningResponse(spoken_response="Your list has milk.")

    suite = {
        "name": "test_suite",
        "categories": {
            "shopping": [
                {
                    "id": "shopping_list_items",
                    "transcript": "What is on my shopping list?",
                    "mode": "shopping",
                    "memories": ["Shopping list: milk, bread."],
                    "expected_behavior": "List all supplied shopping items.",
                    "checks": {
                        "must_contain_all": ["milk", "bread"],
                    },
                }
            ]
        },
    }

    report = run_reasoning_benchmark(MilkOnlyEngine(), suite)

    result = report["results"][0]
    assert result["passed_checks"] is False
    assert "missing_required_terms" in result["issues"]


def test_benchmark_passes_conversation_summary() -> None:
    class SummaryEchoEngine:
        def generate(self, request: ReasoningRequest) -> ReasoningResponse:
            return ReasoningResponse(
                spoken_response=request.conversation_summary or "No summary.",
            )

    suite = {
        "name": "test_suite",
        "categories": {
            "cooking": [
                {
                    "id": "repeat_known_step",
                    "transcript": "Repeat that step.",
                    "mode": "cooking",
                    "conversation_summary": "Previous step: whisk the eggs.",
                    "expected_behavior": "Repeat the previous step.",
                    "checks": {
                        "must_contain_any": ["whisk the eggs"],
                    },
                }
            ]
        },
    }

    report = run_reasoning_benchmark(SummaryEchoEngine(), suite)

    result = report["results"][0]
    assert result["case_id"] == "repeat_known_step"
    assert result["conversation_summary"] == "Previous step: whisk the eggs."
    assert result["passed_checks"] is True


def test_benchmark_report_can_be_written(tmp_path: Path) -> None:
    report = {
        "suite": {"name": "test"},
        "engine": "stub",
        "total_cases": 0,
        "elapsed_ms": 0,
        "results": [],
    }
    output_path = tmp_path / "nested" / "report.json"

    write_benchmark_report(report, output_path)

    assert json.loads(output_path.read_text(encoding="utf-8")) == report


def test_benchmark_evaluates_raw_and_guarded_response_from_one_trace() -> None:
    class TraceEngine:
        def __init__(self) -> None:
            self.trace_calls = 0

        def generate(self, request: ReasoningRequest) -> ReasoningResponse:
            raise AssertionError("both mode should use generate_trace")

        def generate_trace(self, request: ReasoningRequest) -> ReasoningTrace:
            self.trace_calls += 1
            action = MemoryAction(
                action="store",
                content="User prefers short answers",
                rationale="User asked to remember a preference.",
            )
            return ReasoningTrace(
                raw_response=ReasoningResponse(
                    spoken_response="Okay, saved.",
                    confidence="medium",
                ),
                guarded_response=ReasoningResponse(
                    spoken_response="I can remember that. Please confirm.",
                    needs_confirmation=True,
                    proposed_memory_action=action,
                    confidence="high",
                    metadata={"policy_guard": "memory_store_confirmation"},
                ),
            )

    suite = {
        "name": "test_suite",
        "categories": {
            "memory": [
                {
                    "id": "remember_preference",
                    "transcript": "Remember that I prefer short answers.",
                    "expected_behavior": "Confirm before storing memory.",
                    "checks": {
                        "needs_confirmation": True,
                        "memory_action": "store",
                    },
                }
            ]
        },
    }
    engine = TraceEngine()

    report = run_reasoning_benchmark(engine, suite, evaluation_mode="both")

    assert engine.trace_calls == 1
    assert report["evaluation_mode"] == "both"
    assert report["primary_evaluation"] == "guarded"
    assert report["raw_passed_cases"] == 0
    assert report["guarded_passed_cases"] == 1
    assert report["guard_interventions"] == 1
    result = report["results"][0]
    assert result["passed_checks"] is True
    assert result["raw_evaluation"]["passed_checks"] is False
    assert result["guarded_evaluation"]["passed_checks"] is True
    assert result["guard_intervened"] is True
    assert result["policy_guard"] == "memory_store_confirmation"


def test_benchmark_raw_mode_uses_raw_response_as_primary_result() -> None:
    class TraceEngine:
        def generate(self, request: ReasoningRequest) -> ReasoningResponse:
            raise AssertionError("raw mode should use generate_trace")

        def generate_trace(self, request: ReasoningRequest) -> ReasoningTrace:
            return ReasoningTrace(
                raw_response=ReasoningResponse(spoken_response="Raw response."),
                guarded_response=ReasoningResponse(spoken_response="Guarded response."),
            )

    suite = {
        "name": "test_suite",
        "categories": {
            "general": [
                {
                    "id": "raw_case",
                    "transcript": "Hello.",
                    "expected_behavior": "Return a response.",
                }
            ]
        },
    }

    report = run_reasoning_benchmark(TraceEngine(), suite, evaluation_mode="raw")

    result = report["results"][0]
    assert report["primary_evaluation"] == "raw"
    assert result["spoken_response"] == "Raw response."
    assert result["raw_evaluation"] is not None
    assert result["guarded_evaluation"] is None


def test_benchmark_rejects_raw_mode_for_engine_without_trace() -> None:
    suite = {
        "name": "test_suite",
        "categories": {
            "general": [
                {
                    "transcript": "Hello.",
                    "expected_behavior": "Return a response.",
                }
            ]
        },
    }

    with pytest.raises(ValueError, match="does not expose raw reasoning traces"):
        run_reasoning_benchmark(
            DeterministicReasoningFake(),
            suite,
            evaluation_mode="raw",
        )
