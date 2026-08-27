"""Explicit text-to-speech backend selection for benchmarking.

The application deliberately composes Piper with the macOS voice behind
`FallbackTextToSpeech`, so a user never loses speech when one backend fails.
That is right for the product and wrong for a benchmark: a Piper failure
silently produces macOS audio, and the resulting numbers get published as
Piper's. A previous whole-pipeline run was labelled Piper for exactly this
reason and had in fact measured `say`.

This module therefore resolves one *named* backend with no fallback chain
around it, probes it before any measurement starts, and refuses to continue
when the requested backend cannot synthesize. The application's fallback
behaviour is untouched; nothing here changes what the product does.
"""

from __future__ import annotations

# Standard library
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

# Local
from benchmarks.suite.harness import duration_ms

#: The phrase every backend probe synthesizes. Short, and with enough voiced
#: content that a silent result means a real failure rather than a clipped word.
PROBE_TEXT: str = "Backend check, one two three."

BACKEND_CHOICES: tuple[str, ...] = ("piper", "say", "auto")


class BackendUnavailableError(RuntimeError):
    """A requested text-to-speech backend cannot be used on this machine."""


@dataclass(frozen=True)
class BackendProbe:
    """What happened when a backend was asked to synthesize once."""

    name: str
    available: bool
    detail: str
    sample_rate: int | None = None
    remediation: str | None = None

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "available": self.available,
            "detail": self.detail,
            "sample_rate": self.sample_rate,
            "remediation": self.remediation,
        }


def _piper_executable() -> str | None:
    """Locate the Piper CLI, including inside the active virtual environment."""
    found = shutil.which("piper")
    if found is not None:
        return found
    local = Path(sys.executable).with_name("piper")
    return str(local) if local.is_file() else None


def build_backend(name: str, *, length_scale: float | None = None):
    """Construct one named backend with no fallback wrapper around it."""
    if name == "piper":
        from voice_concierge.voice_output.piper import (
            DEFAULT_CONFIG_PATH,
            DEFAULT_LENGTH_SCALE,
            DEFAULT_MODEL_PATH,
            PiperTextToSpeech,
        )

        return PiperTextToSpeech(
            DEFAULT_MODEL_PATH,
            DEFAULT_CONFIG_PATH,
            length_scale=length_scale or DEFAULT_LENGTH_SCALE,
        )

    if name == "say":
        from voice_concierge.voice_output.say import SayTextToSpeech

        return SayTextToSpeech()

    raise ValueError(f"Unknown text-to-speech backend {name!r}.")


def probe_backend(name: str) -> BackendProbe:
    """Try to synthesize once with `name`, reporting why if it fails.

    Silent output counts as a failure. A backend that returns an all-zero
    buffer has not synthesized anything, and treating that as success is how a
    benchmark ends up reporting timings for audio nobody could hear.
    """
    if name == "piper" and _piper_executable() is None:
        return BackendProbe(
            name=name,
            available=False,
            detail="The Piper executable was not found on PATH or in this venv.",
            remediation=(
                "Install the project requirements into the active environment: "
                "pip install -r requirements-dev.txt"
            ),
        )
    if name == "say" and sys.platform != "darwin":
        return BackendProbe(
            name=name,
            available=False,
            detail=f"The macOS say backend needs Darwin; this is {sys.platform}.",
            remediation="Run with --tts piper on this platform.",
        )

    try:
        backend = build_backend(name)
        audio = backend.synthesize(PROBE_TEXT)
    except Exception as exc:
        return BackendProbe(
            name=name,
            available=False,
            detail=f"{type(exc).__name__}: {exc}",
            remediation=_remediation_for(name, str(exc)),
        )

    if audio.samples.size == 0 or not audio.samples.any():
        return BackendProbe(
            name=name,
            available=False,
            detail="The backend returned silent audio.",
            remediation=_remediation_for(name, ""),
        )

    return BackendProbe(
        name=name,
        available=True,
        detail=f"Synthesized {duration_ms(audio)} ms at {audio.sample_rate} Hz.",
        sample_rate=audio.sample_rate,
    )


def _remediation_for(name: str, message: str) -> str | None:
    """Suggest a fix for the failure modes seen on this project's machines."""
    if name != "piper":
        return None
    if "espeak" in message.lower() or "phontab" in message.lower():
        return (
            "The installed piper-tts wheel resolves its espeak-ng data through a "
            "path baked in at build time, which does not exist on this machine. "
            "Reinstalling piper-tts usually fixes it; if it does not, run the "
            "suite with --tts say and record that the macOS voice was used."
        )
    return "Check that the Piper voice model and config are present."


def resolve_backend(requested: str) -> tuple[str, object, list[BackendProbe]]:
    """Pick the backend to measure with, or fail loudly saying why.

    An explicit choice is never silently substituted: asking for Piper and
    getting the macOS voice is precisely the failure this suite exists to stop.
    `auto` is the only mode permitted to choose, and it still reports which
    backend it landed on so the output can never be misread.
    """
    if requested not in BACKEND_CHOICES:
        raise ValueError(f"Unknown backend {requested!r}.")

    if requested == "auto":
        probes = [probe_backend("piper"), probe_backend("say")]
        for probe in probes:
            if probe.available:
                return probe.name, build_backend(probe.name), probes
        raise BackendUnavailableError(
            "No text-to-speech backend is usable on this machine.\n"
            + _format_probes(probes)
        )

    probe = probe_backend(requested)
    if not probe.available:
        raise BackendUnavailableError(
            f"The {requested!r} text-to-speech backend was requested but cannot "
            f"synthesize on this machine.\n" + _format_probes([probe]) + "\n"
            "Refusing to fall back to another backend: a benchmark labelled "
            f"{requested!r} must contain {requested!r} audio. Re-run with "
            "--tts auto to measure whatever is available, and the report will "
            "name the backend that actually ran."
        )
    return requested, build_backend(requested), [probe]


def _format_probes(probes: list[BackendProbe]) -> str:
    """Render probe results as an operator-readable block."""
    lines = []
    for probe in probes:
        mark = "ok  " if probe.available else "FAIL"
        lines.append(f"  [{mark}] {probe.name}: {probe.detail}")
        if probe.remediation:
            lines.append(f"         fix: {probe.remediation}")
    return "\n".join(lines)
