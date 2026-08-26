"""Per-component benchmarks: synthesis, transcription, wake word, VAD.

Each function measures one stage against fixed material and returns a plain
dictionary, so the orchestrator can run any subset and the report writer does
not need to know which stages ran.

Every stage here is driven from recorded or synthesized audio rather than a
live microphone. That is what makes the suite runnable unattended on someone
else's machine, and it is also its main limitation: synthesized speech is
clean, evenly paced and single-voiced, so accuracy figures derived from it are
ceilings rather than estimates of real use, and replayed audio never passes
through a speaker, a room or a microphone. The report states both
limitations; live-voice trials remain the authority for anything quoted as
a detection rate.
"""

from __future__ import annotations

# Standard library
import contextlib
import io
import time
from pathlib import Path
from typing import Sequence

# Third-party
import numpy as np

# Local
from benchmarks.suite import corpus
from benchmarks.suite.harness import (
    Timer,
    add_noise,
    duration_ms,
    eprint,
    latency_summary,
    read_wav,
    reasoning_config,
    resample_to,
    score_transcript,
    summarize_transcripts,
)

#: openWakeWord consumes 80 ms frames at 16 kHz and is not tolerant of others.
WAKE_WORD_RATE: int = 16000
WAKE_WORD_CHUNK: int = 1280

#: Thresholds swept for the wake-word detector. Unlike the June benchmark,
#: each is a genuinely independent replay rather than a re-scoring of one run.
DEFAULT_THRESHOLDS: tuple[float, ...] = (0.3, 0.5, 0.7)

#: Pause lengths swept to find where an utterance gets cut in half. Spans
#: the 300 ms threshold the June benchmark used and the 500 ms it moved to.
DEFAULT_PAUSE_GAPS_MS: tuple[int, ...] = (200, 300, 400, 500, 700, 1000)

#: Noise conditions for the wake-word sweep, as (label, SNR in dB). None
#: means the audio is left as synthesized. Clean replay alone flattens the
#: sweep, so the noisy rows are what carry the threshold trade-off.
DEFAULT_NOISE_CONDITIONS: tuple[tuple[str, float | None], ...] = (
    ("clean", None),
    ("noisy_15db", 15.0),
    ("noisy_10db", 10.0),
    ("noisy_5db", 5.0),
)


# --------------------------------------------------------------------------
# text to speech
# --------------------------------------------------------------------------


def benchmark_tts(backend_name: str, backend, *, repeats: int = 3) -> dict:
    """Measure synthesis cost for the pinned backend.

    Reports a real-time factor as well as raw latency: synthesis time alone
    says nothing without the length of audio it produced, and the ratio is
    what determines whether speech can be streamed as it is generated.
    """
    eprint(f"  text-to-speech [{backend_name}] ...")
    results = []
    for label, text in corpus.SYNTHESIS_TEXTS:
        timer = Timer()
        audio = None
        for _ in range(repeats):
            audio, _ = timer.time(lambda: backend.synthesize(text))
        summary = timer.summary()
        audio_ms = duration_ms(audio)
        results.append(
            {
                "label": label,
                "characters": len(text),
                "audio_ms": audio_ms,
                "sample_rate": audio.sample_rate,
                "latency": summary,
                # < 1.0 means synthesis outpaces playback, so speech can start
                # before the whole utterance has been generated.
                "real_time_factor": (
                    round(summary["mean_ms"] / audio_ms, 3) if audio_ms else None
                ),
            }
        )

    all_latencies = [
        sample for result in results for sample in [result["latency"]["mean_ms"]]
    ]
    return {
        "backend": backend_name,
        "repeats_per_text": repeats,
        "by_length": results,
        "overall_latency": latency_summary(all_latencies),
    }


def _synthesize_corpus(backend, texts: Sequence[str], target_rate: int | None = None):
    """Render each text once, optionally resampled for a downstream component."""
    rendered = []
    for text in texts:
        audio = backend.synthesize(text)
        if target_rate is not None:
            audio = resample_to(audio, target_rate)
        rendered.append((text, audio))
    return rendered


# --------------------------------------------------------------------------
# speech to text
# --------------------------------------------------------------------------


def benchmark_stt(
    backend,
    *,
    model_size: str | None = None,
    include_recorded: bool = True,
) -> dict:
    """Measure transcription accuracy and latency for the configured model.

    Accuracy is reported both raw and with numeric tokens normalized, because
    a model that writes "10" where the reference says "ten" has recognized the
    word correctly and only disagrees about orthography.
    """
    from voice_concierge.voice_input.stt.factory import build_speech_to_text
    from voice_concierge.voice_input.stt.whisper import (
        DEFAULT_BEAM_SIZE,
        DEFAULT_COMPUTE_TYPE,
        DEFAULT_DEVICE,
        DEFAULT_MODEL_SIZE,
        DEFAULT_VAD_FILTER,
    )

    resolved_size = model_size or DEFAULT_MODEL_SIZE
    eprint(f"  speech-to-text [{resolved_size}] ...")
    stt = build_speech_to_text(resolved_size)

    groups: dict[str, dict] = {}
    for name, texts in (
        ("pipeline_requests", corpus.PIPELINE_REQUESTS),
        ("command_requests", corpus.COMMAND_REQUESTS),
        ("conversational_requests", corpus.CONVERSATIONAL_REQUESTS),
    ):
        scores, timings, utterances = [], [], []
        for text, audio in _synthesize_corpus(backend, texts):
            started = time.perf_counter()
            transcript = stt.transcribe(audio)
            elapsed_ms = (time.perf_counter() - started) * 1000
            score = score_transcript(text, transcript.text)
            scores.append(score)
            timings.append(elapsed_ms)
            utterances.append(
                {
                    "reference": score.reference,
                    "hypothesis": score.hypothesis,
                    "wer": score.wer,
                    "wer_numbers_normalized": score.wer_numbers_normalized,
                    "exact_match": score.exact_match,
                    "audio_ms": duration_ms(audio),
                    "transcribe_ms": round(elapsed_ms, 1),
                }
            )
        groups[name] = {
            "accuracy": summarize_transcripts(scores),
            "latency": latency_summary(timings),
            "utterances": utterances,
        }

    if include_recorded:
        clips = corpus.recorded_wake_word_clips()
        if clips:
            groups["recorded_real_voices"] = _score_recorded_clips(stt, clips)

    pooled = [
        score_transcript(u["reference"], u["hypothesis"])
        for name, group in groups.items()
        if name != "recorded_real_voices"
        for u in group["utterances"]
    ]
    return {
        "config": {
            "model_size": resolved_size,
            "device": DEFAULT_DEVICE,
            "compute_type": DEFAULT_COMPUTE_TYPE,
            "beam_size": DEFAULT_BEAM_SIZE,
            "vad_filter": DEFAULT_VAD_FILTER,
        },
        "groups": groups,
        "all_synthetic": summarize_transcripts(pooled),
    }


def _score_recorded_clips(stt, clips: Sequence[Path]) -> dict:
    """Transcribe committed real-voice recordings against their known phrase.

    These are two words each, so they carry almost no statistical weight. They
    are included because they are the only genuine human speech in the
    repository, and a real-voice data point with a stated caveat is worth more
    than none at all.
    """
    scores, timings, utterances = [], [], []
    for path in clips:
        audio = read_wav(path)
        started = time.perf_counter()
        transcript = stt.transcribe(audio)
        elapsed_ms = (time.perf_counter() - started) * 1000
        score = score_transcript(corpus.WAKE_PHRASE, transcript.text)
        scores.append(score)
        timings.append(elapsed_ms)
        utterances.append(
            {
                "reference": score.reference,
                "hypothesis": score.hypothesis,
                "source": path.name,
                "wer": score.wer,
                "wer_numbers_normalized": score.wer_numbers_normalized,
                "exact_match": score.exact_match,
                "audio_ms": duration_ms(audio),
                "transcribe_ms": round(elapsed_ms, 1),
            }
        )
    return {
        "accuracy": summarize_transcripts(scores),
        "latency": latency_summary(timings),
        "utterances": utterances,
        "caveat": (
            "Two-word utterances from four speakers; indicative only, not a "
            "meaningful word error rate."
        ),
    }


# --------------------------------------------------------------------------
# wake word
# --------------------------------------------------------------------------


def _replay_for_wake_word(detector, audio, threshold: float) -> dict:
    """Stream one clip through the detector at one threshold.

    The detector is reset first and the replay stops at the first activation,
    so each threshold sees the same audio from the same starting state. This
    is what makes the sweep three independent evaluations rather than one run
    re-scored three times, which is how the June table was built.
    """
    detector.reset()
    samples = audio.samples
    inference_ms: list[float] = []
    for start in range(0, len(samples) - WAKE_WORD_CHUNK + 1, WAKE_WORD_CHUNK):
        chunk = np.ascontiguousarray(samples[start : start + WAKE_WORD_CHUNK])
        started = time.perf_counter()
        prediction = detector.process_audio(chunk, confidence_threshold=threshold)
        inference_ms.append((time.perf_counter() - started) * 1000)
        if prediction is not None:
            return {
                "activated": True,
                "confidence": round(float(prediction.confidence), 4),
                "chunk_index": start // WAKE_WORD_CHUNK,
                "inference_ms": inference_ms,
            }
    return {
        "activated": False,
        "confidence": None,
        "chunk_index": None,
        "inference_ms": inference_ms,
    }


def _score_population(
    detector, population, threshold: float, inference_sink: list[float]
) -> dict:
    """Replay one population at one threshold and summarize activations."""
    trials = []
    for label, audio in population:
        outcome = _replay_for_wake_word(detector, audio, threshold)
        inference_sink.extend(outcome["inference_ms"])
        trials.append(
            {
                "label": label,
                "activated": outcome["activated"],
                "confidence": outcome["confidence"],
                "audio_ms": duration_ms(audio),
            }
        )
    activations = sum(1 for trial in trials if trial["activated"])
    confidences = [t["confidence"] for t in trials if t["confidence"] is not None]
    return {
        "trials": len(trials),
        "activations": activations,
        "rate": round(activations / len(trials), 4) if trials else 0.0,
        "mean_confidence": (
            round(sum(confidences) / len(confidences), 4) if confidences else None
        ),
        "detail": trials,
    }


def benchmark_wake_word(
    backend,
    *,
    thresholds: Sequence[float] = DEFAULT_THRESHOLDS,
    conditions: Sequence[tuple[str, float | None]] = DEFAULT_NOISE_CONDITIONS,
    include_recorded: bool = True,
) -> dict:
    """Sweep detection and false activation across thresholds and noise levels.

    Three populations are measured separately because they answer different
    questions: positives give a detection rate, confusable phrases give an
    adversarial activation rate, and neutral speech gives the closest thing to
    a background false-accept rate this suite can produce offline.

    The noise conditions exist because replayed audio reaches the detector
    without passing through a speaker, a room or a microphone, so every clip
    is cleaner than anything a user produces. On clean audio the detector
    scores near 0.9 on everything and the threshold sweep goes flat, showing no
    trade-off at all. Calibrated noise restores a gradient and makes the sweep
    discriminate again.
    """
    from voice_concierge.voice_input.wake_word_detector import WakeWordDetector

    eprint("  wake word ...")
    detector = WakeWordDetector()

    positives = _synthesize_corpus(
        backend, [corpus.WAKE_PHRASE], target_rate=WAKE_WORD_RATE
    )
    if include_recorded:
        positives += [
            (path.name, resample_to(read_wav(path), WAKE_WORD_RATE))
            for path in corpus.recorded_wake_word_clips()
        ]
    confusables = _synthesize_corpus(
        backend, corpus.CONFUSABLE_PHRASES, target_rate=WAKE_WORD_RATE
    )
    neutrals = _synthesize_corpus(
        backend, corpus.NEUTRAL_PHRASES, target_rate=WAKE_WORD_RATE
    )

    all_inference_ms: list[float] = []
    by_condition = []
    for condition_name, snr_db in conditions:
        eprint(f"    condition: {condition_name}")
        populations = {
            name: [
                (label, audio if snr_db is None else add_noise(audio, snr_db))
                for label, audio in population
            ]
            for name, population in (
                ("positive", positives),
                ("confusable", confusables),
                ("neutral", neutrals),
            )
        }
        by_threshold = []
        for threshold in thresholds:
            groups = {}
            for name, population in populations.items():
                groups[name] = _score_population(
                    detector, population, threshold, all_inference_ms
                )
            by_threshold.append({"threshold": threshold, "groups": groups})
        by_condition.append(
            {
                "condition": condition_name,
                "snr_db": snr_db,
                "by_threshold": by_threshold,
            }
        )

    return {
        "method": (
            "Each threshold is an independent replay of the same audio with the "
            "detector reset beforehand, not a re-scoring of a single run."
        ),
        "acoustic_caveat": (
            "Audio is injected digitally, bypassing speaker, room and "
            "microphone. Clean-condition results are therefore optimistic and "
            "do not reproduce live over-the-air behaviour: live trials in June "
            "saw confidences from 0.32 to 0.99 and a confusable phrase firing "
            "5/5, where clean replay scores near 0.9 on everything and rejects "
            "the same phrase. Use the noisy conditions for threshold choice, "
            "and live trials for anything reported as a detection rate."
        ),
        "populations": {
            "positive": len(positives),
            "confusable": len(confusables),
            "neutral": len(neutrals),
        },
        "by_condition": by_condition,
        "inference_latency": {
            **latency_summary(all_inference_ms),
            "note": (
                "Model inference per 80 ms frame. Excludes audio capture, the "
                "frame period, and the rolling context the model accumulates "
                "before it can decide. Not user-perceived activation latency."
            ),
        },
    }


# --------------------------------------------------------------------------
# voice activity detection
# --------------------------------------------------------------------------


def _chunk_bytes(audio, chunk_samples: int) -> list[bytes]:
    """Split audio into fixed-size byte chunks for a fake audio source."""
    samples = audio.samples.astype(np.int16)
    chunks = []
    for start in range(0, len(samples), chunk_samples):
        window = samples[start : start + chunk_samples]
        if len(window) < chunk_samples:
            window = np.pad(window, (0, chunk_samples - len(window)))
        chunks.append(window.tobytes())
    return chunks


def benchmark_vad(
    backend,
    *,
    silence_ms: int = 1500,
    pause_gaps_ms: Sequence[int] = DEFAULT_PAUSE_GAPS_MS,
) -> dict:
    """Measure utterance boundary capture against known input lengths.

    Wall-clock duration is meaningless when audio is replayed from memory, so
    capture is scored on retained samples instead: how much of a known input
    survived the boundary decision. That is the property the June benchmark
    was really probing when it recorded early cut-offs.
    """
    from voice_concierge.audio.source import FakeAudioSource
    from voice_concierge.voice_input.voice_activity_detector import (
        DEFAULT_CHUNK,
        DEFAULT_MIN_SILENCE_MS,
        DEFAULT_RATE,
        VoiceActivityDetector,
    )

    eprint("  voice activity detection ...")
    silence_chunk = np.zeros(DEFAULT_CHUNK, dtype=np.int16).tobytes()

    def capture(audio):
        """Run one utterance through a detector fed from memory."""
        chunks = _chunk_bytes(resample_to(audio, DEFAULT_RATE), DEFAULT_CHUNK)
        trailing = max(1, int(silence_ms / 1000 * DEFAULT_RATE / DEFAULT_CHUNK))
        source = FakeAudioSource(
            chunks=[*chunks, *([silence_chunk] * trailing)], fill=silence_chunk
        )
        detector = VoiceActivityDetector(audio_source=source)
        captured: list = []
        # The detector narrates to stdout for the live runner's benefit. Here
        # nobody is speaking and the commentary is misleading, so it is
        # swallowed rather than changing how the component behaves.
        with contextlib.redirect_stdout(io.StringIO()):
            detector.capture_utterance(captured.append)
        return captured[0] if captured else None

    trials = []
    for label, text in corpus.VAD_UTTERANCES:
        audio = backend.synthesize(text)
        trials.append(_vad_trial(label, text, audio, capture(audio)))

    captured_count = sum(1 for trial in trials if trial["captured"])
    return {
        "config": {
            "min_silence_ms": DEFAULT_MIN_SILENCE_MS,
            "chunk_samples": DEFAULT_CHUNK,
            "rate": DEFAULT_RATE,
            "trailing_silence_ms": silence_ms,
        },
        "continuous_speech": {
            "trials": len(trials),
            "captured": captured_count,
            "capture_rate": (round(captured_count / len(trials), 4) if trials else 0.0),
            "detail": trials,
        },
        "pause_tolerance": _benchmark_pause_tolerance(
            backend, capture, pause_gaps_ms, DEFAULT_RATE, DEFAULT_MIN_SILENCE_MS
        ),
        "note": (
            "Capture is scored on retained audio against a known input length, "
            "since replayed audio has no meaningful wall-clock duration. "
            "Retention above 1.0 is normal: the detector pads utterance "
            "boundaries, so it keeps slightly more than it was given."
        ),
    }


def _benchmark_pause_tolerance(
    backend,
    capture,
    gaps_ms: Sequence[int],
    rate: int,
    min_silence_ms: int,
) -> dict:
    """Find the pause length at which an utterance is cut in half.

    The gap is constructed from real silence rather than trusting the
    synthesizer to render an ellipsis as one, so the measurement tests the
    detector's silence threshold rather than the voice's punctuation handling.
    This is the accessibility question in the June benchmark made precise:
    older adults pause mid-sentence, and the threshold decides whether that
    costs them the rest of their sentence.
    """
    first = resample_to(backend.synthesize(corpus.VAD_PAUSE_FIRST_HALF), rate)
    second = resample_to(backend.synthesize(corpus.VAD_PAUSE_SECOND_HALF), rate)

    trials = []
    for gap_ms in gaps_ms:
        joined = _join_with_silence(first, second, gap_ms, rate)
        captured = capture(joined)
        captured_ms = duration_ms(captured) if captured is not None else 0.0
        # Reaching the midpoint of the second half means the pause was ridden
        # out; stopping short of it means the tail of the sentence was lost.
        completion_ms = duration_ms(first) + gap_ms + duration_ms(second) / 2
        trials.append(
            {
                "gap_ms": gap_ms,
                "captured": captured is not None,
                "input_ms": duration_ms(joined),
                "captured_ms": captured_ms,
                "cut_off_early": captured is not None and captured_ms < completion_ms,
            }
        )

    cut_offs = [trial for trial in trials if trial["cut_off_early"]]
    survived = [
        trial["gap_ms"]
        for trial in trials
        if trial["captured"] and not trial["cut_off_early"]
    ]
    return {
        "configured_min_silence_ms": min_silence_ms,
        "first_half": corpus.VAD_PAUSE_FIRST_HALF,
        "second_half": corpus.VAD_PAUSE_SECOND_HALF,
        "trials": trials,
        "cut_off_count": len(cut_offs),
        "longest_pause_survived_ms": max(survived) if survived else None,
        "shortest_pause_cut_off_ms": (
            min(trial["gap_ms"] for trial in cut_offs) if cut_offs else None
        ),
    }


def _join_with_silence(first, second, gap_ms: int, rate: int):
    """Concatenate two clips separated by an exact silence gap."""
    from voice_concierge.audio.types import CapturedAudio

    gap = np.zeros(int(rate * gap_ms / 1000), dtype=np.int16)
    samples = np.concatenate(
        [first.samples.astype(np.int16), gap, second.samples.astype(np.int16)]
    )
    return CapturedAudio(samples=samples, sample_rate=rate, channels=1)


def _vad_trial(label: str, text: str, source_audio, captured) -> dict:
    """Compare what the detector kept against what it was given."""
    input_ms = duration_ms(source_audio)
    captured_ms = duration_ms(captured) if captured is not None else 0.0
    return {
        "label": label,
        "text": text,
        "captured": captured is not None,
        "input_ms": input_ms,
        "captured_ms": captured_ms,
        "retention_ratio": (
            round(captured_ms / input_ms, 3) if input_ms and captured else 0.0
        ),
    }


# --------------------------------------------------------------------------
# reasoning
# --------------------------------------------------------------------------


def benchmark_reasoning(*, model: str | None = None, cases: int | None = None) -> dict:
    """Measure reasoning latency against the local model.

    Deliberately thin: the project already has a graded reasoning suite under
    `benchmarks/reasoning`, and duplicating its scoring here would produce a
    second set of pass rates that disagree with the published ones. This
    records response latency and leaves correctness to that suite.
    """
    from voice_concierge.app.reasoning import build_reasoning_turn_service

    eprint("  reasoning ...")
    config, resolved_model = reasoning_config(model)
    service = build_reasoning_turn_service(config)

    prompts = list(corpus.PIPELINE_REQUESTS + corpus.CONVERSATIONAL_REQUESTS)
    if cases is not None:
        prompts = prompts[:cases]

    timer = Timer()
    turns = []
    for prompt in prompts:
        result, elapsed_ms = timer.time(lambda: service.process_transcript(prompt))
        turns.append(
            {
                "prompt": prompt,
                "latency_ms": round(elapsed_ms, 1),
                "response_characters": len(
                    getattr(result, "spoken_response", "") or ""
                ),
            }
        )

    return {
        "model": resolved_model,
        "turns": turns,
        "latency": timer.summary(),
        "note": (
            "Latency only. Graded correctness lives in benchmarks/reasoning so "
            "there is a single source of pass-rate figures."
        ),
    }
