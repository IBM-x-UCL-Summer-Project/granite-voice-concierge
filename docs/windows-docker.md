# Windows Docker Support

The [main README](../README.md#windows) contains the complete copy/paste setup
and operation commands. Check its
[system requirements and download sizes](../README.md#system-requirements-and-download-sizes)
before the first installation. This guide explains the Windows deployment and
provides error-specific diagnostics.

## Deployment model

The supported Windows deployment is x86-64 Windows with Docker Desktop running
Linux containers through WSL 2. Windows on Arm has not been validated.

- Ollama runs as a native Windows application so it can use the host hardware.
- Granite Voice Concierge runs in a Linux container.
- The container reaches Ollama at `host.docker.internal:11434`.
- The browser reaches the application at `http://127.0.0.1:4173`.
- Memories and reminders remain in the repository's `data\.local` directory.
- Speech-model caches remain in the Docker volume `voice-model-cache`.

Docker Desktop documents the current Windows and WSL requirements in its
[Windows installation guide](https://docs.docker.com/desktop/setup/install/windows-install/)
and [WSL 2 guide](https://docs.docker.com/desktop/features/wsl/).

## Ollama networking and security

Ollama normally listens only on Windows loopback. A Linux container cannot use
its own `127.0.0.1` to reach a Windows service, so the one-time setup in the
[main README](../README.md#configure-ollama-for-windows-once) configures
Ollama to listen on `0.0.0.0:11434`.

Docker Desktop resolves `host.docker.internal` to the host and proxies the
container connection. See Docker's
[host-service networking documentation](https://docs.docker.com/desktop/features/networking/networking-how-tos/#connect-a-container-to-a-service-on-the-host).

Listening on `0.0.0.0` also exposes Ollama on Windows network interfaces. Keep
port `11434` blocked from public and untrusted networks in Windows Defender
Firewall or the applicable endpoint-security product. Ollama documents its
Windows environment-variable behavior in the
[Ollama FAQ](https://docs.ollama.com/faq#setting-environment-variables-on-windows).

## What the launcher does

`scripts\quickstart.ps1`:

1. verifies Docker Desktop, Compose, and native Ollama;
2. downloads missing Granite reasoning and embedding models;
3. prepares persistent application directories;
4. builds the Linux image and normalizes its entrypoint line endings;
5. verifies container-to-host Ollama connectivity;
6. starts the application and reports initialization progress; and
7. opens the local browser interface after the health check reports `ready`.

The initial build downloads container layers, Python packages, speech assets,
and Ollama models. Later starts reuse the Docker layers, application cache, and
host Ollama storage.

## Browser voice behavior

The browser captures the Windows microphone and sends audio to the local
application. The container performs wake-word detection and transcription,
generates Piper audio, and returns it to the browser for playback.

Allow microphone access for `http://127.0.0.1:4173` in both the browser prompt
and Windows privacy settings. Use the browser's push-to-talk or wake-word
controls; the host-native continuous microphone runner is not part of the
Windows Docker deployment.

## Persistent data

| Data                                   | Location                          | Removed by `docker compose down` |
| -------------------------------------- | --------------------------------- | -------------------------------- |
| Memories, reminders, and preferences  | `data\.local`                    | No                               |
| Whisper, Vosk, and application caches | Docker volume `voice-model-cache` | No                               |
| Ollama models                          | Native Ollama model directory     | No                               |
| Container logs                         | Docker logging storage            | Container-dependent              |

`docker compose down -v` deletes `voice-model-cache`. Deleting `data\.local`
deletes saved user data. Neither action is required for normal updates or
rebuilds.

## Troubleshooting

### Collect the useful diagnostics

Run these from the repository root in a second PowerShell window:

```powershell
docker compose ps --all
Invoke-RestMethod http://127.0.0.1:4173/api/health
ollama ps
docker compose logs --tail 200 voice-concierge
```

If the health request cannot connect, the container is still starting or has
exited. `docker compose ps --all` and the logs distinguish those cases.

### Docker Desktop or WSL is unavailable

```powershell
wsl --version
docker info
docker compose version
```

If WSL is outdated, run `wsl --update`, restart Windows, and start Docker
Desktop. Confirm Docker Desktop is using Linux containers. Follow Docker's
[Windows installation troubleshooting](https://docs.docker.com/desktop/setup/install/windows-install/)
for WSL or virtualization errors.

### Native Ollama is unavailable

```powershell
ollama --version
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```

If the command-line tool exists but the API does not respond, fully quit Ollama
from the taskbar and start it again from the Start menu.

### The host reaches Ollama but the container cannot

Run the same probe as the launcher:

```powershell
docker compose run --rm --no-deps --entrypoint sh voice-concierge `
    -c 'curl --fail --silent "$OLLAMA_API_URL/api/tags"'
```

If this fails while the host API succeeds:

1. confirm the user `OLLAMA_HOST` value is `0.0.0.0:11434`;
2. restart Ollama so it inherits that value;
3. check Windows Firewall and endpoint-security rules for Docker Desktop; and
4. temporarily disconnect a VPN to determine whether it is intercepting
   `host.docker.internal` traffic.

### A model does not download

Update and restart Ollama first. To retry the default models directly against
the local server:

```powershell
$previousOllamaHost = $env:OLLAMA_HOST
$env:OLLAMA_HOST = "http://127.0.0.1:11434"
try {
    ollama pull granite4.1:8b
    ollama pull granite-embedding:278m
}
finally {
    $env:OLLAMA_HOST = $previousOllamaHost
}
ollama list
```

For proxy-controlled networks, configure `HTTPS_PROXY` for Ollama and trust the
required certificate. Do not set `HTTP_PROXY` for Ollama because it can disrupt
local client connections. See the [Ollama proxy guidance](https://docs.ollama.com/faq#how-do-i-use-ollama-behind-a-proxy).

### Startup remains at `starting`

```powershell
Invoke-RestMethod http://127.0.0.1:4173/api/health
ollama ps
docker compose logs --tail 200 voice-concierge
```

`status: starting` means the web service is responding while Ollama loads and
warms the reasoning model. A cold start is slower than a later start. The
launcher reports progress every ten seconds and automatically prints logs if
the application reports `error`, the container exits, or the timeout expires.

To permit a longer first start:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
    -File .\scripts\quickstart.ps1 `
    -NoBrowser `
    -HealthTimeoutSeconds 1200
```

### Logs report `entrypoint.sh: no such file or directory`

This indicates an image built from an older revision that retained Windows CRLF
line endings. Update and rebuild:

```powershell
git pull --ff-only
docker compose build voice-concierge
docker compose up -d --force-recreate
```

Current images normalize the Linux entrypoint during the Docker build.

### Port 4173 is already in use

```powershell
Get-NetTCPConnection -LocalPort 4173 -ErrorAction SilentlyContinue
```

Stop the conflicting process or change only the host side of the port mapping
in `docker-compose.yml`, for example `127.0.0.1:5000:4173`. Keep the host binding
on `127.0.0.1` unless a secured remote deployment has been reviewed.

### Docker or model downloads fail behind a proxy

Configure Docker Desktop under **Settings > Resources > Proxies**. Docker's
[networking guide](https://docs.docker.com/desktop/features/networking/networking-how-tos/)
describes proxy and VPN behavior. Private certificate authorities must be
trusted by Windows, Ollama, and the Docker build environment as applicable.
