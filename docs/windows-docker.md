# Windows Docker Guide

This guide covers the supported x86-64 Windows deployment. Granite Voice
Concierge runs as a Linux container in Docker Desktop, while Ollama runs as a
native Windows application. Compose does not install, start, stop, or upgrade
Ollama.

Windows on Arm is not currently supported because the complete native Python
and machine-learning dependency set has not been validated for Linux Arm
containers on Docker Desktop for Windows.

## Prerequisites

Install and start all of the following before running the quick start:

- a Windows release supported by Docker Desktop;
- current WSL 2, with hardware virtualisation enabled;
- Docker Desktop using the WSL 2 backend and Linux containers;
- Ollama for Windows, running in the taskbar; and
- Git for Windows and Windows PowerShell 5.1 or newer.

Use `wsl --version` to inspect WSL and `wsl --update` from an elevated
PowerShell session when it needs updating. Docker documents its current Windows
and WSL requirements in the
[Docker Desktop installation guide](https://docs.docker.com/desktop/setup/install/windows-install/).

The first setup requires internet access for container layers, Python packages,
Piper, Whisper, Vosk, and Ollama models. Normal operation remains local after
the required images and models have been downloaded. Model downloads need
several gigabytes of free disk space; the selected Granite model must also fit
in available system or GPU memory.

## Make Ollama reachable from Docker Desktop

Ollama serves `http://127.0.0.1:11434` by default. The host itself can use that
address, but a Linux container normally needs Ollama to accept connections on a
non-loopback host interface.

Set `OLLAMA_HOST` once for the Windows user from PowerShell:

```powershell
[Environment]::SetEnvironmentVariable(
    "OLLAMA_HOST",
    "0.0.0.0:11434",
    "User"
)
```

Quit Ollama from its taskbar icon and start it again from the Windows Start menu
so it inherits the new setting. Confirm the host API responds:

```powershell
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```

Binding Ollama to `0.0.0.0` makes it listen on Windows network interfaces, not
only the loopback interface. Keep TCP port `11434` blocked from public and
untrusted networks in Windows Defender Firewall. The application container
reaches it through Docker Desktop's `host.docker.internal` gateway; Ollama does
not need to be exposed through a Compose port mapping.

See the [Ollama FAQ](https://docs.ollama.com/faq) for the current Windows
environment-variable procedure.

## Quick start

Open PowerShell in the repository root. Create the ignored local configuration
file, then run the Windows launcher:

```powershell
Copy-Item .env.example .env
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\quickstart.ps1
```

`-ExecutionPolicy Bypass` applies only to that PowerShell process; it does not
change the user's persistent execution policy. The launcher:

1. validates Docker Desktop, Compose, and native Ollama;
2. pulls the configured Granite reasoning model when it is missing;
3. pulls the local Granite embedding model when it is missing;
4. creates the persistent data directories;
5. validates and builds the Linux application image;
6. verifies that the container can reach host Ollama;
7. starts the application and waits for local models to initialise; and
8. opens `http://127.0.0.1:4173` in the default browser.

The initial build and startup can take several minutes. To prevent the launcher
from opening a browser, add `-NoBrowser`. To allow more than the default ten
minutes for first-start model initialisation, use for example:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
    -File .\scripts\quickstart.ps1 `
    -NoBrowser `
    -HealthTimeoutSeconds 1200
```

## Voice input and output

Do not add Linux `/dev/snd` mappings on Docker Desktop for Windows. The browser
captures microphone audio and sends it to the same-origin local application;
the container performs local wake-word detection and transcription. Piper
generates response audio in the container and the browser plays it through the
selected Windows output device.

When prompted by the browser, allow microphone access for
`http://127.0.0.1:4173`. Windows privacy settings must also allow microphone
access for desktop applications and the selected browser. The host-native
continuous microphone runner is not part of the Windows Docker deployment; use
the browser's push-to-talk or wake-word interface.

## Normal operation

Run these commands from the repository root:

```powershell
# Show service and health state
docker compose ps
Invoke-RestMethod http://127.0.0.1:4173/api/health

# Follow logs; Ctrl-C stops following without stopping the container
docker compose logs -f voice-concierge

# Stop while retaining application data and downloaded models
docker compose down

# Start again without rebuilding
docker compose up -d
```

Application data persists under `data\.local`. Whisper, Vosk, and related model
caches persist in the Docker volume `voice-model-cache`. Ollama models remain in
the native Windows Ollama model directory.

Do not use `docker compose down -v` unless deleting the application model cache
is intentional. Deleting `data\.local` removes saved memories, reminders,
preferences, and application logs.

## Troubleshooting

### Docker Desktop is installed but unavailable

Start Docker Desktop, verify it is using Linux containers, then run:

```powershell
docker info
docker compose version
```

Both commands must succeed before starting the application. If Docker reports a
WSL error, update WSL, restart Windows, and start Docker Desktop again.

### The host responds but the container cannot reach Ollama

First confirm native Ollama is running:

```powershell
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```

Then run the same probe used by the launcher:

```powershell
docker compose run --rm --no-deps --entrypoint sh voice-concierge `
    -c 'curl --fail --silent "$OLLAMA_API_URL/api/tags"'
```

If the host check passes but the container check fails, confirm that the user
`OLLAMA_HOST` value is `0.0.0.0:11434`, fully quit and restart Ollama, and check
Windows Firewall, VPN, and endpoint-security rules affecting Docker Desktop.
Docker Desktop documents `host.docker.internal` in its
[networking guide](https://docs.docker.com/desktop/features/networking/networking-how-tos/).

### Startup remains in starting or unhealthy state

Inspect the application and health state:

```powershell
docker compose ps
docker compose logs --tail 200 voice-concierge
```

The first run may still be downloading or loading Whisper. A reported startup
failure is different from slow initialisation: resolve the error in the logs,
then recreate the service with `docker compose up -d --force-recreate`.

### An Ollama model does not download

The launcher prints `Downloading <model> with Ollama` before each automatic
download. If the download itself fails, update Ollama, fully quit and restart
it, then rerun the launcher. To retry the default reasoning model directly
against the local Ollama server:

```powershell
$previousOllamaHost = $env:OLLAMA_HOST
$env:OLLAMA_HOST = "http://127.0.0.1:11434"
try {
    ollama pull granite4.1:8b
}
finally {
    $env:OLLAMA_HOST = $previousOllamaHost
}
```

The temporary process value is intentional: the Ollama application can keep
binding to `0.0.0.0:11434` for Docker Desktop while the CLI connects to it over
Windows loopback. Confirm the completed download with
`ollama list`, then rerun `scripts\quickstart.ps1`.

### Port 4173 is already in use

Identify the process using it:

```powershell
Get-NetTCPConnection -LocalPort 4173 -ErrorAction SilentlyContinue
```

Stop the conflicting process or change only the host side of the port mapping
in `docker-compose.yml`, for example `127.0.0.1:5000:4173`. Continue to bind the
host side to `127.0.0.1` unless remote access has been deliberately secured.

### Corporate proxy or VPN interferes with downloads

Configure Docker Desktop's proxy settings for image and build downloads. Ollama
uses `HTTPS_PROXY` for model downloads; do not set `HTTP_PROXY` for Ollama,
because it can interfere with local client connections. Any private certificate
authority required by the proxy must be trusted by both Windows and the Docker
build environment.
