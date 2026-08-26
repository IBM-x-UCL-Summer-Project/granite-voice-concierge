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
FINAL_PROMPT_SUITE = Path("benchmarks/reasoning/prompts/final-v1.json")


def test_prompt_suite_loads_all_cases() -> None:
    suite = load_prompt_suite(PROMPT_SUITE)
    cases = list(iter_benchmark_cases(suite))

    assert len(cases) == 20
    assert cases[0].case_id == "cooking_scrambled_eggs_first_step"
    assert cases[0].category == "cooking"
    assert cases[0].mode == "cooking"
    assert cases[0].checks is not None
    runtime_case = next(
        case for case in cases if case.case_id == "runtime_local_device_time"
    )
    assert runtime_case.runtime_context[0].runtime_id == "system.local_datetime"


def test_final_prompt_suite_has_reported_case_distribution() -> None:
    suite = load_prompt_suite(FINAL_PROMPT_SUITE)
    cases = list(iter_benchmark_cases(suite))

    assert len(cases) == 30
    assert {
        category: len(category_cases)
        for category, category_cases in suite["categories"].items()
    } == {
        "general_requests": 6,
        "missing_context": 5,
        "safety_sensitive": 5,
        "offline_no_web": 5,
        "memory_confirmation": 5,
        "structured_output_response_length": 4,
    }
    assert len({case.case_id for case in cases}) == 30


def test_benchmark_report_contains_core_metrics() -> None:
    suite = load_prompt_suite(PROMPT_SUITE)

    report = run_reasoning_benchmark(DeterministicReasoningFake(), suite)

    assert report["suite"]["name"] == "reasoning_prompts_v0"
    assert report["engine"] == "DeterministicReasoningFake"
    assert report["total_cases"] == 20
    assert report["elapsed_ms"] >= 0
    assert len(report["results"]) == 20

    first_result = report["results"][0]
    assert first_result["case_id"] == "cooking_scrambled_eggs_first_step"
    assert first_result["latency_ms"] >= 0
    assert first_result["response_words"] > 0
    assert "spoken_response" in first_result
    assert "required_information_source" in first_result
    assert "information_evidence" in first_result
    assert "freshness_requirement" in first_result
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


def test_benchmark_report_checks_information_source_and_freshness() -> None:
    suite = {
        "name": "test_suite",
        "categories": {
            "information_policy": [
                {
                    "transcript": "Is the pharmacy open?",
                    "mode": "home",
                    "expected_behavior": "Require current external information.",
                    "checks": {
                        "information_source": "external_live",
                        "freshness_requirement": "current",
                    },
                }
            ]
        },
    }

    report = run_reasoning_benchmark(DeterministicReasoningFake(), suite)

    issues = report["results"][0]["issues"]
    assert "information_source_expected_external_live" in issues
    assert "freshness_requirement_expected_current" in issues


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
                    "memories": [
                        {
                            "memory_id": 1,
                            "content": "Shopping list: milk, bread.",
                            "layer": "feedback",
                            "revision": 1,
                            "memory_key": "list:shopping",
                        }
                    ],
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
    assert report["raw_passed_responses"] == 0
    assert report["guarded_passed_responses"] == 1
    assert report["guard_interventions"] == 1
    result = report["results"][0]
    assert result["passed_checks"] is True
    assert result["raw_evaluation"]["passed_checks"] is False
    assert result["guarded_evaluation"]["passed_checks"] is True
    assert result["guard_intervened"] is True
    assert result["policy_guard"] == "memory_store_confirmation"


def test_benchmark_fails_schema_invalid_generations() -> None:
    class InvalidStructuredTraceEngine:
        def generate(self, request: ReasoningRequest) -> ReasoningResponse:
            raise AssertionError("both mode should use generate_trace")

        def generate_trace(self, request: ReasoningRequest) -> ReasoningTrace:
            invalid_response = ReasoningResponse(
                spoken_response="I could not produce a valid structured response.",
                confidence="low",
                metadata={"structured_parse_error": "schema_validation_failed"},
            )
            return ReasoningTrace(
                raw_response=invalid_response,
                guarded_response=invalid_response,
            )

    suite = {
        "name": "test_suite",
        "categories": {
            "general": [
                {
                    "id": "invalid_structure",
                    "transcript": "Hello.",
                    "expected_behavior": "Return a structured response.",
                }
            ]
        },
    }

    report = run_reasoning_benchmark(
        InvalidStructuredTraceEngine(),
        suite,
        evaluation_mode="both",
    )

    assert report["structured_parse_failures"] == 1
    assert report["raw_passed_responses"] == 0
    assert report["guarded_passed_responses"] == 0
    result = report["results"][0]
    assert result["raw_evaluation"]["issues"] == ("structured_output_invalid",)
    assert result["guarded_evaluation"]["issues"] == ("structured_output_invalid",)


def test_benchmark_repeats_every_case_and_labels_each_response() -> None:
    suite = {
        "name": "repeated_suite",
        "categories": {
            "general": [
                {
                    "id": "hello",
                    "transcript": "Hello.",
                    "expected_behavior": "Return a response.",
                },
                {
                    "id": "goodbye",
                    "transcript": "Goodbye.",
                    "expected_behavior": "Return a response.",
                },
            ]
        },
    }

    report = run_reasoning_benchmark(
        DeterministicReasoningFake(),
        suite,
        repetitions=3,
    )

    assert report["total_cases"] == 2
    assert report["repetitions"] == 3
    assert report["total_responses"] == 6
    assert [result["repetition"] for result in report["results"]] == [
        1,
        1,
        2,
        2,
        3,
        3,
    ]


@pytest.mark.parametrize("repetitions", (0, -1, True))
def test_benchmark_rejects_invalid_repetition_count(repetitions: object) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        run_reasoning_benchmark(
            DeterministicReasoningFake(),
            {"name": "test", "categories": {}},
            repetitions=repetitions,  # type: ignore[arg-type]
        )


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
