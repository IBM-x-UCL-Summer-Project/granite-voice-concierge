"""Utilities for comparing local reasoning benchmark reports."""

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
    report_path: str | None
    total_cases: int
    passed_cases: int
    failed_cases: int
    pass_rate: float
    elapsed_ms: float
    average_latency_ms: float
    max_latency_ms: float
    issue_counts: dict[str, int]
    raw_passed_cases: int | None = None
    raw_pass_rate: float | None = None
    guarded_passed_cases: int | None = None
    guarded_pass_rate: float | None = None
    guard_interventions: int = 0
    raw_issue_counts: dict[str, int] = field(default_factory=dict)
    guarded_issue_counts: dict[str, int] = field(default_factory=dict)
    raw_failed_case_ids: list[str] = field(default_factory=list)
    guarded_failed_case_ids: list[str] = field(default_factory=list)
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

    total_cases = len(results)
    passed_cases = sum(1 for result in results if result.get("passed_checks") is True)
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

    return ModelComparisonRow(
        model=model,
        report_path=str(report_path),
        total_cases=total_cases,
        passed_cases=passed_cases,
        failed_cases=total_cases - passed_cases,
        pass_rate=round((passed_cases / total_cases) if total_cases else 0.0, 4),
        elapsed_ms=float(report.get("elapsed_ms", 0.0)),
        average_latency_ms=(
            round(sum(latencies) / len(latencies), 3) if latencies else 0.0
        ),
        max_latency_ms=round(max(latencies), 3) if latencies else 0.0,
        issue_counts=dict(sorted(issue_counts.items())),
        raw_passed_cases=raw_summary.passed_cases,
        raw_pass_rate=raw_summary.pass_rate,
        guarded_passed_cases=guarded_summary.passed_cases,
        guarded_pass_rate=guarded_summary.pass_rate,
        guard_interventions=guard_interventions,
        raw_issue_counts=raw_summary.issue_counts,
        guarded_issue_counts=guarded_summary.issue_counts,
        raw_failed_case_ids=raw_summary.failed_case_ids,
        guarded_failed_case_ids=guarded_summary.failed_case_ids,
    )


@dataclass(frozen=True)
class _StageSummary:
    passed_cases: int | None
    pass_rate: float | None
    issue_counts: dict[str, int]
    failed_case_ids: list[str]


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

    passed_cases = sum(
        1 for _, evaluation in evaluations if evaluation.get("passed_checks") is True
    )
    issue_counts: Counter[str] = Counter()
    failed_case_ids: list[str] = []
    for result, evaluation in evaluations:
        issues = evaluation.get("issues", ())
        if isinstance(issues, list | tuple):
            issue_counts.update(issue for issue in issues if isinstance(issue, str))
        if evaluation.get("passed_checks") is False:
            case_id = result.get("case_id")
            if isinstance(case_id, str):
                failed_case_ids.append(case_id)

    return _StageSummary(
        passed_cases=passed_cases,
        pass_rate=round(passed_cases / len(evaluations), 4),
        issue_counts=dict(sorted(issue_counts.items())),
        failed_case_ids=failed_case_ids,
    )


def _top_level_represents_stage(stage: str, evaluation_mode: object) -> bool:
    if stage == "raw":
        return evaluation_mode == "raw"
    return evaluation_mode in (None, "guarded", "both")


def failed_model_row(model: str, error: str) -> ModelComparisonRow:
    """Create a comparison row for a model that could not be benchmarked."""

    return ModelComparisonRow(
        model=model,
        report_path=None,
        total_cases=0,
        passed_cases=0,
        failed_cases=0,
        pass_rate=0.0,
        elapsed_ms=0.0,
        average_latency_ms=0.0,
        max_latency_ms=0.0,
        issue_counts={},
        error=error,
    )


def rank_models(rows: list[ModelComparisonRow]) -> list[ModelComparisonRow]:
    """Rank by guarded pass rate when available, then primary rate and latency."""

    return sorted(
        rows,
        key=lambda row: (
            row.error is not None,
            -(
                row.guarded_pass_rate
                if row.guarded_pass_rate is not None
                else row.pass_rate
            ),
            row.average_latency_ms,
            row.model,
        ),
    )


def write_comparison_summary(
    rows: list[ModelComparisonRow],
    *,
    output_dir: Path,
) -> dict[str, Any]:
    """Write JSON and Markdown comparison summaries to an output directory."""

    output_dir.mkdir(parents=True, exist_ok=True)
    ranked_rows = rank_models(rows)
    summary = {
        "models": [asdict(row) for row in ranked_rows],
        "best_model": _best_model(ranked_rows),
        "ranking_basis": (
            "guarded_pass_rate_when_available_then_primary_pass_rate_then_"
            "average_latency"
        ),
    }

    json_path = output_dir / "comparison-summary.json"
    markdown_path = output_dir / "comparison-summary.md"
    json_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_markdown_summary(ranked_rows), encoding="utf-8")
    return summary


def _best_model(rows: list[ModelComparisonRow]) -> str | None:
    for row in rows:
        if row.error is None:
            return row.model
    return None


def _markdown_summary(rows: list[ModelComparisonRow]) -> str:
    lines = [
        "# Local Reasoning Model Comparison",
        "",
        "Guarded scores represent product behavior. Raw scores represent the "
        "parsed model output before policy guards and word-limit shaping.",
        "",
        "| Rank | Model | Guarded pass | Raw pass | Guards | Avg latency ms | "
        "Max latency ms | Error |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for index, row in enumerate(rows, start=1):
        error = row.error or "-"
        guarded_score = _format_stage_score(
            row.guarded_pass_rate,
            row.guarded_passed_cases,
            row.total_cases,
        )
        raw_score = _format_stage_score(
            row.raw_pass_rate,
            row.raw_passed_cases,
            row.total_cases,
        )
        lines.append(
            "| "
            f"{index} | "
            f"`{row.model}` | "
            f"{guarded_score} | "
            f"{raw_score} | "
            f"{row.guard_interventions} | "
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

        if row.raw_pass_rate is not None:
            lines.append("")
            lines.append(
                f"- Raw failed cases: {_format_failed_cases(row.raw_failed_case_ids)}"
            )
            lines.extend(_format_issue_counts("Raw issues", row.raw_issue_counts))

        if row.guarded_pass_rate is not None:
            lines.append("")
            lines.append(
                "- Guarded failed cases: "
                f"{_format_failed_cases(row.guarded_failed_case_ids)}"
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


def _format_failed_cases(case_ids: list[str]) -> str:
    if not case_ids:
        return "none"
    return ", ".join(f"`{case_id}`" for case_id in case_ids)


def _format_issue_counts(label: str, issue_counts: dict[str, int]) -> list[str]:
    if not issue_counts:
        return [f"- {label}: none"]
    formatted = ", ".join(
        f"`{issue}` ({count})" for issue, count in issue_counts.items()
    )
    return [f"- {label}: {formatted}"]
