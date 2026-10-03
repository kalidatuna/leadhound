# leadhound installer for Windows. Run in PowerShell:
#   irm https://raw.githubusercontent.com/kalidatuna/leadhound/main/install.ps1 | iex
#
# What it does: finds Python 3.10+ (offers to install it with winget if missing), creates a private
# environment in %USERPROFILE%\.leadhound\app, installs leadhound there, adds the `leadhound` command
# and a desktop icon, then opens the app. No admin rights are needed.
# Options (environment variables): LEADHOUND_HOME, LEADHOUND_NO_START=1, LEADHOUND_SOURCE (pip spec or folder).
$ErrorActionPreference = "Stop"

$AppHome = if ($env:LEADHOUND_HOME) { $env:LEADHOUND_HOME } else { Join-Path $env:USERPROFILE ".leadhound" }
$Venv = Join-Path $AppHome "app"
$BinDir = Join-Path $AppHome "bin"
$Src = if ($env:LEADHOUND_SOURCE) { $env:LEADHOUND_SOURCE } else { "https://github.com/kalidatuna/leadhound/archive/refs/heads/main.zip" }
$Releases = "https://github.com/kalidatuna/leadhound/releases/latest"

function Test-Python([string[]]$cmd) {
    try {
        $exe = $cmd[0]
        $rest = @()
        if ($cmd.Length -gt 1) { $rest = $cmd[1..($cmd.Length - 1)] }
        & $exe @rest -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

function Find-Python {
    $candidates = @(@("py", "-3"), @("python"), @("python3"))
    foreach ($v in "313", "312", "311", "310") {
        $candidates += , @((Join-Path $env:LOCALAPPDATA "Programs\Python\Python$v\python.exe"))
    }
    foreach ($c in $candidates) {
        if ((Get-Command $c[0] -ErrorAction SilentlyContinue) -or (Test-Path $c[0])) {
            if (Test-Python $c) { return , $c }
        }
    }
    return $null
}

$py = Find-Python
if (-not $py) {
    Write-Host "leadhound needs Python 3.10 or newer, and none was found."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        $answer = Read-Host "Install Python 3.12 now with winget? [Y/n]"
        if ($answer -eq "" -or $answer -match "^[Yy]") {
            winget install -e --id Python.Python.3.12 --scope user
            $py = Find-Python
        }
    }
    if (-not $py) {
        Write-Host "Install Python from https://www.python.org/downloads/ (tick 'Add to PATH'),"
        Write-Host "or download the ready-made app instead: $Releases"
        exit 1
    }
}
$pyExe = $py[0]
$pyArgs = @()
if ($py.Length -gt 1) { $pyArgs = $py[1..($py.Length - 1)] }
Write-Host ("Using " + (& $pyExe @pyArgs --version))

New-Item -ItemType Directory -Force -Path $AppHome, $BinDir | Out-Null
& $pyExe @pyArgs -m venv $Venv
if ($LASTEXITCODE -ne 0) { Write-Host "Could not create the Python environment."; exit 1 }
$venvPy = Join-Path $Venv "Scripts\python.exe"

Write-Host "Installing leadhound (about 30 seconds)..."
& $venvPy -m pip install --quiet --disable-pip-version-check --upgrade $Src
if ($LASTEXITCODE -ne 0) {
    Write-Host "Download failed. Check your internet connection and run the installer again."
    exit 1
}

# A small launcher in its own folder, so only `leadhound` (not python.exe) goes on PATH
$lh = Join-Path $Venv "Scripts\leadhound.exe"
Set-Content -Path (Join-Path $BinDir "leadhound.cmd") -Value "@echo off`r`n`"$lh`" %*" -Encoding ASCII
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not $userPath) { $userPath = "" }
if (-not ($userPath.Split(";") -contains $BinDir)) {
    [Environment]::SetEnvironmentVariable("Path", ($userPath.TrimEnd(";") + ";" + $BinDir).TrimStart(";"), "User")
}
& $lh shortcut | Out-Null
if ($LASTEXITCODE -eq 0) { Write-Host "Desktop icon created." }

Write-Host ""
Write-Host ("leadhound " + ((& $lh --version) -split " ")[1] + " is installed.")
Write-Host "Open it any time with the desktop icon, or type 'leadhound' in a new terminal."
if (-not $env:LEADHOUND_NO_START) {
    Write-Host "Opening leadhound in your browser now. Close this window to stop it."
    & $lh
}
