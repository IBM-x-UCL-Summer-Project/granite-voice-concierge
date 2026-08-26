"""Whole-pipeline benchmark: captured audio in, spoken response out.

The measured span is speech-to-text, context, memory, reasoning and synthesis,
which is exactly what wake word and voice activity detection hand over. Those
two are excluded because they need a live microphone and would make a run
unrepeatable; they are measured separately in `components`.

Two things differ from the earlier version of this benchmark. The synthesis
backend is injected rather than resolved through the application's fallback
chain, so a run labelled Piper contains Piper audio. And the transcript is
retained, so transcription accuracy is recorded for the same turns that
produced the latency figures instead of being unmeasurable after the fact.
"""

from __future__ import annotations

# Standard library
import time
from dataclasses import dataclass, field
from typing import Sequence

# Local
from benchmarks.suite import corpus
from benchmarks.suite.harness import (
    ResourceSampler,
    duration_ms,
    eprint,
    find_ollama_processes,
    latency_summary,
    loaded_model_memory_mb,
    reasoning_config,
    resample_to,
    score_transcript,
    summarize_transcripts,
)


@dataclass
class TurnRecord:
    """Everything observed for one complete turn."""

    index: int
    request: str
    transcript: str | None
    response: str
    latency_ms: float
    audio_ms: float
    wer: float | None
    wer_numbers_normalized: float | None
    transcript_exact: bool | None
    usage: dict = field(default_factory=dict)
    model_weights_mb: float = 0.0
    model_weights_detail: dict = field(default_factory=dict)
    attributable_total_mb: float = 0.0
    errors: tuple[str, ...] = ()


def benchmark_pipeline(
    backend_name: str,
    backend,
    *,
    turns: int = 8,
    requests: Sequence[str] | None = None,
    load_memory: bool = True,
    reasoning_model: str | None = None,
) -> dict:
    """Run `turns` complete turns and record cost and accuracy for each."""
    from voice_concierge.app.factory import build_voice_concierge_pipeline
    from voice_concierge.app.types import AppPipelineState
    from voice_concierge.voice_input.stt.factory import build_speech_to_text

    prompts = list(requests or corpus.PIPELINE_REQUESTS)
    eprint(f"  whole pipeline [{turns} turns, tts={backend_name}] ...")

    config, resolved_model = reasoning_config(reasoning_model)
    pipeline = build_voice_concierge_pipeline(
        config,
        speech_to_text=build_speech_to_text(),
        # Injected rather than built by the factory: this is what keeps a
        # failed Piper from being silently recorded as a successful Piper run.
        text_to_speech=backend,
        load_memory=load_memory,
        load_voice_io=False,
    )
    state = AppPipelineState()

    # One unrecorded warm-up turn. The first turn pays for lazy model loading
    # and would otherwise dominate every summary statistic.
    eprint("    warm-up turn (not recorded) ...")
    warm_audio = _prepare_request_audio(backend, prompts[0])
    pipeline.process_audio(warm_audio, state, synthesize=True, play=False)

    records: list[TurnRecord] = []
    for index in range(1, turns + 1):
        request = prompts[(index - 1) % len(prompts)]
        audio = _prepare_request_audio(backend, request)
        records.append(_run_turn(pipeline, audio, state, index=index, request=request))
        eprint(
            f"    turn {index}/{turns}: {records[-1].latency_ms / 1000:.2f}s  "
            f"{request!r}"
        )

    return {
        "text_to_speech_backend": backend_name,
        "reasoning_model": resolved_model,
        "memory_loaded": load_memory,
        "requests_cycled": prompts,
        "unique_requests": len(set(prompts)),
        "scope": (
            "Speech-to-text, context, memory, reasoning and synthesis. Wake "
            "word and VAD excluded (they need a live microphone); playback "
            "excluded (its duration is a property of response length)."
        ),
        "turns": [_record_as_dict(record) for record in records],
        "summary": _summarize(records),
    }


def _prepare_request_audio(backend, text: str):
    """Render a spoken request so every run hears identical audio.

    Recorded rather than live input means a latency difference between runs is
    the pipeline changing rather than the speaker. It also means the requests
    are clean synthetic speech, which the report must state.
    """
    from voice_concierge.voice_input.stt.whisper import (
        WhisperSpeechToText,  # noqa: F401
    )

    # 16 kHz mono is what the speech-to-text stage expects; synthesis backends
    # emit their own native rates.
    return resample_to(backend.synthesize(text), 16000)


def _run_turn(pipeline, audio, state, *, index: int, request: str) -> TurnRecord:
    """Run one turn under sampling and score what came back."""
    # Re-looked-up every turn: Ollama spawns the runner holding the weights
    # lazily, so a list captured before first use finds only the server.
    model_processes = find_ollama_processes()
    sampler = ResourceSampler(model_processes)

    started = time.perf_counter()
    with sampler:
        result = pipeline.process_audio(audio, state, synthesize=True, play=False)
        latency_ms = (time.perf_counter() - started) * 1000

    # Read while the model is still resident: Ollama unloads it after an idle
    # period, and an unloaded model reports nothing.
    weights_mb, weights_detail = loaded_model_memory_mb()
    usage = sampler.usage()

    transcript_text = _transcript_text(result)
    score = (
        score_transcript(request, transcript_text)
        if transcript_text is not None
        else None
    )
    return TurnRecord(
        index=index,
        request=request,
        transcript=transcript_text,
        response=(getattr(result, "spoken_response", "") or "")[:200],
        latency_ms=round(latency_ms, 1),
        audio_ms=duration_ms(audio),
        wer=score.wer if score else None,
        wer_numbers_normalized=score.wer_numbers_normalized if score else None,
        transcript_exact=score.exact_match if score else None,
        usage=usage,
        model_weights_mb=weights_mb,
        model_weights_detail=weights_detail,
        # max(), not sum(): psutil RSS and `ollama ps` can each independently
        # describe the model's resident weight memory. On some Ollama
        # versions the runner's own RSS stays tiny (tens of MB) and `ollama
        # ps` is the only instrument that sees the unified-memory pages; on
        # others the runner's RSS already reflects several GB of resident
        # weight directly. Summing them assumes the first case always holds
        # and silently double-counts the same physical memory under the
        # second, which is what happened on this machine: the runner process
        # was observed at ~4.8 GB RSS while `ollama ps` also reported ~5.7 GB
        # for the same model.
        attributable_total_mb=round(
            usage["peak_rss_app_mb"] + max(usage["peak_rss_model_mb"], weights_mb), 1
        ),
        errors=tuple(getattr(result, "errors", ()) or ()),
    )


def _transcript_text(result) -> str | None:
    """Pull the recognized text out of a turn result, if there was one."""
    transcript = getattr(result, "transcript", None)
    if transcript is None:
        return None
    return getattr(transcript, "text", None)


def _record_as_dict(record: TurnRecord) -> dict:
    """Flatten a turn record for serialization."""
    return {
        "index": record.index,
        "request": record.request,
        "transcript": record.transcript,
        "response": record.response,
        "latency_ms": record.latency_ms,
        "latency_s": round(record.latency_ms / 1000, 3),
        "audio_ms": record.audio_ms,
        "wer": record.wer,
        "wer_numbers_normalized": record.wer_numbers_normalized,
        "transcript_exact": record.transcript_exact,
        "model_weights_mb": record.model_weights_mb,
        "model_weights_detail": record.model_weights_detail,
        "attributable_total_mb": record.attributable_total_mb,
        "errors": list(record.errors),
        **record.usage,
    }


def _summarize(records: Sequence[TurnRecord]) -> dict:
    """Aggregate the turns into the figures a report quotes."""
    if not records:
        return {"turns": 0}

    latencies = [record.latency_ms for record in records]
    scores = [
        score_transcript(record.request, record.transcript)
        for record in records
        if record.transcript is not None
    ]
    peak_app_rss = max(record.usage["peak_rss_app_mb"] for record in records)
    peak_model_rss = max(record.usage["peak_rss_model_mb"] for record in records)
    peak_total_rss = max(record.usage["peak_rss_total_mb"] for record in records)
    weights = max(record.model_weights_mb for record in records)

    return {
        "turns": len(records),
        "latency": latency_summary(latencies),
        "latency_s": {
            "min": round(min(latencies) / 1000, 3),
            "mean": round(sum(latencies) / len(latencies) / 1000, 3),
            "max": round(max(latencies) / 1000, 3),
        },
        "transcription": summarize_transcripts(scores),
        "peak_rss_app_mb": peak_app_rss,
        "peak_rss_model_mb": peak_model_rss,
        "peak_rss_total_mb": peak_total_rss,
        "model_weights_mb": weights,
        # max(), not sum(): see the matching comment in _run_turn. psutil RSS
        # and `ollama ps` are two instruments that can both describe the same
        # resident weight memory, and adding them double-counts whenever RSS
        # already reflects it, which happened during measurement on this
        # machine (runner RSS ~4.8 GB alongside `ollama ps` ~5.7 GB for the
        # same model).
        "attributable_total_mb": round(peak_app_rss + max(peak_model_rss, weights), 1),
        "peak_cpu_percent_total": max(r.usage["peak_cpu_total"] for r in records),
        "peak_system_used_mb": max(r.usage["peak_system_used_mb"] for r in records),
        "turns_with_errors": sum(1 for r in records if r.errors),
    }
