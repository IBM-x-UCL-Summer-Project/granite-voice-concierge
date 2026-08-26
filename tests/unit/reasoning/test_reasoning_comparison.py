"""Tests for reasoning model comparison helpers."""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks.reasoning.comparison import (
    failed_model_row,
    summarize_benchmark_report,
    write_comparison_summary,
)


def test_summarize_benchmark_report_counts_passes_and_issues() -> None:
    report = {
        "elapsed_ms": 30.0,
        "results": [
            {
                "latency_ms": 10.0,
                "passed_checks": True,
                "issues": [],
            },
            {
                "latency_ms": 20.0,
                "passed_checks": False,
                "issues": ("missing_required_term", "missing_required_term"),
            },
        ],
    }

    row = summarize_benchmark_report(
        report,
        model="granite-test",
        report_path=Path("report.json"),
    )

    assert row.model == "granite-test"
    assert row.case_count == 2
    assert row.repetitions == 1
    assert row.total_responses == 2
    assert row.passed_responses == 1
    assert row.failed_responses == 1
    assert row.pass_rate == 0.5
    assert row.average_latency_ms == 15.0
    assert row.issue_counts == {"missing_required_term": 2}
    assert row.raw_pass_rate is None
    assert row.guarded_pass_rate == 0.5


def test_write_comparison_summary_writes_json_and_markdown(tmp_path: Path) -> None:
    row = failed_model_row("granite-test", "not installed")

    summary = write_comparison_summary([row], output_dir=tmp_path)

    assert summary == {"models": [row.__dict__]}
    assert json.loads((tmp_path / "comparison-summary.json").read_text()) == summary
    markdown = (tmp_path / "comparison-summary.md").read_text()
    assert "granite-test" in markdown
    assert "not installed" in markdown
    assert "Rank" not in markdown


def test_write_comparison_summary_preserves_candidate_order(tmp_path: Path) -> None:
    first = failed_model_row("slower-model", "not installed")
    second = failed_model_row("faster-model", "not installed")

    summary = write_comparison_summary([first, second], output_dir=tmp_path)

    assert [model["model"] for model in summary["models"]] == [
        "slower-model",
        "faster-model",
    ]
    assert "best_model" not in summary
    assert "ranking_basis" not in summary


def test_summarize_benchmark_report_separates_raw_and_guarded_results() -> None:
    report = {
        "evaluation_mode": "both",
        "elapsed_ms": 20.0,
        "guard_interventions": 1,
        "total_cases": 1,
        "repetitions": 3,
        "model": {
            "digest": "abcdef1234567890",
            "parameter_size": "8.0B",
            "quantization_level": "Q4_K_M",
        },
        "results": [
            {
                "case_id": "memory_store",
                "repetition": 2,
                "latency_ms": 20.0,
                "passed_checks": True,
                "issues": [],
                "guard_intervened": True,
                "raw_evaluation": {
                    "passed_checks": False,
                    "issues": ["needs_confirmation_expected_true"],
                },
                "guarded_evaluation": {
                    "passed_checks": True,
                    "issues": [],
                },
            }
        ],
    }

    row = summarize_benchmark_report(
        report,
        model="granite-test",
        report_path=Path("report.json"),
    )

    assert row.raw_passed_responses == 0
    assert row.raw_pass_rate == 0.0
    assert row.guarded_passed_responses == 1
    assert row.guarded_pass_rate == 1.0
    assert row.guard_interventions == 1
    assert row.case_count == 1
    assert row.repetitions == 3
    assert row.model_digest == "abcdef1234567890"
    assert row.parameter_size == "8.0B"
    assert row.quantization_level == "Q4_K_M"
    assert row.raw_failed_responses == ["memory_store [run 2]"]
    assert row.guarded_failed_responses == []
    assert row.raw_issue_counts == {"needs_confirmation_expected_true": 1}


def test_comparison_markdown_shows_both_evaluation_stages(tmp_path: Path) -> None:
    report = {
        "evaluation_mode": "both",
        "elapsed_ms": 20.0,
        "results": [
            {
                "case_id": "memory_store",
                "latency_ms": 20.0,
                "passed_checks": True,
                "issues": [],
                "guard_intervened": True,
                "raw_evaluation": {
                    "passed_checks": False,
                    "issues": ["needs_confirmation_expected_true"],
                },
                "guarded_evaluation": {
                    "passed_checks": True,
                    "issues": [],
                },
            }
        ],
    }
    row = summarize_benchmark_report(
        report,
        model="granite-test",
        report_path=Path("report.json"),
    )

    write_comparison_summary([row], output_dir=tmp_path)

    markdown = (tmp_path / "comparison-summary.md").read_text()
    assert "Guarded pass" in markdown
    assert "Raw pass" in markdown
    assert "100.00% (1/1)" in markdown
    assert "0.00% (0/1)" in markdown
    assert "`memory_store`" in markdown
    assert "Detailed report: `report.json`" in markdown
    assert "Automated checks are diagnostic only" in markdown
