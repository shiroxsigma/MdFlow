[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$javaPackage = "EclipseAdoptium.Temurin.21.JRE"
$graphvizPackage = "Graphviz.Graphviz"
$projectRoot = Split-Path -Parent $PSScriptRoot
$fetchScript = Join-Path $PSScriptRoot "fetch_plantuml.py"
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    throw "winget was not found. Install Microsoft App Installer first."
}

function Install-WingetPackage([string]$Id, [string]$Label) {
    winget list --exact --id $Id --accept-source-agreements --disable-interactivity *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[MdFlow] $Label is already installed."
        return
    }
    Write-Host "[MdFlow] Installing/checking $Label with winget..."
    winget install --exact --id $Id --accept-package-agreements `
        --accept-source-agreements --silent --disable-interactivity
    if ($LASTEXITCODE -ne 0) {
        throw "$Label installation failed (exit code: $LASTEXITCODE)."
    }
}

Install-WingetPackage $javaPackage "Java 21 runtime"
Install-WingetPackage $graphvizPackage "Graphviz"

# winget updates the persistent PATH, but this PowerShell process keeps its old value.
$machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$env:Path = "$machinePath;$userPath"

$dot = Get-Command dot -ErrorAction SilentlyContinue
if (-not $dot) {
    $graphvizBin = Join-Path $env:ProgramFiles "Graphviz\bin"
    if (Test-Path -LiteralPath (Join-Path $graphvizBin "dot.exe")) {
        $userParts = @($userPath -split ";" | Where-Object { $_ })
        if ($graphvizBin -notin $userParts) {
            [Environment]::SetEnvironmentVariable("Path", (($userParts + $graphvizBin) -join ";"), "User")
        }
        $env:Path = "$env:Path;$graphvizBin"
    }
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

$java = Get-Command java -ErrorAction SilentlyContinue
if (-not $java) { throw "Java was installed but java.exe was not found on PATH." }

$jar = Join-Path $projectRoot "mdflow\resources\vendor\plantuml\plantuml.jar"
$smokeSource = "@startuml`nAlice -> Bob: MdFlow setup test`n@enduml`n"
$javaArgs = @("-Djava.awt.headless=true", "-jar", $jar, "-pipe", "-tsvg", "-charset", "UTF-8")
$smokeSvg = $smokeSource | & $java.Source $javaArgs
if ($LASTEXITCODE -ne 0 -or ($smokeSvg -join "`n") -notmatch "<svg") {
    throw "PlantUML rendering verification failed."
}

& $java.Source -version
$dot = Get-Command dot -ErrorAction SilentlyContinue
if ($dot) { & $dot.Source -V } else { Write-Warning "Graphviz dot.exe was not found on PATH." }

Write-Host ""
Write-Host "[MdFlow] PlantUML setup completed."
Write-Host "Restart MdFlow so that it can use the installed environment."
