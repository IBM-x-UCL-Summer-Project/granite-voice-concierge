"""Render suite results as JSON and as a Markdown benchmark report.

The Markdown follows the shape of the existing files under `benchmarks/`, so a
report produced here can sit beside the June wake-word and VAD results without
looking foreign. Both artifacts are written from the same dictionary: the JSON
is the record, the Markdown is what gets read.
"""

from __future__ import annotations

# Standard library
import json
from pathlib import Path
from typing import Any


def write_json(path: Path, results: dict) -> None:
    """Write the full result record."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, indent=2, default=str))


def write_markdown(path: Path, results: dict) -> None:
    """Write the human-readable report."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(results))


def render_markdown(results: dict) -> str:
    """Build the Markdown report from a results record."""
    lines: list[str] = ["# Voice Pipeline Benchmark — full suite", ""]
    lines += _render_header(results)
    lines += _render_caveats(results)

    components = results.get("components", {})
    if "text_to_speech" in components:
        lines += _render_tts(components["text_to_speech"])
    if "speech_to_text" in components:
        lines += _render_stt(components["speech_to_text"])
    if "wake_word" in components:
        lines += _render_wake_word(components["wake_word"])
    if "voice_activity_detection" in components:
        lines += _render_vad(components["voice_activity_detection"])
    if "reasoning" in components:
        lines += _render_reasoning(components["reasoning"])
    if results.get("pipeline"):
        lines += _render_pipeline(results["pipeline"])

    lines += _render_failures(results)
    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------------
# sections
# --------------------------------------------------------------------------


def _render_header(results: dict) -> list[str]:
    device = results.get("device", {})
    provenance = results.get("provenance", {})
    versions = results.get("versions", {})
    backend = results.get("text_to_speech", {})

    dirty = provenance.get("git_dirty")
    dirty_note = (
        " (working tree dirty — results may not match this commit)" if dirty else ""
    )

    lines = ["## Run", ""]
    lines += [
        f"- Captured: {provenance.get('captured_utc', 'unknown')}",
        f"- Commit: `{provenance.get('git_commit', 'unknown')}`"
        f" on `{provenance.get('git_branch', 'unknown')}`{dirty_note}",
        f"- Machine: {device.get('chip') or device.get('machine')}"
        f" ({device.get('physical_cores')} cores, {device.get('ram_gb')} GB)",
        f"- OS: {device.get('os')}",
        f"- Python: {device.get('python')}",
        "",
        "## Backends measured",
        "",
        f"- **Text to speech: `{backend.get('selected', 'unknown')}`**"
        f" — {backend.get('detail', '')}",
    ]
    if backend.get("requested") == "auto":
        lines.append("  - Selected automatically; the suite reports what actually ran.")
    for probe in backend.get("probes", []):
        if not probe.get("available"):
            lines.append(f"  - `{probe['name']}` unavailable: {probe['detail']}")
    lines += [""]
    if versions:
        lines += ["| Package | Version |", "| --- | --- |"]
        lines += [
            f"| `{name}` | {version or 'not installed'} |"
            for name, version in sorted(versions.items())
        ]
        lines += [""]
    return lines


def _render_caveats(results: dict) -> list[str]:
    """State the limitations up front rather than burying them."""
    return [
        "## How to read these numbers",
        "",
        "- Request audio is **synthesized, not spoken**. Accuracy figures are",
        "  therefore clean-speech ceilings: no accent variation, no",
        "  disfluency, no background noise, one voice. They do not estimate",
        "  accuracy for real users, and specifically not for older adults,",
        "  which is the target group.",
        "- Wake-word thresholds are swept as **independent replays**, each with",
        "  the detector reset, rather than by re-scoring one run.",
        "- Wake-word latency is **per-frame model inference**, not",
        "  user-perceived activation latency.",
        "- Replayed audio is injected digitally and never passes through a",
        "  speaker, a room or a microphone. Clean-condition wake-word results",
        "  are optimistic; the noisy conditions are the ones that show a",
        "  threshold trade-off, and live trials remain the authority.",
        "- The whole-pipeline span excludes wake word and VAD (they need a live",
        "  microphone) and excludes playback.",
        "- Sample sizes here are small. Treat every figure as indicative unless",
        "  the run was repeated.",
        "",
    ]


def _render_tts(data: dict) -> list[str]:
    lines = [
        f"## Text to speech — `{data['backend']}`",
        "",
        f"Each text synthesized {data['repeats_per_text']} times.",
        "",
        "| Length | Chars | Audio (ms) | Mean synth (ms) | Real-time factor |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for row in data["by_length"]:
        factor = row["real_time_factor"]
        lines.append(
            f"| {row['label']} | {row['characters']} | {row['audio_ms']:.0f} "
            f"| {row['latency']['mean_ms']:.1f} "
            f"| {factor if factor is not None else '—'} |"
        )
    lines += [
        "",
        "A real-time factor below 1.0 means synthesis outpaces playback, so",
        "speech can begin before the whole utterance is generated.",
        "",
    ]
    return lines


def _render_stt(data: dict) -> list[str]:
    config = data["config"]
    lines = [
        f"## Speech to text — `{config['model_size']}`",
        "",
        f"{config['device']}, {config['compute_type']}, "
        f"beam {config['beam_size']}, VAD filter {config['vad_filter']}.",
        "",
        "| Corpus | Utterances | Ref. words | WER | WER (numbers norm.) | Exact |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, group in data["groups"].items():
        accuracy = group["accuracy"]
        lines.append(
            f"| {name.replace('_', ' ')} | {accuracy['utterances']} "
            f"| {accuracy['reference_words']} "
            f"| {accuracy['corpus_wer']:.2%} "
            f"| {accuracy['corpus_wer_numbers_normalized']:.2%} "
            f"| {accuracy['exact_match_rate']:.0%} |"
        )
    overall = data["all_synthetic"]
    lines.append(
        f"| **all synthetic** | **{overall['utterances']}** "
        f"| **{overall['reference_words']}** "
        f"| **{overall['corpus_wer']:.2%}** "
        f"| **{overall['corpus_wer_numbers_normalized']:.2%}** "
        f"| **{overall['exact_match_rate']:.0%}** |"
    )
    lines += [
        "",
        f"Errors: {overall['substitutions']} substitutions, "
        f"{overall['deletions']} deletions, {overall['insertions']} insertions.",
        "",
        "The numbers-normalized column exists because a model that writes",
        '"10" where the reference says "ten" has recognized the word and only',
        "disagrees about orthography. Quote whichever is appropriate, but say",
        "which one.",
        "",
    ]
    _append_misses(lines, data)
    return lines


def _append_misses(lines: list[str], data: dict) -> None:
    """List the utterances that were not transcribed exactly."""
    misses = [
        utterance
        for group in data["groups"].values()
        for utterance in group["utterances"]
        if not utterance["exact_match"]
    ]
    if not misses:
        lines += ["Every utterance transcribed exactly.", ""]
        return
    lines += [
        "### Utterances not transcribed exactly",
        "",
        "| WER | Reference | Recognized |",
        "| ---: | --- | --- |",
    ]
    for miss in misses:
        lines.append(
            f"| {miss['wer']:.2%} | {miss['reference']} | {miss['hypothesis']} |"
        )
    lines.append("")


def _render_wake_word(data: dict) -> list[str]:
    populations = data["populations"]
    lines = [
        "## Wake word",
        "",
        data["method"],
        "",
        f"Populations per threshold: {populations['positive']} positive, "
        f"{populations['confusable']} confusable, {populations['neutral']} neutral.",
        "",
        "| Condition | Threshold | Detection | Confusable | Neutral | Mean conf. |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for condition in data["by_condition"]:
        label = condition["condition"]
        for row in condition["by_threshold"]:
            groups = row["groups"]
            positive = groups["positive"]
            confidence = positive["mean_confidence"]
            lines.append(
                f"| {label} | {row['threshold']} "
                f"| {positive['activations']}/{positive['trials']} "
                f"({positive['rate']:.0%}) "
                f"| {groups['confusable']['activations']}/"
                f"{groups['confusable']['trials']} "
                f"({groups['confusable']['rate']:.0%}) "
                f"| {groups['neutral']['activations']}/{groups['neutral']['trials']} "
                f"({groups['neutral']['rate']:.0%}) "
                f"| {confidence if confidence is not None else '—'} |"
            )
    latency = data["inference_latency"]
    lines += [
        "",
        f"> **Acoustic caveat.** {data['acoustic_caveat']}",
        "",
        "**Confusable activation is an adversarial rate**: every one of those",
        "phrases was chosen to sound like the wake word. It is a worst case,",
        "not a background false-accept rate, and is not comparable with",
        "false-accepts-per-hour figures reported elsewhere. The neutral column",
        "is the closer analogue to that metric.",
        "",
        f"Inference latency per 80 ms frame: mean {latency.get('mean_ms', 0):.2f} ms, "
        f"median {latency.get('median_ms', 0):.2f} ms, "
        f"max {latency.get('max_ms', 0):.2f} ms "
        f"(n = {latency.get('count', 0)} frames).",
        "",
        f"> {latency.get('note', '')}",
        "",
    ]
    return lines


def _render_vad(data: dict) -> list[str]:
    config = data["config"]
    continuous = data["continuous_speech"]
    paused = data["pause_tolerance"]
    lines = [
        "## Voice activity detection",
        "",
        f"Silence threshold {config['min_silence_ms']} ms, "
        f"{config['chunk_samples']}-sample chunks at {config['rate']} Hz.",
        "",
        "| Utterance | Captured | Input (ms) | Captured (ms) | Retention |",
        "| --- | :-: | ---: | ---: | ---: |",
    ]
    for trial in continuous["detail"]:
        lines.append(
            f"| {trial['label']} | {'yes' if trial['captured'] else 'no'} "
            f"| {trial['input_ms']:.0f} | {trial['captured_ms']:.0f} "
            f"| {trial['retention_ratio']:.2f} |"
        )
    lines += [
        "",
        f"Continuous-speech capture rate: {continuous['captured']}/"
        f"{continuous['trials']} ({continuous['capture_rate']:.0%}).",
        "",
        f"> {data['note']}",
        "",
    ]
    lines += _render_pause_tolerance(paused)
    return lines


def _render_pause_tolerance(data: dict) -> list[str]:
    """Report where a mid-utterance pause starts costing the rest of the sentence."""
    lines = [
        "### Mid-utterance pause tolerance",
        "",
        f'Utterance split as "{data["first_half"]}" … "{data["second_half"]}", '
        "joined by a constructed silence gap of an exact length. Configured "
        f"silence threshold: {data['configured_min_silence_ms']} ms.",
        "",
        "| Gap (ms) | Captured | Input (ms) | Captured (ms) | Cut off early |",
        "| ---: | :-: | ---: | ---: | :-: |",
    ]
    for trial in data["trials"]:
        lines.append(
            f"| {trial['gap_ms']} | {'yes' if trial['captured'] else 'no'} "
            f"| {trial['input_ms']:.0f} | {trial['captured_ms']:.0f} "
            f"| {'**YES**' if trial['cut_off_early'] else 'no'} |"
        )

    shortest = data["shortest_pause_cut_off_ms"]
    longest = data["longest_pause_survived_ms"]
    lines += [
        "",
        (
            f"Shortest pause that lost the tail of the sentence: **{shortest} ms**."
            if shortest is not None
            else "No pause length tested cut the utterance short."
        ),
        (
            f" Longest pause ridden out intact: {longest} ms."
            if longest is not None
            else ""
        ),
        "",
        "This is the accessibility question made concrete. Older adults pause",
        "mid-sentence more often than the threshold assumes, and every pause",
        "at or beyond the cut-off length costs them the rest of what they were",
        "saying. Report the cut-off length, not just the capture rate.",
        "",
    ]
    return lines


def _render_reasoning(data: dict) -> list[str]:
    latency = data["latency"]
    lines = [
        f"## Reasoning — `{data.get('model') or 'default'}`",
        "",
        "| Turns | Min (ms) | Mean (ms) | Median (ms) | Max (ms) | SD (ms) |",
        "| ---: | ---: | ---: | ---: | ---: | ---: |",
        f"| {latency.get('count', 0)} | {latency.get('min_ms', 0):.0f} "
        f"| {latency.get('mean_ms', 0):.0f} | {latency.get('median_ms', 0):.0f} "
        f"| {latency.get('max_ms', 0):.0f} | {latency.get('stdev_ms', 0):.0f} |",
        "",
        f"> {data.get('note', '')}",
        "",
    ]
    return lines


def _render_pipeline(data: dict) -> list[str]:
    summary = data["summary"]
    latency = summary["latency_s"]
    transcription = summary.get("transcription", {})
    lines = [
        "## Whole pipeline",
        "",
        f"Text to speech: `{data['text_to_speech_backend']}`. "
        f"Reasoning: `{data.get('reasoning_model') or 'default'}`. "
        f"Memory loaded: {data['memory_loaded']}.",
        "",
        f"> {data['scope']}",
        "",
        f"{summary['turns']} turns cycling {data['unique_requests']} unique "
        "requests, after one unrecorded warm-up turn.",
        "",
        "| Turn | Request | Latency (s) | WER | App RSS (MB) | Total (MB) | Peak CPU |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for turn in data["turns"]:
        wer = turn["wer"]
        lines.append(
            f"| {turn['index']} | {turn['request'][:40]} "
            f"| {turn['latency_s']:.2f} "
            f"| {f'{wer:.0%}' if wer is not None else '—'} "
            f"| {turn['peak_rss_app_mb']:.0f} "
            f"| {turn['attributable_total_mb']:.0f} "
            f"| {turn['peak_cpu_total']:.0f}% |"
        )
    lines += [
        "",
        "### Summary",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| End-to-end latency (min / mean / max) | "
        f"{latency['min']:.2f} / {latency['mean']:.2f} / {latency['max']:.2f} s |",
        f"| Latency standard deviation | "
        f"{summary['latency']['stdev_ms'] / 1000:.2f} s |",
        f"| Peak app process RSS | {summary['peak_rss_app_mb']:.1f} MB |",
        f"| Peak model process RSS | {summary['peak_rss_model_mb']:.1f} MB |",
        f"| Peak combined RSS | {summary['peak_rss_total_mb']:.1f} MB |",
        f"| Model weights resident | {summary['model_weights_mb']:.1f} MB |",
        f"| **Peak attributable total** | "
        f"**{summary['attributable_total_mb']:.1f} MB** |",
        f"| Peak total CPU | {summary['peak_cpu_percent_total']:.1f}% |",
        f"| Peak system memory used | {summary['peak_system_used_mb']:.1f} MB |",
        f"| Turns reporting an error | {summary['turns_with_errors']} |",
    ]
    if transcription.get("utterances"):
        lines.append(
            f"| Transcription WER across turns | "
            f"{transcription['corpus_wer']:.2%} "
            f"({transcription['corpus_wer_numbers_normalized']:.2%} "
            f"numbers normalized) |"
        )
    lines += [
        "",
        "Resident set size does not account for model weights on Apple",
        "silicon: they live in unified memory through Metal, so the runner",
        "reports tens of megabytes while gigabytes are resident. The",
        "attributable total adds the runtime's own accounting, which is the",
        "only instrument here that sees those pages.",
        "",
    ]
    return lines


def _render_failures(results: dict) -> list[str]:
    """Report stages that did not run.

    Named explicitly so a partial run is never mistaken for a complete one.
    """
    failures: dict[str, Any] = results.get("skipped", {})
    if not failures:
        return []
    lines = ["## Stages that did not run", "", "| Stage | Reason |", "| --- | --- |"]
    lines += [f"| {name} | {reason} |" for name, reason in failures.items()]
    lines += [
        "",
        "These stages are absent from the results above. Do not read the",
        "report as a complete run until they pass.",
        "",
    ]
    return lines
