"""Prompt-suite execution helpers for local reasoning benchmarks."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal

from voice_concierge.reasoning.engine import ReasoningEngine, TraceableReasoningEngine
from voice_concierge.reasoning.types import (
    MemoryReference,
    ReasoningConstraints,
    ReasoningRequest,
    ReasoningResponse,
)

EvaluationMode = Literal["raw", "guarded", "both"]
EVALUATION_MODES: tuple[EvaluationMode, ...] = ("raw", "guarded", "both")


@dataclass(frozen=True)
class BenchmarkCase:
    """Single prompt case from a benchmark suite."""

    case_id: str
    category: str
    transcript: str
    mode: str
    expected_behavior: str
    memories: tuple[MemoryReference, ...] = ()
    conversation_summary: str | None = None
    checks: dict[str, Any] | None = None


@dataclass(frozen=True)
class BenchmarkEvaluation:
    """Check results for one stage of a reasoning response."""

    spoken_response: str
    response_words: int
    needs_confirmation: bool
    proposed_memory_action: str | None
    confidence: str
    required_information_source: str
    freshness_requirement: str
    metadata: dict[str, str]
    passed_checks: bool
    issues: tuple[str, ...]


@dataclass(frozen=True)
class BenchmarkResult:
    """Measured raw and/or guarded result for one benchmark case."""

    case_id: str
    category: str
    transcript: str
    mode: str
    memories: tuple[MemoryReference, ...]
    conversation_summary: str | None
    expected_behavior: str
    spoken_response: str
    latency_ms: float
    response_words: int
    needs_confirmation: bool
    proposed_memory_action: str | None
    confidence: str
    required_information_source: str
    freshness_requirement: str
    metadata: dict[str, str]
    passed_checks: bool
    issues: tuple[str, ...]
    raw_evaluation: BenchmarkEvaluation | None
    guarded_evaluation: BenchmarkEvaluation | None
    guard_intervened: bool
    policy_guard: str | None


def load_prompt_suite(path: Path) -> dict[str, Any]:
    """Load and minimally validate a reasoning prompt suite."""

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data.get("categories"), dict):
        raise ValueError("Prompt suite must include a categories object.")
    return data


def iter_benchmark_cases(suite: dict[str, Any]) -> Iterable[BenchmarkCase]:
    """Yield normalized benchmark cases from a prompt suite."""

    for category, cases in suite["categories"].items():
        if not isinstance(cases, list):
            raise ValueError(f"Category {category!r} must contain a list of cases.")

        for index, case in enumerate(cases, start=1):
            case_id = case.get("id", f"{category}_{index}")
            if not isinstance(case_id, str) or not case_id.strip():
                raise ValueError(f"Case in category {category!r} has an invalid id.")

            yield BenchmarkCase(
                case_id=case_id,
                category=category,
                transcript=case["transcript"],
                mode=case.get("mode", "home"),
                expected_behavior=case["expected_behavior"],
                memories=tuple(
                    _memory_reference_from_payload(memory, index=memory_index)
                    for memory_index, memory in enumerate(
                        case.get("memories", ()),
                    )
                ),
                conversation_summary=case.get("conversation_summary"),
                checks=case.get("checks"),
            )


def run_reasoning_benchmark(
    engine: ReasoningEngine,
    suite: dict[str, Any],
    *,
    max_words: int = 60,
    evaluation_mode: EvaluationMode = "guarded",
) -> dict[str, Any]:
    """Run a prompt suite against a reasoning engine and return JSON-ready data."""

    if evaluation_mode not in EVALUATION_MODES:
        raise ValueError(f"Unsupported evaluation mode: {evaluation_mode}")

    started_at = datetime.now(timezone.utc)
    suite_name = suite.get("name", "unnamed_reasoning_suite")
    suite_purpose = suite.get("purpose", "")

    results: list[BenchmarkResult] = []
    run_start = time.perf_counter()
    for case in iter_benchmark_cases(suite):
        constraints = ReasoningConstraints(max_words=max_words)
        request = ReasoningRequest(
            transcript=case.transcript,
            mode=case.mode,
            memories=case.memories,
            conversation_summary=case.conversation_summary,
            constraints=constraints,
        )

        case_start = time.perf_counter()
        raw_response, guarded_response = _generate_responses(
            engine,
            request,
            evaluation_mode=evaluation_mode,
        )
        latency_ms = (time.perf_counter() - case_start) * 1000

        raw_evaluation = _evaluate_response(
            case,
            raw_response,
            max_words=max_words,
        )
        guarded_evaluation = _evaluate_response(
            case,
            guarded_response,
            max_words=max_words,
        )
        primary_evaluation = guarded_evaluation or raw_evaluation
        if primary_evaluation is None:
            raise RuntimeError("Benchmark did not produce an evaluation result.")

        policy_guard = (
            guarded_response.metadata.get("policy_guard")
            if guarded_response is not None
            else None
        )
        results.append(
            BenchmarkResult(
                case_id=case.case_id,
                category=case.category,
                transcript=case.transcript,
                mode=case.mode,
                memories=case.memories,
                conversation_summary=case.conversation_summary,
                expected_behavior=case.expected_behavior,
                spoken_response=primary_evaluation.spoken_response,
                latency_ms=round(latency_ms, 3),
                response_words=primary_evaluation.response_words,
                needs_confirmation=primary_evaluation.needs_confirmation,
                proposed_memory_action=primary_evaluation.proposed_memory_action,
                confidence=primary_evaluation.confidence,
                required_information_source=(
                    primary_evaluation.required_information_source
                ),
                freshness_requirement=primary_evaluation.freshness_requirement,
                metadata=primary_evaluation.metadata,
                passed_checks=primary_evaluation.passed_checks,
                issues=primary_evaluation.issues,
                raw_evaluation=raw_evaluation,
                guarded_evaluation=guarded_evaluation,
                guard_intervened=policy_guard is not None,
                policy_guard=policy_guard,
            )
        )

    elapsed_ms = (time.perf_counter() - run_start) * 1000
    return {
        "suite": {
            "name": suite_name,
            "purpose": suite_purpose,
        },
        "engine": engine.__class__.__name__,
        "evaluation_mode": evaluation_mode,
        "primary_evaluation": (
            "guarded" if evaluation_mode in ("guarded", "both") else "raw"
        ),
        "started_at_utc": started_at.isoformat(),
        "total_cases": len(results),
        "raw_passed_cases": _passed_evaluation_count(results, "raw_evaluation"),
        "guarded_passed_cases": _passed_evaluation_count(
            results,
            "guarded_evaluation",
        ),
        "guard_interventions": sum(result.guard_intervened for result in results),
        "elapsed_ms": round(elapsed_ms, 3),
        "results": [asdict(result) for result in results],
    }


def _memory_reference_from_payload(
    payload: object,
    *,
    index: int,
) -> MemoryReference:
    if not isinstance(payload, dict):
        raise ValueError(f"memories[{index}] must be an object.")
    try:
        return MemoryReference(
            memory_id=payload["memory_id"],
            content=payload["content"],
            layer=payload["layer"],
            revision=payload["revision"],
            memory_key=payload.get("memory_key"),
            topic=payload.get("topic"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"memories[{index}] is invalid: {exc}") from exc


def _generate_responses(
    engine: ReasoningEngine,
    request: ReasoningRequest,
    *,
    evaluation_mode: EvaluationMode,
) -> tuple[ReasoningResponse | None, ReasoningResponse | None]:
    if evaluation_mode == "guarded":
        return None, engine.generate(request)

    if not isinstance(engine, TraceableReasoningEngine):
        raise ValueError(
            f"{engine.__class__.__name__} does not expose raw reasoning traces. "
            "Use evaluation mode 'guarded'."
        )

    trace = engine.generate_trace(request)
    if evaluation_mode == "raw":
        return trace.raw_response, None
    return trace.raw_response, trace.guarded_response


def _evaluate_response(
    case: BenchmarkCase,
    response: ReasoningResponse | None,
    *,
    max_words: int,
) -> BenchmarkEvaluation | None:
    if response is None:
        return None

    memory_action = response.proposed_memory_action
    proposed_action = memory_action.action if memory_action else None
    response_words = len(response.spoken_response.split())
    issues = _evaluate_case(
        case,
        response_text=response.spoken_response,
        response_words=response_words,
        max_words=max_words,
        needs_confirmation=response.needs_confirmation,
        proposed_memory_action=proposed_action,
        required_information_source=response.required_information_source,
        freshness_requirement=response.freshness_requirement,
    )
    return BenchmarkEvaluation(
        spoken_response=response.spoken_response,
        response_words=response_words,
        needs_confirmation=response.needs_confirmation,
        proposed_memory_action=proposed_action,
        confidence=response.confidence,
        required_information_source=response.required_information_source,
        freshness_requirement=response.freshness_requirement,
        metadata=response.metadata,
        passed_checks=not issues,
        issues=tuple(issues),
    )


def _passed_evaluation_count(
    results: list[BenchmarkResult],
    attribute: Literal["raw_evaluation", "guarded_evaluation"],
) -> int | None:
    evaluations = [
        evaluation
        for result in results
        if (evaluation := getattr(result, attribute)) is not None
    ]
    if not evaluations:
        return None
    return sum(evaluation.passed_checks for evaluation in evaluations)


def write_benchmark_report(report: dict[str, Any], output_path: Path) -> None:
    """Write benchmark report JSON to disk."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _evaluate_case(
    case: BenchmarkCase,
    *,
    response_text: str,
    response_words: int,
    max_words: int,
    needs_confirmation: bool,
    proposed_memory_action: str | None,
    required_information_source: str,
    freshness_requirement: str,
) -> list[str]:
    issues: list[str] = []
    checks = case.checks or {}
    normalized_response = response_text.lower()

    if response_words > max_words:
        issues.append("response_exceeds_max_words")

    expected_confirmation = checks.get("needs_confirmation")
    if (
        isinstance(expected_confirmation, bool)
        and needs_confirmation != expected_confirmation
    ):
        issues.append(
            f"needs_confirmation_expected_{str(expected_confirmation).lower()}"
        )

    if "memory_action" in checks:
        expected_action = checks["memory_action"]
        if proposed_memory_action != expected_action:
            issues.append(f"memory_action_expected_{expected_action}")

    expected_source = checks.get("information_source")
    if (
        isinstance(expected_source, str)
        and required_information_source != expected_source
    ):
        issues.append(f"information_source_expected_{expected_source}")

    expected_freshness = checks.get("freshness_requirement")
    if (
        isinstance(expected_freshness, str)
        and freshness_requirement != expected_freshness
    ):
        issues.append(f"freshness_requirement_expected_{expected_freshness}")

    required_any = checks.get("must_contain_any")
    if isinstance(required_any, list) and required_any:
        terms = [term.lower() for term in required_any if isinstance(term, str)]
        if terms and not any(term in normalized_response for term in terms):
            issues.append("missing_required_term")

    required_all = checks.get("must_contain_all")
    if isinstance(required_all, list) and required_all:
        terms = [term.lower() for term in required_all if isinstance(term, str)]
        missing_terms = [term for term in terms if term not in normalized_response]
        if missing_terms:
            issues.append("missing_required_terms")

    forbidden_any = checks.get("must_not_contain_any")
    if isinstance(forbidden_any, list) and forbidden_any:
        terms = [term.lower() for term in forbidden_any if isinstance(term, str)]
        if any(term in normalized_response for term in terms):
            issues.append("contains_forbidden_term")

    return issues
