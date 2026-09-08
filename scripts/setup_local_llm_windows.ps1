[CmdletBinding()]
param(
    [string]$Model = ""
)

$ErrorActionPreference = "Stop"
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    throw "winget was not found. Install Microsoft App Installer first."
}

Write-Host "[MdFlow] Installing Ollama with winget..."
winget install --exact --id Ollama.Ollama `
    --accept-package-agreements --accept-source-agreements --silent
if ($LASTEXITCODE -ne 0) {
    throw "Ollama installation failed (exit code: $LASTEXITCODE)."
}

if ($Model) {
    $ollama = Get-Command ollama -ErrorAction SilentlyContinue
    if (-not $ollama) {
        throw "Ollama was installed, but is not on the current PATH. Open a new terminal and run: ollama pull $Model"
    }
    Write-Host "[MdFlow] Downloading model: $Model"
    & ollama pull $Model
    if ($LASTEXITCODE -ne 0) { throw "Model download failed (exit code: $LASTEXITCODE)." }
}

Write-Host "[MdFlow] Local LLM setup completed. Restart MdFlow before use."
