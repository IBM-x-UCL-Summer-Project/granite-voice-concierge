"""Comparison helpers for local reasoning benchmark reports."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ModelComparisonRow:
    """Summary row for one candidate model benchmark run."""

    model: str
    model_digest: str | None
    parameter_size: str | None
    quantization_level: str | None
    report_path: str | None
    case_count: int
    repetitions: int
    total_responses: int
    passed_responses: int
    failed_responses: int
    pass_rate: float
    elapsed_ms: float
    average_latency_ms: float
    max_latency_ms: float
    issue_counts: dict[str, int]
    raw_passed_responses: int | None = None
    raw_pass_rate: float | None = None
    guarded_passed_responses: int | None = None
    guarded_pass_rate: float | None = None
    guard_interventions: int = 0
    structured_parse_failures: int = 0
    raw_issue_counts: dict[str, int] = field(default_factory=dict)
    guarded_issue_counts: dict[str, int] = field(default_factory=dict)
    raw_failed_responses: list[str] = field(default_factory=list)
    guarded_failed_responses: list[str] = field(default_factory=list)
    error: str | None = None


def summarize_benchmark_report(
    report: dict[str, Any],
    *,
    model: str,
    report_path: Path,
) -> ModelComparisonRow:
    """Create a comparison row from a single benchmark report."""

    results = report.get("results", ())
    if not isinstance(results, list):
        raise ValueError("Benchmark report results must be a list.")

    case_count = report.get("total_cases")
    if not isinstance(case_count, int):
        unique_case_ids = {
            result.get("case_id")
            for result in results
            if isinstance(result.get("case_id"), str)
        }
        case_count = len(unique_case_ids) if unique_case_ids else len(results)
    repetitions = report.get("repetitions")
    if not isinstance(repetitions, int):
        repetitions = 1
    total_responses = len(results)
    passed_responses = sum(
        1 for result in results if result.get("passed_checks") is True
    )
    latencies = [
        float(result["latency_ms"])
        for result in results
        if isinstance(result.get("latency_ms"), int | float)
    ]
    issue_counts: Counter[str] = Counter()
    for result in results:
        issues = result.get("issues", ())
        if isinstance(issues, list | tuple):
            issue_counts.update(issue for issue in issues if isinstance(issue, str))

    raw_summary = _summarize_evaluation_stage(
        results,
        stage="raw",
        evaluation_mode=report.get("evaluation_mode"),
    )
    guarded_summary = _summarize_evaluation_stage(
        results,
        stage="guarded",
        evaluation_mode=report.get("evaluation_mode"),
    )
    guard_interventions = report.get("guard_interventions")
    if not isinstance(guard_interventions, int):
        guard_interventions = sum(
            1 for result in results if result.get("guard_intervened") is True
        )
    structured_parse_failures = report.get("structured_parse_failures")
    if not isinstance(structured_parse_failures, int):
        structured_parse_failures = sum(
            1 for result in results if _result_has_structured_parse_error(result)
        )

    model_metadata = report.get("model")
    if not isinstance(model_metadata, dict):
        model_metadata = {}

    return ModelComparisonRow(
        model=model,
        model_digest=_optional_string(model_metadata.get("digest")),
        parameter_size=_optional_string(model_metadata.get("parameter_size")),
        quantization_level=_optional_string(model_metadata.get("quantization_level")),
        report_path=str(report_path),
        case_count=case_count,
        repetitions=repetitions,
        total_responses=total_responses,
        passed_responses=passed_responses,
        failed_responses=total_responses - passed_responses,
        pass_rate=round(
            (passed_responses / total_responses) if total_responses else 0.0,
            4,
        ),
        elapsed_ms=float(report.get("elapsed_ms", 0.0)),
        average_latency_ms=(
            round(sum(latencies) / len(latencies), 3) if latencies else 0.0
        ),
        max_latency_ms=round(max(latencies), 3) if latencies else 0.0,
        issue_counts=dict(sorted(issue_counts.items())),
        raw_passed_responses=raw_summary.passed_responses,
        raw_pass_rate=raw_summary.pass_rate,
        guarded_passed_responses=guarded_summary.passed_responses,
        guarded_pass_rate=guarded_summary.pass_rate,
        guard_interventions=guard_interventions,
        structured_parse_failures=structured_parse_failures,
        raw_issue_counts=raw_summary.issue_counts,
        guarded_issue_counts=guarded_summary.issue_counts,
        raw_failed_responses=raw_summary.failed_responses,
        guarded_failed_responses=guarded_summary.failed_responses,
    )


@dataclass(frozen=True)
class _StageSummary:
    passed_responses: int | None
    pass_rate: float | None
    issue_counts: dict[str, int]
    failed_responses: list[str]


def _summarize_evaluation_stage(
    results: list[dict[str, Any]],
    *,
    stage: str,
    evaluation_mode: object,
) -> _StageSummary:
    evaluations: list[tuple[dict[str, Any], dict[str, Any]]] = []
    key = f"{stage}_evaluation"
    for result in results:
        evaluation = result.get(key)
        if isinstance(evaluation, dict):
            evaluations.append((result, evaluation))

    if not evaluations and _top_level_represents_stage(stage, evaluation_mode):
        evaluations = [(result, result) for result in results]

    if not evaluations:
        return _StageSummary(None, None, {}, [])

    passed_responses = sum(
        1 for _, evaluation in evaluations if evaluation.get("passed_checks") is True
    )
    issue_counts: Counter[str] = Counter()
    failed_responses: list[str] = []
    for result, evaluation in evaluations:
        issues = evaluation.get("issues", ())
        if isinstance(issues, list | tuple):
            issue_counts.update(issue for issue in issues if isinstance(issue, str))
        if evaluation.get("passed_checks") is False:
            case_id = result.get("case_id")
            if isinstance(case_id, str):
                repetition = result.get("repetition")
                suffix = f" [run {repetition}]" if isinstance(repetition, int) else ""
                failed_responses.append(f"{case_id}{suffix}")

    return _StageSummary(
        passed_responses=passed_responses,
        pass_rate=round(passed_responses / len(evaluations), 4),
        issue_counts=dict(sorted(issue_counts.items())),
        failed_responses=failed_responses,
    )


def _top_level_represents_stage(stage: str, evaluation_mode: object) -> bool:
    if stage == "raw":
        return evaluation_mode == "raw"
    return evaluation_mode in (None, "guarded", "both")


def failed_model_row(model: str, error: str) -> ModelComparisonRow:
    """Create a comparison row for a model that could not be benchmarked."""

    return ModelComparisonRow(
        model=model,
        model_digest=None,
        parameter_size=None,
        quantization_level=None,
        report_path=None,
        case_count=0,
        repetitions=0,
        total_responses=0,
        passed_responses=0,
        failed_responses=0,
        pass_rate=0.0,
        elapsed_ms=0.0,
        average_latency_ms=0.0,
        max_latency_ms=0.0,
        issue_counts={},
        error=error,
    )


def write_comparison_summary(
    rows: list[ModelComparisonRow],
    *,
    output_dir: Path,
    experiment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write unranked JSON and Markdown statistics to an output directory."""

    output_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {"models": [asdict(row) for row in rows]}
    if experiment is not None:
        summary["experiment"] = experiment

    json_path = output_dir / "comparison-summary.json"
    markdown_path = output_dir / "comparison-summary.md"
    json_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(
        _markdown_summary(rows, experiment=experiment),
        encoding="utf-8",
    )
    return summary


def _markdown_summary(
    rows: list[ModelComparisonRow],
    *,
    experiment: dict[str, Any] | None,
) -> str:
    lines = [
        "# Local Reasoning Model Comparison",
        "",
        "Scoring was performed by deterministic Python checks with no partial "
        "credit and no human or LLM judge. A response passes only when all "
        "applicable checks pass.",
        "Raw scores represent the schema-parsed model output before policy "
        "guards and word-limit shaping. Guarded scores represent the same "
        "generation after those controls.",
        "Guard interventions count responses carrying a named `policy_guard`; "
        "an intervention does not necessarily convert a failure to a pass.",
        "Schema failures count generations that could not be validated against "
        "the required structured response and therefore fail scoring.",
        "Automated checks are diagnostic only. Review detailed responses before "
        "selecting a model.",
        "",
    ]
    lines.extend(_markdown_experiment(experiment))
    lines.extend(
        [
            "| Model | Quant. | Digest | Responses | Guarded pass | Raw pass | "
            "Guard interventions | Schema failures | Avg latency ms | "
            "Max latency ms | Error |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | "
            "---: | --- |",
        ]
    )
    for row in rows:
        error = row.error or "-"
        guarded_score = _format_stage_score(
            row.guarded_pass_rate,
            row.guarded_passed_responses,
            row.total_responses,
        )
        raw_score = _format_stage_score(
            row.raw_pass_rate,
            row.raw_passed_responses,
            row.total_responses,
        )
        digest = row.model_digest[:12] if row.model_digest else "-"
        lines.append(
            "| "
            f"`{row.model}` | "
            f"{row.quantization_level or '-'} | "
            f"`{digest}` | "
            f"{row.total_responses} | "
            f"{guarded_score} | "
            f"{raw_score} | "
            f"{row.guard_interventions} | "
            f"{row.structured_parse_failures} | "
            f"{row.average_latency_ms:.1f} | "
            f"{row.max_latency_ms:.1f} | "
            f"{error} |"
        )

    lines.append("")
    lines.append("## Issue Counts")
    lines.append("")
    for row in rows:
        lines.append(f"### `{row.model}`")
        if row.error:
            lines.append("")
            lines.append(f"- Error: {row.error}")
            lines.append("")
            continue

        lines.append("")
        lines.append(f"- Detailed report: `{row.report_path}`")

        if row.raw_pass_rate is not None:
            lines.append(
                "- Raw failed responses: "
                f"{_format_failed_responses(row.raw_failed_responses)}"
            )
            lines.extend(_format_issue_counts("Raw issues", row.raw_issue_counts))

        if row.guarded_pass_rate is not None:
            lines.append("")
            lines.append(
                "- Guarded failed responses: "
                f"{_format_failed_responses(row.guarded_failed_responses)}"
            )
            lines.extend(
                _format_issue_counts("Guarded issues", row.guarded_issue_counts)
            )

        if row.raw_pass_rate is not None or row.guarded_pass_rate is not None:
            lines.append("")
            continue

        if not row.issue_counts:
            lines.append("")
            lines.append("- No failed checks.")
            lines.append("")
            continue

        lines.append("")
        for issue, count in row.issue_counts.items():
            lines.append(f"- `{issue}`: {count}")
        lines.append("")

    return "\n".join(lines)


def _format_stage_score(
    pass_rate: float | None,
    passed_cases: int | None,
    total_cases: int,
) -> str:
    if pass_rate is None or passed_cases is None:
        return "-"
    return f"{pass_rate:.2%} ({passed_cases}/{total_cases})"


def _format_failed_responses(response_ids: list[str]) -> str:
    if not response_ids:
        return "none"
    return ", ".join(f"`{response_id}`" for response_id in response_ids)


def _markdown_experiment(experiment: dict[str, Any] | None) -> list[str]:
    if experiment is None:
        return []

    suite = experiment.get("suite")
    generation = experiment.get("generation")
    lines = ["## Reproducibility", ""]
    if isinstance(suite, dict):
        lines.append(
            "- Suite: "
            f"`{suite.get('name', 'unknown')}`; "
            f"SHA-256 `{suite.get('sha256', 'unknown')}`."
        )
    if isinstance(generation, dict):
        lines.append(
            "- Generation: prompt "
            f"`{generation.get('prompt_version', 'unknown')}`, temperature "
            f"{generation.get('temperature', 'unknown')}, top-p "
            f"{generation.get('top_p', 'unknown')}, context "
            f"{generation.get('num_ctx', 'unknown')}, prediction budget "
            f"{generation.get('num_predict', 'unknown')} tokens, spoken limit "
            f"{generation.get('max_words', 'unknown')} words, thinking "
            f"{generation.get('thinking', 'unknown')}, seed "
            f"{generation.get('seed', 'not set')}."
        )
    lines.append("")
    return lines


def _optional_string(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _result_has_structured_parse_error(result: dict[str, Any]) -> bool:
    raw_evaluation = result.get("raw_evaluation")
    if isinstance(raw_evaluation, dict):
        metadata = raw_evaluation.get("metadata")
    else:
        metadata = result.get("metadata")
    return isinstance(metadata, dict) and "structured_parse_error" in metadata


def _format_issue_counts(label: str, issue_counts: dict[str, int]) -> list[str]:
    if not issue_counts:
        return [f"- {label}: none"]
    formatted = ", ".join(
        f"`{issue}` ({count})" for issue, count in issue_counts.items()
    )
    return [f"- {label}: {formatted}"]
