"""Read-only readiness checks for local app pipeline E2E testing."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Sequence

Status = Literal["pass", "warn", "fail"]

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_REASONING_MODEL = "granite4.1:8b"
DEFAULT_EMBEDDING_MODEL = "granite-embedding:278m"
DEFAULT_MODEL_SELECTION_PATH = REPO_ROOT / ".local/reasoning-model-selection.json"
DEFAULT_PIPER_EXECUTABLE = "piper"
DEFAULT_PIPER_MODEL_PATH = (
    REPO_ROOT / "src/voice_concierge/voice_output/en_GB-alan-medium.onnx"
)
DEFAULT_PIPER_CONFIG_PATH = (
    REPO_ROOT / "src/voice_concierge/voice_output/en_GB-alan-medium.onnx.json"
)
DEFAULT_WAKE_WORD_MODEL = "hey_jarvis_v0.1.onnx"

REQUIRED_IMPORTS: tuple[tuple[str, str], ...] = (
    ("httpx", "Ollama HTTP transport"),
    ("ollama", "local reasoning and embedding client"),
    ("pydantic", "structured reasoning output validation"),
    ("pysqlite3", "memory record storage"),
    ("sqlite_vec", "memory vector search"),
    ("numpy", "audio arrays"),
    ("psutil", "VAD metrics"),
    ("pyaudio", "microphone capture"),
    ("sounddevice", "speaker playback"),
    ("openwakeword", "wake-word detection"),
    ("silero_vad", "voice activity detection"),
    ("torch", "Silero VAD runtime"),
    ("faster_whisper", "speech-to-text"),
    ("piper", "Piper text-to-speech package"),
)


@dataclass(frozen=True)
class ReadinessCheck:
    """One local setup check result."""

    name: str
    status: Status
    detail: str
    remediation: str | None = None


def run_readiness_checks(
    *,
    host: str = DEFAULT_OLLAMA_HOST,
    reasoning_model: str | None = None,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    model_selection_path: Path = DEFAULT_MODEL_SELECTION_PATH,
    piper_executable: str = DEFAULT_PIPER_EXECUTABLE,
    piper_model_path: Path = DEFAULT_PIPER_MODEL_PATH,
    piper_config_path: Path = DEFAULT_PIPER_CONFIG_PATH,
    wake_word_model: str = DEFAULT_WAKE_WORD_MODEL,
    check_audio_devices: bool = True,
) -> tuple[ReadinessCheck, ...]:
    """Return readiness results without installing, downloading, or mutating state."""

    selected_reasoning_model = reasoning_model or _selected_reasoning_model(
        model_selection_path
    )
    checks: list[ReadinessCheck] = []
    checks.extend(_python_import_checks(REQUIRED_IMPORTS))
    checks.append(_ollama_service_check(host))
    checks.append(_ollama_model_check(host, selected_reasoning_model, "reasoning"))
    checks.append(_ollama_model_check(host, embedding_model, "embedding"))
    checks.append(_executable_check(piper_executable, "Piper executable"))
    checks.append(
        _file_check(
            piper_model_path,
            "Piper voice model",
            "Run: python -m voice_concierge.voice_output.download_models",
        )
    )
    checks.append(
        _file_check(
            piper_config_path,
            "Piper voice config",
            "Run: python -m voice_concierge.voice_output.download_models",
        )
    )
    checks.append(_wake_word_model_check(wake_word_model))
    if check_audio_devices:
        checks.append(_microphone_check())
        checks.append(_speaker_check())
    else:
        checks.append(
            ReadinessCheck(
                name="audio devices",
                status="warn",
                detail="Input/output device checks skipped.",
                remediation="Run without --skip-audio-devices before live E2E.",
            )
        )
    checks.append(
        ReadinessCheck(
            name="STT model cache",
            status="warn",
            detail=(
                "faster-whisper downloads or loads the base.en model on first use; "
                "this checker does not instantiate the model."
            ),
            remediation=(
                'Prefetch with: python -c "from faster_whisper import '
                "WhisperModel; WhisperModel('base.en', device='cpu', "
                "compute_type='int8')\""
            ),
        )
    )
    checks.append(
        ReadinessCheck(
            name="Silero VAD model cache",
            status="warn",
            detail=(
                "Silero VAD may download/cache its model on first load; this checker "
                "does not instantiate it."
            ),
            remediation=(
                'Prefetch with: python -c "from silero_vad import '
                'load_silero_vad; load_silero_vad()"'
            ),
        )
    )
    return tuple(checks)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the readiness checker from the command line."""

    parser = argparse.ArgumentParser(
        description="Check local setup for app pipeline E2E testing.",
    )
    parser.add_argument("--host", default=DEFAULT_OLLAMA_HOST, help="Ollama host URL.")
    parser.add_argument(
        "--reasoning-model",
        default=None,
        help="Expected local reasoning model. Defaults to local selection/default.",
    )
    parser.add_argument(
        "--embedding-model",
        default=DEFAULT_EMBEDDING_MODEL,
        help="Expected local embedding model.",
    )
    parser.add_argument(
        "--skip-audio-devices",
        action="store_true",
        help="Skip microphone and speaker device checks.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    args = parser.parse_args(argv)

    checks = run_readiness_checks(
        host=args.host,
        reasoning_model=args.reasoning_model,
        embedding_model=args.embedding_model,
        check_audio_devices=not args.skip_audio_devices,
    )
    if args.json:
        print(json.dumps([asdict(check) for check in checks], indent=2))
    else:
        _print_human_report(checks)
    return 1 if any(check.status == "fail" for check in checks) else 0


def _python_import_checks(
    packages: tuple[tuple[str, str], ...],
) -> tuple[ReadinessCheck, ...]:
    checks: list[ReadinessCheck] = []
    for import_name, purpose in packages:
        if importlib.util.find_spec(import_name) is None:
            checks.append(
                ReadinessCheck(
                    name=f"python package: {import_name}",
                    status="fail",
                    detail=f"Missing package for {purpose}.",
                    remediation="Run: python -m pip install -r requirements-dev.txt",
                )
            )
            continue
        checks.append(
            ReadinessCheck(
                name=f"python package: {import_name}",
                status="pass",
                detail=f"Import is available for {purpose}.",
            )
        )
    return tuple(checks)


def _ollama_service_check(host: str) -> ReadinessCheck:
    try:
        import ollama

        ollama.Client(host=host, timeout=5.0).list()
    except Exception as exc:
        return ReadinessCheck(
            name="Ollama service",
            status="fail",
            detail=f"Could not reach Ollama at {host}: {exc}",
            remediation="Start Ollama locally, then retry this check.",
        )
    return ReadinessCheck(
        name="Ollama service",
        status="pass",
        detail=f"Ollama is reachable at {host}.",
    )


def _ollama_model_check(host: str, model: str, role: str) -> ReadinessCheck:
    try:
        import ollama

        ollama.Client(host=host, timeout=5.0).show(model)
    except Exception as exc:
        return ReadinessCheck(
            name=f"Ollama {role} model",
            status="fail",
            detail=f"Model {model!r} is not available at {host}: {exc}",
            remediation=f"Run: ollama pull {model}",
        )
    return ReadinessCheck(
        name=f"Ollama {role} model",
        status="pass",
        detail=f"Model {model!r} is available locally.",
    )


def _executable_check(executable: str, name: str) -> ReadinessCheck:
    resolved = _resolve_executable(executable)
    if resolved is None:
        return ReadinessCheck(
            name=name,
            status="fail",
            detail=f"Executable {executable!r} was not found on PATH.",
            remediation=(
                "Activate the virtualenv and reinstall dependencies with: "
                "python -m pip install -r requirements-dev.txt"
            ),
        )
    return ReadinessCheck(
        name=name,
        status="pass",
        detail=f"Found {executable!r} at {resolved}.",
    )


def _resolve_executable(executable: str) -> str | None:
    resolved = shutil.which(executable)
    if resolved is not None:
        return resolved

    sibling = Path(sys.executable).with_name(executable)
    if sibling.is_file():
        return str(sibling)
    return None


def _file_check(path: Path, name: str, remediation: str) -> ReadinessCheck:
    if not path.is_file():
        return ReadinessCheck(
            name=name,
            status="fail",
            detail=f"Missing file: {path}",
            remediation=remediation,
        )
    return ReadinessCheck(
        name=name,
        status="pass",
        detail=f"Found file: {path}",
    )


def _wake_word_model_check(model_name: str) -> ReadinessCheck:
    spec = importlib.util.find_spec("openwakeword")
    if spec is None or spec.origin is None:
        return ReadinessCheck(
            name="openWakeWord model",
            status="fail",
            detail=(
                "openwakeword is not importable, so the model cache cannot be "
                "checked."
            ),
            remediation="Run: python -m pip install -r requirements-dev.txt",
        )

    package_dir = Path(spec.origin).resolve().parent
    model_path = package_dir / "resources" / "models" / model_name
    if not model_path.is_file():
        return ReadinessCheck(
            name="openWakeWord model",
            status="fail",
            detail=f"Missing wake-word model: {model_path}",
            remediation=(
                'Run: python -c "import openwakeword.utils; '
                'openwakeword.utils.download_models()"'
            ),
        )
    return ReadinessCheck(
        name="openWakeWord model",
        status="pass",
        detail=f"Found wake-word model: {model_path}",
    )


def _microphone_check() -> ReadinessCheck:
    try:
        import pyaudio

        audio = pyaudio.PyAudio()
        try:
            devices = [
                audio.get_device_info_by_index(index)
                for index in range(audio.get_device_count())
            ]
        finally:
            audio.terminate()
        input_devices = [
            device for device in devices if int(device.get("maxInputChannels", 0)) > 0
        ]
    except Exception as exc:
        return ReadinessCheck(
            name="microphone input",
            status="fail",
            detail=f"Could not enumerate input devices: {exc}",
            remediation="Check PortAudio, microphone permissions, and input hardware.",
        )

    if not input_devices:
        return ReadinessCheck(
            name="microphone input",
            status="fail",
            detail="No input audio devices were reported by PyAudio.",
            remediation="Connect or enable a microphone before live E2E.",
        )
    return ReadinessCheck(
        name="microphone input",
        status="pass",
        detail=f"Found {len(input_devices)} input audio device(s).",
    )


def _speaker_check() -> ReadinessCheck:
    try:
        import sounddevice as sd

        devices = sd.query_devices()
        output_devices = [
            device
            for device in devices
            if int(device.get("max_output_channels", 0)) > 0
        ]
    except Exception as exc:
        return ReadinessCheck(
            name="speaker output",
            status="fail",
            detail=f"Could not enumerate output devices: {exc}",
            remediation="Check speaker permissions, output hardware, and sounddevice.",
        )

    if not output_devices:
        return ReadinessCheck(
            name="speaker output",
            status="fail",
            detail="No output audio devices were reported by sounddevice.",
            remediation="Connect or enable an output device before live E2E.",
        )
    return ReadinessCheck(
        name="speaker output",
        status="pass",
        detail=f"Found {len(output_devices)} output audio device(s).",
    )


def _selected_reasoning_model(path: Path) -> str:
    if not path.is_file():
        return DEFAULT_REASONING_MODEL

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DEFAULT_REASONING_MODEL

    model = payload.get("model") if isinstance(payload, dict) else None
    if isinstance(model, str) and model.strip():
        return model.strip()
    return DEFAULT_REASONING_MODEL


def _print_human_report(checks: tuple[ReadinessCheck, ...]) -> None:
    for check in checks:
        print(f"[{check.status.upper()}] {check.name}: {check.detail}")
        if check.remediation:
            print(f"       {check.remediation}")

    failures = sum(1 for check in checks if check.status == "fail")
    warnings = sum(1 for check in checks if check.status == "warn")
    print(f"\nSummary: {failures} failure(s), {warnings} warning(s).")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
