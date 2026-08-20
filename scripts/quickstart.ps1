<#
.SYNOPSIS
    Granite Voice Concierge quick start for Windows.

.DESCRIPTION
    The PowerShell counterpart to scripts/quickstart.sh. Windows has no bash,
    so a Windows user would otherwise need WSL or Git Bash before they could
    run anything at all.

    It performs the same steps in the same order: check Docker and Ollama,
    pull the models, create the bind-mount directories, build the image,
    confirm the container can reach Ollama on the host, and start the service.

.EXAMPLE
    .\scripts\quickstart.ps1

.EXAMPLE
    $env:OLLAMA_MODEL = "granite3.3:2b"; .\scripts\quickstart.ps1
    Use a smaller model on a machine with less memory.
#>

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

function Write-Step { param([string]$Message) Write-Host $Message }
function Write-Problem { param([string]$Message) Write-Host $Message -ForegroundColor Red }

Write-Step "Granite Voice Concierge - Quick Start"
Write-Step ""

# Docker Compose reads .env by itself, but the native ollama commands below do
# not. Import the same file while letting an explicit shell variable win, which
# is also how Compose resolves precedence.
$shellModel = $env:OLLAMA_MODEL
$shellEmbeddingModel = $env:OLLAMA_EMBEDDING_MODEL

if (Test-Path ".env") {
    foreach ($line in Get-Content ".env") {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) { continue }
        $name, $value = $trimmed.Split("=", 2)
        if ($value) {
            Set-Item -Path "env:$($name.Trim())" -Value $value.Trim()
        }
    }
}

if ($shellModel) { $env:OLLAMA_MODEL = $shellModel }
if ($shellEmbeddingModel) { $env:OLLAMA_EMBEDDING_MODEL = $shellEmbeddingModel }

# Check required host applications.
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Problem "Docker not found. Install Docker Desktop for Windows:"
    Write-Problem "  https://docs.docker.com/desktop/install/windows-install/"
    exit 1
}

docker compose version *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Problem "Docker Compose plugin not found. Install or update Docker Desktop."
    exit 1
}

Write-Step "Docker found"
Write-Step ""

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Problem "Ollama not found. Install the Windows Ollama application first:"
    Write-Problem "  winget install Ollama.Ollama"
    Write-Problem "  or download it from https://ollama.com/download/windows"
    exit 1
}

try {
    Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 5 | Out-Null
} catch {
    Write-Problem "Native Ollama is not responding on http://127.0.0.1:11434"
    Write-Problem "Start the Ollama application, or run it bound to all interfaces:"
    Write-Problem '  $env:OLLAMA_HOST = "0.0.0.0:11434"; ollama serve'
    exit 1
}

Write-Step "Native Ollama is ready"
Write-Step ""

# Models are owned by native Ollama and stay outside the Docker image.
if (-not $env:OLLAMA_MODEL) { $env:OLLAMA_MODEL = "granite4.1:8b" }
ollama show $env:OLLAMA_MODEL *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Step "Downloading $($env:OLLAMA_MODEL) (first run only)..."
    ollama pull $env:OLLAMA_MODEL
}

if (-not $env:OLLAMA_EMBEDDING_MODEL) { $env:OLLAMA_EMBEDDING_MODEL = "granite-embedding:278m" }
ollama show $env:OLLAMA_EMBEDDING_MODEL *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Step "Downloading $($env:OLLAMA_EMBEDDING_MODEL) (first run only)..."
    ollama pull $env:OLLAMA_EMBEDDING_MODEL
}

# Creating the bind-mount sources on the host keeps existing application state
# and matches what the shell script does.
foreach ($directory in @(
    "data/.local/memory",
    "data/.local/preferences",
    "data/.local/reminders",
    "data/.local/logs"
)) {
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
}

Write-Step "Building Docker image..."
docker compose build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# Confirm the host service is reachable from inside Docker before starting the
# long-running container. On Windows this is the step that usually fails,
# because Ollama listens on 127.0.0.1 only and the container is a separate host.
Write-Step "Checking Ollama access from Docker..."
docker compose run --rm --no-deps --entrypoint sh voice-concierge `
    -c 'curl --fail --silent "$OLLAMA_API_URL/api/tags" > /dev/null'
if ($LASTEXITCODE -ne 0) {
    Write-Problem "Docker cannot reach native Ollama."
    Write-Problem "Ollama listens on 127.0.0.1 by default, which the container cannot see."
    Write-Problem "Set it to listen on all interfaces, then restart Ollama:"
    Write-Problem '  setx OLLAMA_HOST "0.0.0.0:11434"'
    Write-Problem "Quit Ollama from the system tray and start it again for this to apply."
    exit 1
}

Write-Step "Starting Granite Voice Concierge..."
docker compose up -d
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Step ""
Write-Step "Service Status:"
docker compose ps
Write-Step ""

Write-Step "Next Steps:"
Write-Step ""
Write-Step "1. Native Ollama model is ready: $($env:OLLAMA_MODEL)"
Write-Step "   The embedding model is ready: $($env:OLLAMA_EMBEDDING_MODEL)"
Write-Step ""
Write-Step "2. Access Web UI:"
Write-Step "   start http://127.0.0.1:4173"
Write-Step ""
Write-Step "3. View logs:"
Write-Step "   docker compose logs -f voice-concierge"
Write-Step ""
Write-Step "4. Stop without deleting data:"
Write-Step "   docker compose down"
Write-Step ""
Write-Step "Note: continuous live voice (the wake-word loop) needs direct microphone"
Write-Step "access and is not available through Docker on Windows. The browser UI at"
Write-Step "the address above uses your browser's microphone instead."
Write-Step ""
