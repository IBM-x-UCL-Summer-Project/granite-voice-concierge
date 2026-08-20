[CmdletBinding()]
param(
    [switch] $NoBrowser,
    [switch] $ValidateOnly,
    [ValidateRange(30, 3600)]
    [int] $HealthTimeoutSeconds = 600
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
    param([Parameter(Mandatory = $true)][string] $Message)

    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Assert-CommandAvailable {
    param(
        [Parameter(Mandatory = $true)][string] $Name,
        [Parameter(Mandatory = $true)][string] $InstallMessage
    )

    if ($null -eq (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name was not found. $InstallMessage"
    }
}

function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory = $true)][string] $FilePath,
        [Parameter(Mandatory = $true)][string[]] $ArgumentList
    )

    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        $renderedArguments = $ArgumentList -join " "
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $renderedArguments"
    }
}

function Test-NativeCommand {
    param(
        [Parameter(Mandatory = $true)][string] $FilePath,
        [Parameter(Mandatory = $true)][string[]] $ArgumentList
    )

    & $FilePath @ArgumentList *> $null
    return $LASTEXITCODE -eq 0
}

function Read-ComposeEnvironment {
    param([Parameter(Mandatory = $true)][string] $Path)

    $values = @{}
    foreach ($line in Get-Content -LiteralPath $Path) {
        $trimmed = $line.Trim()
        if ($trimmed.Length -eq 0 -or $trimmed.StartsWith("#")) {
            continue
        }

        $separator = $trimmed.IndexOf("=")
        if ($separator -lt 1) {
            throw "Invalid environment entry in ${Path}: $line"
        }

        $name = $trimmed.Substring(0, $separator).Trim()
        $value = $trimmed.Substring($separator + 1).Trim()
        if ($value.Length -ge 2) {
            $first = $value.Substring(0, 1)
            $last = $value.Substring($value.Length - 1, 1)
            if (($first -eq '"' -and $last -eq '"') -or
                ($first -eq "'" -and $last -eq "'")) {
                $value = $value.Substring(1, $value.Length - 2)
            }
        }
        $values[$name] = $value
    }
    return $values
}

function Resolve-Setting {
    param(
        [Parameter(Mandatory = $true)][string] $Name,
        [Parameter(Mandatory = $true)][hashtable] $FileValues,
        [Parameter(Mandatory = $true)][string] $DefaultValue
    )

    $processValue = [Environment]::GetEnvironmentVariable($Name, "Process")
    if (-not [string]::IsNullOrWhiteSpace($processValue)) {
        return $processValue
    }
    if ($FileValues.ContainsKey($Name) -and
        -not [string]::IsNullOrWhiteSpace([string] $FileValues[$Name])) {
        return [string] $FileValues[$Name]
    }
    return $DefaultValue
}

function Test-OllamaApi {
    param([Parameter(Mandatory = $true)][string] $Uri)

    try {
        $null = Invoke-RestMethod -Method Get -Uri $Uri -TimeoutSec 5
        return $true
    }
    catch {
        return $false
    }
}

function Get-NormalizedOllamaModelName {
    param([Parameter(Mandatory = $true)][string] $Name)

    if ($Name.Contains(":")) {
        return $Name
    }
    return "${Name}:latest"
}

function Test-OllamaModelAvailable {
    param(
        [Parameter(Mandatory = $true)][string] $TagsUri,
        [Parameter(Mandatory = $true)][string] $Model
    )

    $expectedName = Get-NormalizedOllamaModelName -Name $Model
    $response = Invoke-RestMethod -Method Get -Uri $TagsUri -TimeoutSec 10
    foreach ($installedModel in @($response.models)) {
        $installedNames = @(
            [string] $installedModel.name,
            [string] $installedModel.model
        )
        foreach ($installedName in $installedNames) {
            if (-not [string]::IsNullOrWhiteSpace($installedName) -and
                (Get-NormalizedOllamaModelName -Name $installedName) -eq $expectedName) {
                return $true
            }
        }
    }
    return $false
}

function Install-OllamaModel {
    param(
        [Parameter(Mandatory = $true)][string] $TagsUri,
        [Parameter(Mandatory = $true)][string] $Model
    )

    Write-Host "Downloading $Model with Ollama (first run only)..." -ForegroundColor Yellow

    # OLLAMA_HOST configures both the Ollama server bind address and the CLI's
    # destination. Windows users commonly set it to 0.0.0.0 so Docker Desktop
    # can reach the server. Point only this child process at loopback so the CLI
    # always talks to that same local server while it downloads the model.
    $previousOllamaHost = [Environment]::GetEnvironmentVariable("OLLAMA_HOST", "Process")
    try {
        $env:OLLAMA_HOST = "http://127.0.0.1:11434"
        Invoke-NativeCommand -FilePath "ollama" -ArgumentList @("pull", $Model)
    }
    finally {
        [Environment]::SetEnvironmentVariable(
            "OLLAMA_HOST",
            $previousOllamaHost,
            "Process"
        )
    }

    if (-not (Test-OllamaModelAvailable -TagsUri $TagsUri -Model $Model)) {
        throw "Ollama completed the pull but model $Model is not available from the local server."
    }
}

function Wait-ApplicationReady {
    param(
        [Parameter(Mandatory = $true)][string] $Uri,
        [Parameter(Mandatory = $true)][int] $TimeoutSeconds
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $health = Invoke-RestMethod -Method Get -Uri $Uri -TimeoutSec 5
            if ($health.status -eq "ready") {
                return $true
            }
            if ($health.status -eq "error") {
                $message = [string] $health.message
                throw "The application reported a startup failure: $message"
            }
        }
        catch {
            if ($_.Exception.Message.StartsWith("The application reported")) {
                throw
            }
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Invoke-QuickStart {
    $repositoryRoot = Split-Path -Parent $PSScriptRoot
    Push-Location $repositoryRoot
    try {
        $exampleEnvironmentPath = Join-Path $repositoryRoot ".env.example"
        $environmentPath = Join-Path $repositoryRoot ".env"
        if (-not (Test-Path -LiteralPath $exampleEnvironmentPath -PathType Leaf)) {
            throw "Missing environment template: $exampleEnvironmentPath"
        }

        if ($ValidateOnly) {
            $settingsPath = $exampleEnvironmentPath
        }
        else {
            if (-not (Test-Path -LiteralPath $environmentPath -PathType Leaf)) {
                Copy-Item -LiteralPath $exampleEnvironmentPath -Destination $environmentPath
                Write-Host "Created .env from .env.example"
            }
            $settingsPath = $environmentPath
        }

        $fileValues = Read-ComposeEnvironment -Path $settingsPath
        $reasoningModel = Resolve-Setting `
            -Name "OLLAMA_MODEL" `
            -FileValues $fileValues `
            -DefaultValue "granite4.1:8b"
        $embeddingModel = Resolve-Setting `
            -Name "OLLAMA_EMBEDDING_MODEL" `
            -FileValues $fileValues `
            -DefaultValue "granite-embedding:278m"

        if ($ValidateOnly) {
            Write-Host "Windows quick-start configuration is valid."
            Write-Host "Reasoning model: $reasoningModel"
            Write-Host "Embedding model: $embeddingModel"
            return
        }

        Write-Host "Granite Voice Concierge - Windows Quick Start" -ForegroundColor Green

        Write-Step "Checking host prerequisites"
        Assert-CommandAvailable `
            -Name "docker" `
            -InstallMessage "Install and start Docker Desktop using Linux containers."
        Assert-CommandAvailable `
            -Name "ollama" `
            -InstallMessage "Install Ollama for Windows and start the Ollama application."
        Invoke-NativeCommand -FilePath "docker" -ArgumentList @("compose", "version")
        if (-not (Test-NativeCommand -FilePath "docker" -ArgumentList @("info"))) {
            throw "Docker Desktop is installed but its Linux container engine is not running."
        }

        $hostOllamaTags = "http://127.0.0.1:11434/api/tags"
        if (-not (Test-OllamaApi -Uri $hostOllamaTags)) {
            throw @"
Ollama is installed but is not responding at http://127.0.0.1:11434.
Start the Ollama application from the Windows Start menu and run this script again.
"@
        }
        Write-Host "Docker Desktop and native Ollama are running."

        Write-Step "Checking local Ollama models"
        if (-not (Test-OllamaModelAvailable -TagsUri $hostOllamaTags -Model $reasoningModel)) {
            Install-OllamaModel -TagsUri $hostOllamaTags -Model $reasoningModel
        }
        else {
            Write-Host "Reasoning model is available: $reasoningModel"
        }
        if (-not (Test-OllamaModelAvailable -TagsUri $hostOllamaTags -Model $embeddingModel)) {
            Install-OllamaModel -TagsUri $hostOllamaTags -Model $embeddingModel
        }
        else {
            Write-Host "Embedding model is available: $embeddingModel"
        }

        Write-Step "Preparing persistent application data"
        $persistentDirectories = @(
            "data/.local/memory",
            "data/.local/preferences",
            "data/.local/reminders",
            "data/.local/logs"
        )
        foreach ($directory in $persistentDirectories) {
            $null = New-Item -ItemType Directory -Path $directory -Force
        }

        Write-Step "Validating and building the Linux container"
        Invoke-NativeCommand -FilePath "docker" -ArgumentList @("compose", "config", "--quiet")
        Invoke-NativeCommand -FilePath "docker" -ArgumentList @("compose", "build")

        Write-Step "Checking container access to host Ollama"
        $probeArguments = @(
            "compose", "run", "--rm", "--no-deps",
            "--entrypoint", "sh", "voice-concierge", "-c",
            'curl --fail --silent "$OLLAMA_API_URL/api/tags" > /dev/null'
        )
        if (-not (Test-NativeCommand -FilePath "docker" -ArgumentList $probeArguments)) {
            throw @"
The application container cannot reach Ollama on the Windows host.

Ollama listens only on loopback by default. Set this user environment variable:
  [Environment]::SetEnvironmentVariable("OLLAMA_HOST", "0.0.0.0:11434", "User")

Then quit Ollama from the taskbar, start it again from the Start menu, and rerun
this script. Keep port 11434 blocked from untrusted networks in Windows Firewall.
"@
        }

        Write-Step "Starting Granite Voice Concierge"
        Invoke-NativeCommand -FilePath "docker" -ArgumentList @("compose", "up", "-d")

        $healthUri = "http://127.0.0.1:4173/api/health"
        Write-Host "Waiting up to $HealthTimeoutSeconds seconds for local models to initialise..."
        if (-not (Wait-ApplicationReady -Uri $healthUri -TimeoutSeconds $HealthTimeoutSeconds)) {
            Write-Host "Recent container logs:" -ForegroundColor Yellow
            & docker compose logs --tail 100 voice-concierge
            throw "The application did not become ready within $HealthTimeoutSeconds seconds."
        }

        Write-Host ""
        Write-Host "Granite Voice Concierge is ready." -ForegroundColor Green
        Write-Host "Web UI: http://127.0.0.1:4173"
        Write-Host "Logs:  docker compose logs -f voice-concierge"
        Write-Host "Stop:  docker compose down"

        if (-not $NoBrowser) {
            try {
                Start-Process "http://127.0.0.1:4173"
            }
            catch {
                Write-Warning "Could not open the browser automatically: $($_.Exception.Message)"
            }
        }
    }
    finally {
        Pop-Location
    }
}

Invoke-QuickStart
