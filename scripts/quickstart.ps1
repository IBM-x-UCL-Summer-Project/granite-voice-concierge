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

# PowerShell 7.3 and later turn a native command's stderr into a terminating
# error when ErrorActionPreference is Stop, and it is on by default from 7.4.
# That matters here because "ollama show" writes to stderr for a model that is
# not installed yet, which is the normal first-run case: the script would stop
# at the check instead of going on to download the model. Exit codes are what
# this script tests, so opt out and keep testing them.
$PSNativeCommandUseErrorActionPreference = $false

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

# Windows PowerShell inherits Internet Explorer's proxy settings, and a proxy
# configured for a university or company network will happily intercept a
# request to 127.0.0.1 and fail it. Ollama is local, so never use a proxy here.
[System.Net.WebRequest]::DefaultWebProxy = $null

function Test-OllamaEndpoint {
    <#
        Returns the error from probing one address, or $null when it answered.
        Both loopback spellings are tried by the caller because Ollama may bind
        to IPv4 or IPv6 only, and 127.0.0.1 and localhost do not always resolve
        to the same interface on Windows.
    #>
    param([string]$BaseUrl)

    $request = @{ Uri = "$BaseUrl/api/tags"; TimeoutSec = 5 }
    # PowerShell 7 has -NoProxy; Windows PowerShell 5.1 does not and instead
    # honours the DefaultWebProxy cleared above. Passing -Proxy $null to 5.1 is
    # a parameter binding error, so ask before using it.
    if ((Get-Command Invoke-RestMethod).Parameters.ContainsKey("NoProxy")) {
        $request.NoProxy = $true
    }

    try {
        Invoke-RestMethod @request | Out-Null
        return $null
    } catch {
        return $_.Exception.Message
    }
}

$ollamaUrl = $null
$probeErrors = @()
foreach ($candidate in @("http://127.0.0.1:11434", "http://localhost:11434")) {
    $probeError = Test-OllamaEndpoint -BaseUrl $candidate
    if (-not $probeError) {
        $ollamaUrl = $candidate
        break
    }
    $probeErrors += "  $candidate -> $probeError"
}

if (-not $ollamaUrl) {
    Write-Problem "Native Ollama is not responding."
    Write-Problem ""
    Write-Problem "What was tried:"
    $probeErrors | ForEach-Object { Write-Problem $_ }
    Write-Problem ""

    # Say which of the two situations this is, rather than making the reader
    # guess: a stopped Ollama and a blocked request need different fixes.
    $listening = $null
    if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
        $listening = Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue
    }
    $running = Get-Process -Name "ollama*" -ErrorAction SilentlyContinue

    if (-not $running) {
        Write-Problem "No ollama process is running. On Windows, Ollama normally runs"
        Write-Problem "as a tray application: open Ollama from the Start menu and wait for"
        Write-Problem "the tray icon to appear, then run this script again."
        Write-Problem ""
        Write-Problem "Running 'ollama serve' in a terminal is the alternative to the tray"
        Write-Problem "application, not an addition to it. It fails with an address-in-use"
        Write-Problem "error if the tray application is already running."
    } elseif (-not $listening) {
        Write-Problem "Ollama is running but nothing is listening on port 11434."
        Write-Problem "It may be bound to another port. Check with:"
        Write-Problem "  Get-NetTCPConnection -State Listen | Where-Object OwningProcess -in (Get-Process ollama*).Id"
    } else {
        Write-Problem "Ollama is running and port 11434 is open, so the request itself was"
        Write-Problem "blocked. This is usually a proxy, a VPN, or security software."
        Write-Problem "Confirm the port answers at all with:"
        Write-Problem "  curl.exe http://127.0.0.1:11434/api/tags"
        Write-Problem "If that works, exclude localhost from your proxy or VPN and retry."
    }
    exit 1
}

Write-Step "Native Ollama is ready"
Write-Step ""

# OLLAMA_HOST is read by the server as the address to bind and by the CLI as
# the address to reach. Anyone who set it to 0.0.0.0 so the container could
# connect has also pointed their CLI at 0.0.0.0, where "ollama show" can report
# a model missing that is really present. Pin the CLI to loopback for the calls
# below, whatever the user set globally, and restore it afterwards.
$callerOllamaHost = $env:OLLAMA_HOST
$env:OLLAMA_HOST = $ollamaUrl

function Confirm-OllamaModel {
    <#
        Make sure one model is present locally, pulling it if it is not.
        A failed pull stops the script here: continuing would build and start
        everything only for the first turn to fail with a missing model.
    #>
    param([string]$Name)

    ollama show $Name *> $null
    if ($LASTEXITCODE -eq 0) {
        return
    }

    Write-Step "Downloading $Name (first run only)..."
    ollama pull $Name
    if ($LASTEXITCODE -ne 0) {
        Write-Problem ""
        Write-Problem "Could not download $Name."
        Write-Problem ""
        Write-Problem "Check the name exists and that there is disk space for it:"
        Write-Problem "  ollama pull $Name"
        Write-Problem "  ollama list"
        Write-Problem ""
        Write-Problem "To use a smaller model instead, set it and run this script again:"
        Write-Problem '  $env:OLLAMA_MODEL = "granite4.1:3b"; .\scripts\quickstart.ps1'
        exit 1
    }
}

# Models are owned by native Ollama and stay outside the Docker image.
if (-not $env:OLLAMA_MODEL) { $env:OLLAMA_MODEL = "granite4.1:8b" }
Confirm-OllamaModel -Name $env:OLLAMA_MODEL

if (-not $env:OLLAMA_EMBEDDING_MODEL) { $env:OLLAMA_EMBEDDING_MODEL = "granite-embedding:278m" }
Confirm-OllamaModel -Name $env:OLLAMA_EMBEDDING_MODEL

# The container needs the host address, not the loopback one used above.
$env:OLLAMA_HOST = $callerOllamaHost

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
    Write-Problem ""
    Write-Problem "If Ollama runs from the system tray, set the variable for your account"
    Write-Problem "and restart it:"
    Write-Problem '  setx OLLAMA_HOST "0.0.0.0:11434"'
    Write-Problem "Then quit Ollama from the tray and open it again. setx only affects"
    Write-Problem "processes started afterwards, so the restart is required."
    Write-Problem ""
    Write-Problem "If you start Ollama yourself in a terminal instead, set it there:"
    Write-Problem '  $env:OLLAMA_HOST = "0.0.0.0:11434"; ollama serve'
    Write-Problem ""
    Write-Problem "Only do this on a network you trust. Ollama has no authentication, so"
    Write-Problem "anything able to reach the port can use your models."
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
