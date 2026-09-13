# Install the `beastfly` launcher onto your PATH. Windows counterpart of
# install.sh - it writes one .cmd shim that points back at this folder.
#
#   powershell -ExecutionPolicy Bypass -File .\install.ps1
#
$ErrorActionPreference = "Stop"

$SrcDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not (Test-Path (Join-Path $SrcDir "beastfly"))) {
    Write-Error "install.ps1: run this from the Beastfly source folder."
}

# `py` is the launcher the python.org installer adds; `python` is what the
# Microsoft Store build and most PATH setups provide.
$Python = $null
foreach ($candidate in @("py", "python", "python3")) {
    $found = Get-Command $candidate -ErrorAction SilentlyContinue
    if (-not $found) { continue }
    $version = & $candidate -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
    if ($LASTEXITCODE -eq 0 -and [version]$version -ge [version]"3.8") {
        $Python = $candidate
        break
    }
}
if (-not $Python) {
    Write-Error "beastfly needs Python 3.8 or newer. Install it from https://www.python.org/downloads/ and reopen this window."
}

$BinDir = if ($env:BIN_DIR) { $env:BIN_DIR } else { Join-Path $env:LOCALAPPDATA "Programs\beastfly" }
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
$Target = Join-Path $BinDir "beastfly.cmd"

@"
@echo off
rem beastfly - Hollow Knight: Silksong mod manager
if "%BEASTFLY_DIR%"=="" set "BEASTFLY_DIR=$SrcDir"
if not exist "%BEASTFLY_DIR%\beastfly" (
  echo beastfly: source not found at %BEASTFLY_DIR% 1>&2
  echo           set BEASTFLY_DIR to the folder containing the beastfly\ package. 1>&2
  exit /b 1
)
set "PYTHONPATH=%BEASTFLY_DIR%;%PYTHONPATH%"
$Python -m beastfly %*
"@ | Set-Content -Path $Target -Encoding ASCII

Write-Host "Installed $Target"

# Put the shim on PATH for future terminals, without disturbing what's there.
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -split ";" -notcontains $BinDir) {
    $joined = if ([string]::IsNullOrEmpty($userPath)) { $BinDir } else { "$userPath;$BinDir" }
    [Environment]::SetEnvironmentVariable("Path", $joined, "User")
    Write-Host "Added $BinDir to your PATH. Open a new terminal, then run: beastfly"
} else {
    Write-Host "Run: beastfly"
}
