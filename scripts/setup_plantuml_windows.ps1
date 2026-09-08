[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$javaPackage = "EclipseAdoptium.Temurin.21.JRE"
$projectRoot = Split-Path -Parent $PSScriptRoot
$fetchScript = Join-Path $PSScriptRoot "fetch_plantuml.py"
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    throw "winget was not found. Install Microsoft App Installer first."
}

Write-Host "[MdFlow] Installing the Java runtime with winget..."
winget install --exact --id $javaPackage `
    --accept-package-agreements --accept-source-agreements --silent
if ($LASTEXITCODE -ne 0) {
    throw "Java runtime installation failed (exit code: $LASTEXITCODE)."
}

if (Test-Path -LiteralPath $venvPython) {
    $python = $venvPython
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $python = "py"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $python = "python"
} else {
    throw "Python was not found; the PlantUML JAR could not be downloaded."
}

Write-Host "[MdFlow] Downloading the pinned PlantUML JAR..."
if ($python -eq "py") {
    & $python -3 $fetchScript
} else {
    & $python $fetchScript
}
if ($LASTEXITCODE -ne 0) {
    throw "PlantUML JAR download failed (exit code: $LASTEXITCODE)."
}

Write-Host ""
Write-Host "[MdFlow] PlantUML setup completed."
Write-Host "Restart MdFlow so that it can use Java from the updated PATH."
