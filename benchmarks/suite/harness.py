"""Shared measurement infrastructure for the component and pipeline suite.

Everything here is deliberately free of component knowledge: sampling a
process, describing the machine, scoring a transcript and reading audio are the
same operations whichever stage is under test, and keeping them in one place is
what lets two components' numbers be compared without arguing about method.
"""

from __future__ import annotations

# Standard library
import platform
import re
import statistics
import subprocess
import sys
import threading
import time
import wave
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Sequence

# Third-party
import numpy as np
import psutil

REPO_ROOT = Path(__file__).resolve().parents[2]

#: How often the background sampler reads memory and CPU, in seconds.
SAMPLE_INTERVAL: float = 0.1


# --------------------------------------------------------------------------
# provenance
# --------------------------------------------------------------------------


def _git(*args: str) -> str | None:
    """Run a git command in the repo, returning None if git is unavailable."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def describe_provenance() -> dict:
    """Record what produced these numbers, so a table can be traced back.

    The previous whole-pipeline table could not be reproduced because the run
    behind it was never identified. A commit and a dirty flag cost nothing here
    and remove that whole class of problem.
    """
    status = _git("status", "--porcelain")
    return {
        "captured_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": _git("rev-parse", "HEAD"),
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "git_dirty": bool(status) if status is not None else None,
        "suite_version": "1.0",
    }


def _sysctl(key: str) -> str | None:
    """Read a macOS sysctl value, returning None anywhere else."""
    try:
        result = subprocess.run(
            ["sysctl", "-n", key], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def describe_device() -> dict:
    """Everything needed to say which machine produced these numbers."""
    memory = psutil.virtual_memory()
    return {
        "os": f"{platform.system()} {platform.release()}",
        "platform": platform.platform(),
        "machine": platform.machine(),
        "chip": _sysctl("machdep.cpu.brand_string"),
        "physical_cores": psutil.cpu_count(logical=False),
        "logical_cores": psutil.cpu_count(logical=True),
        "ram_gb": round(memory.total / (1024**3), 1),
        "python": platform.python_version(),
    }


def package_versions(names: Sequence[str]) -> dict:
    """Report the installed version of each named distribution."""
    from importlib.metadata import PackageNotFoundError, version

    versions: dict[str, str | None] = {}
    for name in names:
        try:
            versions[name] = version(name)
        except PackageNotFoundError:
            versions[name] = None
    return versions


# --------------------------------------------------------------------------
# resource sampling
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ProcessSample:
    """One observation of a process group."""

    rss_mb: float
    cpu_percent: float


class ResourceSampler:
    """Sample this process, a model process group, and system memory.

    Sampling on a thread rather than reading before and after is what makes a
    reported peak a real peak: a turn that briefly doubles its memory halfway
    through is invisible to a start/end pair.
    """

    def __init__(self, model_processes: Sequence[psutil.Process] = ()) -> None:
        self._app = psutil.Process()
        self._model_processes = list(model_processes)
        self._app_samples: list[ProcessSample] = []
        self._model_samples: list[ProcessSample] = []
        self._system_used_mb: list[float] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # Prime cpu_percent: the first call on a process always returns 0.0
        # because there is no previous reading to difference against.
        self._app.cpu_percent()
        for process in self._model_processes:
            try:
                process.cpu_percent()
            except psutil.Error:  # pragma: no cover - process may exit
                continue

    def __enter__(self) -> "ResourceSampler":
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._app_samples.append(_sample_one(self._app))
            self._model_samples.append(_sample_group(self._model_processes))
            self._system_used_mb.append(psutil.virtual_memory().used / (1024 * 1024))
            self._stop.wait(SAMPLE_INTERVAL)

    @property
    def app(self) -> list[ProcessSample]:
        return list(self._app_samples)

    @property
    def model(self) -> list[ProcessSample]:
        return list(self._model_samples)

    @property
    def system_used_mb(self) -> list[float]:
        return list(self._system_used_mb)

    def usage(self) -> dict:
        """Summarize what was observed while the sampler was running."""
        app, model = self.app, self.model
        totals = [a.rss_mb + m.rss_mb for a, m in zip(app, model)]
        cpu_totals = [a.cpu_percent + m.cpu_percent for a, m in zip(app, model)]
        return {
            "samples": len(app),
            "peak_rss_app_mb": round(max((s.rss_mb for s in app), default=0.0), 1),
            "peak_rss_model_mb": round(max((s.rss_mb for s in model), default=0.0), 1),
            "peak_rss_total_mb": round(max(totals, default=0.0), 1),
            "mean_cpu_app": _rounded_mean([s.cpu_percent for s in app]),
            "peak_cpu_total": round(max(cpu_totals, default=0.0), 1),
            "peak_system_used_mb": round(max(self._system_used_mb, default=0.0), 1),
        }


def _sample_one(process: psutil.Process) -> ProcessSample:
    """Read one process, tolerating a process that has gone away."""
    try:
        return ProcessSample(
            rss_mb=process.memory_info().rss / (1024 * 1024),
            cpu_percent=process.cpu_percent(),
        )
    except psutil.Error:  # pragma: no cover - process may exit mid-run
        return ProcessSample(rss_mb=0.0, cpu_percent=0.0)


def _sample_group(processes: Sequence[psutil.Process]) -> ProcessSample:
    """Sum a group of processes into one observation."""
    rss = cpu = 0.0
    for process in processes:
        sample = _sample_one(process)
        rss += sample.rss_mb
        cpu += sample.cpu_percent
    return ProcessSample(rss_mb=rss, cpu_percent=cpu)


def _rounded_mean(values: Sequence[float], digits: int = 1) -> float:
    """Mean of `values`, or 0.0 when empty."""
    return round(statistics.fmean(values), digits) if values else 0.0


def find_ollama_processes() -> list[psutil.Process]:
    """Return every running Ollama process.

    Looked up per measurement rather than once at start-up: Ollama spawns the
    runner that actually holds the model weights lazily, so a list captured
    before first use contains only the server and understates memory badly.
    """
    found = []
    for process in psutil.process_iter(["name", "cmdline"]):
        try:
            name = (process.info.get("name") or "").lower()
            cmdline = " ".join(process.info.get("cmdline") or []).lower()
        except psutil.Error:  # pragma: no cover - process may exit
            continue
        if "ollama" in name or "ollama" in cmdline:
            found.append(process)
    return found


def loaded_model_memory_mb() -> tuple[float, dict[str, float]]:
    """Ask Ollama how much memory its loaded models occupy.

    Resident set size does not see these pages on Apple silicon: the weights
    live in unified memory through Metal, so the runner reports tens of
    megabytes while gigabytes are resident. `ollama ps` is the only instrument
    available here that accounts for them.
    """
    try:
        result = subprocess.run(
            ["ollama", "ps"], capture_output=True, text=True, check=True, timeout=15
        )
    except (OSError, subprocess.SubprocessError):
        return 0.0, {}

    total = 0.0
    detail: dict[str, float] = {}
    for line in result.stdout.splitlines()[1:]:
        match = re.match(r"^(\S+)\s+\S+\s+([\d.]+)\s*(GB|MB)\b", line, re.IGNORECASE)
        if match is None:
            continue
        name, size, unit = match.group(1), float(match.group(2)), match.group(3)
        megabytes = size * 1024 if unit.upper() == "GB" else size
        detail[name] = round(megabytes, 1)
        total += megabytes
    return round(total, 1), detail


# --------------------------------------------------------------------------
# reasoning configuration
# --------------------------------------------------------------------------

#: Where the application records which reasoning model is selected.
MODEL_SELECTION_PATH = REPO_ROOT / ".local/reasoning-model-selection.json"


def selected_reasoning_model(path: Path = MODEL_SELECTION_PATH) -> str | None:
    """Read which reasoning model the application is configured to use."""
    import json

    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text()).get("model")
    except (OSError, ValueError):  # pragma: no cover - malformed selection file
        return None


def reasoning_config(model: str | None = None):
    """Build a reasoning config, optionally overriding the selected model.

    The model is not a field on the config; the application resolves it from a
    selection file. Overriding it therefore means pointing the config at a
    different file, which is written to a temporary location so a benchmark
    never mutates the developer's own selection.
    """
    import json
    import tempfile

    from voice_concierge.app.reasoning import AppReasoningConfig

    if model is None:
        return AppReasoningConfig(), selected_reasoning_model()

    base = {}
    if MODEL_SELECTION_PATH.is_file():
        try:
            base = json.loads(MODEL_SELECTION_PATH.read_text())
        except (OSError, ValueError):  # pragma: no cover - malformed file
            base = {}
    base.update({"model": model, "schema_version": base.get("schema_version", 1)})
    base.setdefault("backend", "ollama")
    base.setdefault("host", "http://localhost:11434")

    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, prefix="reasoning-selection-"
    )
    with handle:
        json.dump(base, handle)
    return AppReasoningConfig(selection_path=handle.name), model


# --------------------------------------------------------------------------
# timing
# --------------------------------------------------------------------------


@dataclass
class Timer:
    """Collect repeated timings of one operation."""

    samples_ms: list[float] = field(default_factory=list)

    def time(self, operation: Callable[[], object]) -> tuple[object, float]:
        """Run `operation`, record how long it took, and return both."""
        started = time.perf_counter()
        value = operation()
        elapsed_ms = (time.perf_counter() - started) * 1000
        self.samples_ms.append(elapsed_ms)
        return value, elapsed_ms

    def summary(self) -> dict:
        """Aggregate the recorded timings."""
        return latency_summary(self.samples_ms)


def latency_summary(samples_ms: Sequence[float]) -> dict:
    """Summarize a set of latencies, reporting spread as well as centre.

    Standard deviation and the full range are included because a mean alone
    misrepresents a pipeline whose slowest turn is twice its fastest.
    """
    if not samples_ms:
        return {"count": 0}
    ordered = sorted(samples_ms)
    return {
        "count": len(ordered),
        "min_ms": round(ordered[0], 1),
        "mean_ms": round(statistics.fmean(ordered), 1),
        "median_ms": round(statistics.median(ordered), 1),
        "max_ms": round(ordered[-1], 1),
        "stdev_ms": (round(statistics.stdev(ordered), 1) if len(ordered) > 1 else 0.0),
    }


# --------------------------------------------------------------------------
# transcript scoring
# --------------------------------------------------------------------------

_PUNCTUATION = re.compile(r"[^\w\s']")

#: Whisper writes numbers as digits where a reference text spells them out.
#: Scoring that as an error measures orthography rather than recognition, so
#: the comparison is made both ways and both figures are reported.
_NUMBER_WORDS: dict[str, str] = {
    "0": "zero",
    "1": "one",
    "2": "two",
    "3": "three",
    "4": "four",
    "5": "five",
    "6": "six",
    "7": "seven",
    "8": "eight",
    "9": "nine",
    "10": "ten",
    "11": "eleven",
    "12": "twelve",
    "13": "thirteen",
    "14": "fourteen",
    "15": "fifteen",
    "16": "sixteen",
    "17": "seventeen",
    "18": "eighteen",
    "19": "nineteen",
    "20": "twenty",
    "30": "thirty",
    "40": "forty",
    "50": "fifty",
    "60": "sixty",
    "100": "hundred",
}


def normalize_words(text: str, *, normalize_numbers: bool = False) -> list[str]:
    """Lowercase, drop punctuation and split into comparable word tokens."""
    words = _PUNCTUATION.sub(" ", text.lower()).split()
    if normalize_numbers:
        words = [_NUMBER_WORDS.get(word, word) for word in words]
    return words


def align_words(
    reference: Sequence[str], hypothesis: Sequence[str]
) -> tuple[int, int, int]:
    """Return (substitutions, deletions, insertions) by Levenshtein alignment.

    Equal cost per edit, which is the definition word error rate is built on.
    """
    n, m = len(reference), len(hypothesis)
    distance = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        distance[i][0] = i
    for j in range(m + 1):
        distance[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if reference[i - 1] == hypothesis[j - 1]:
                distance[i][j] = distance[i - 1][j - 1]
            else:
                distance[i][j] = 1 + min(
                    distance[i - 1][j - 1],
                    distance[i - 1][j],
                    distance[i][j - 1],
                )

    substitutions = deletions = insertions = 0
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and reference[i - 1] == hypothesis[j - 1]:
            i, j = i - 1, j - 1
        elif i > 0 and j > 0 and distance[i][j] == distance[i - 1][j - 1] + 1:
            substitutions += 1
            i, j = i - 1, j - 1
        elif i > 0 and distance[i][j] == distance[i - 1][j] + 1:
            deletions += 1
            i -= 1
        else:
            insertions += 1
            j -= 1
    return substitutions, deletions, insertions


@dataclass(frozen=True)
class TranscriptScore:
    """How far one transcript fell from its reference."""

    reference: str
    hypothesis: str
    reference_words: int
    substitutions: int
    deletions: int
    insertions: int
    errors: int
    wer: float
    wer_numbers_normalized: float
    exact_match: bool


def score_transcript(reference: str, hypothesis: str) -> TranscriptScore:
    """Score one transcript, both raw and with numeric tokens normalized."""
    reference_words = normalize_words(reference)
    hypothesis_words = normalize_words(hypothesis)
    substitutions, deletions, insertions = align_words(
        reference_words, hypothesis_words
    )
    errors = substitutions + deletions + insertions
    total = len(reference_words)

    normalized_errors = sum(
        align_words(
            normalize_words(reference, normalize_numbers=True),
            normalize_words(hypothesis, normalize_numbers=True),
        )
    )
    return TranscriptScore(
        reference=reference,
        hypothesis=hypothesis,
        reference_words=total,
        substitutions=substitutions,
        deletions=deletions,
        insertions=insertions,
        errors=errors,
        wer=round(errors / total, 4) if total else 0.0,
        wer_numbers_normalized=(round(normalized_errors / total, 4) if total else 0.0),
        exact_match=reference_words == hypothesis_words,
    )


def summarize_transcripts(scores: Iterable[TranscriptScore]) -> dict:
    """Pool transcript scores into a corpus word error rate.

    Corpus WER pools errors over all reference words, which is the standard
    definition. The mean of per-utterance rates is reported beside it because
    the two diverge when utterance lengths differ, and quoting one alone
    invites the wrong comparison.
    """
    collected = list(scores)
    if not collected:
        return {"utterances": 0}
    total_words = sum(score.reference_words for score in collected)
    total_errors = sum(score.errors for score in collected)
    normalized_errors = sum(
        round(score.wer_numbers_normalized * score.reference_words)
        for score in collected
    )
    return {
        "utterances": len(collected),
        "reference_words": total_words,
        "substitutions": sum(score.substitutions for score in collected),
        "deletions": sum(score.deletions for score in collected),
        "insertions": sum(score.insertions for score in collected),
        "total_errors": total_errors,
        "corpus_wer": round(total_errors / total_words, 4) if total_words else 0.0,
        "corpus_wer_numbers_normalized": (
            round(normalized_errors / total_words, 4) if total_words else 0.0
        ),
        "mean_utterance_wer": _rounded_mean([s.wer for s in collected], 4),
        "exact_match_rate": round(
            sum(1 for s in collected if s.exact_match) / len(collected), 4
        ),
    }


# --------------------------------------------------------------------------
# audio
# --------------------------------------------------------------------------


def read_wav(path: Path):
    """Load a WAV file as mono CapturedAudio."""
    from voice_concierge.audio.types import CapturedAudio

    with wave.open(str(path), "rb") as wav:
        frames = wav.readframes(wav.getnframes())
        rate = wav.getframerate()
        channels = wav.getnchannels()
    samples = np.frombuffer(frames, dtype=np.int16)
    if channels > 1:
        samples = samples[::channels]
    return CapturedAudio(samples=samples, sample_rate=rate, channels=1)


def write_wav(path: Path, audio) -> None:
    """Write CapturedAudio to a 16-bit mono WAV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(audio.sample_rate)
        wav.writeframes(audio.samples.astype(np.int16).tobytes())


def resample_to(audio, sample_rate: int):
    """Linearly resample audio to `sample_rate`.

    Wake word and VAD both require 16 kHz, while the synthesis backends emit
    their own native rates. Linear interpolation is crude for general audio but
    adequate for feeding a detector, and it avoids a scipy dependency.
    """
    from voice_concierge.audio.types import CapturedAudio

    if audio.sample_rate == sample_rate:
        return audio
    source = audio.samples.astype(np.float64)
    target_length = int(round(len(source) * sample_rate / audio.sample_rate))
    if target_length <= 0:  # pragma: no cover - guarded by callers
        return CapturedAudio(
            samples=np.zeros(0, dtype=np.int16), sample_rate=sample_rate, channels=1
        )
    positions = np.linspace(0, len(source) - 1, target_length)
    resampled = np.interp(positions, np.arange(len(source)), source)
    return CapturedAudio(
        samples=resampled.astype(np.int16), sample_rate=sample_rate, channels=1
    )


def add_noise(audio, snr_db: float):
    """Mix white noise into `audio` at a target signal-to-noise ratio.

    Replaying audio straight into a detector bypasses the microphone, the room
    and the speaker, so every clip arrives cleaner than anything a real user
    produces. That flattens a threshold sweep into uselessness: everything
    scores highly and no trade-off is visible. Adding calibrated noise restores
    a gradient. It is not a substitute for the acoustic path — no reverberation,
    no microphone response, no distance attenuation — but it does make the
    sweep discriminate again.
    """
    from voice_concierge.audio.types import CapturedAudio

    signal = audio.samples.astype(np.float64)
    signal_power = float(np.mean(signal**2))
    if signal_power <= 0:  # pragma: no cover - silent input
        return audio
    noise_power = signal_power / (10 ** (snr_db / 10))
    rng = np.random.default_rng(seed=0)  # fixed: two runs must agree
    noisy = signal + rng.normal(0.0, np.sqrt(noise_power), size=signal.shape)
    clipped = np.clip(noisy, -32768, 32767).astype(np.int16)
    return CapturedAudio(
        samples=clipped, sample_rate=audio.sample_rate, channels=audio.channels
    )


def duration_ms(audio) -> float:
    """Length of `audio` in milliseconds."""
    return round(len(audio.samples) / audio.sample_rate * 1000, 1)


def eprint(message: str) -> None:
    """Write progress to stderr so stdout stays usable for piped output."""
    print(message, file=sys.stderr, flush=True)
