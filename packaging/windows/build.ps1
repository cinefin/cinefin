<#
Build the Cinefin Windows installer end-to-end. Run on Windows from the repo
root (or anywhere — paths are resolved relative to this script).

Prerequisites:
  - Python 3.13 + Poetry            (backend deps)
  - Node 20+                        (SPA build)
  - Inno Setup 6 (iscc on PATH)     (GUI installer)   https://jrsoftware.org/isdl.php
  - Internet access                 (downloads a static ffmpeg once)

Usage:
  pwsh packaging/windows/build.ps1                 # version from backend/pyproject
  pwsh packaging/windows/build.ps1 -Version 0.36.0
#>
[CmdletBinding()]
param([string]$Version = "")

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Resolve-Path (Join-Path $here "..\..")
$backend = Join-Path $repo "backend"
$frontend = Join-Path $repo "frontend"

if (-not $Version) {
    $m = Select-String -Path (Join-Path $backend "pyproject.toml") -Pattern '^version\s*=\s*"(.+)"'
    $Version = if ($m) { $m.Matches[0].Groups[1].Value } else { "0.0.0" }
}
Write-Host "==> Building Cinefin $Version" -ForegroundColor Cyan

# 1. SPA build -------------------------------------------------------------
Write-Host "==> Building the SPA" -ForegroundColor Cyan
Push-Location $frontend
npm ci
npm run build
Pop-Location

# 2. Backend deps + build tools -------------------------------------------
Write-Host "==> Installing backend + build deps" -ForegroundColor Cyan
Push-Location $backend
poetry install --only main
poetry run pip install pyinstaller pystray
# collectstatic populates cinefin/staticfiles (bundled + served by WhiteNoise)
poetry run python manage.py collectstatic --no-input --clear
Pop-Location

# 3. ffmpeg (static win64) -------------------------------------------------
$ffdir = Join-Path $here "ffmpeg"
if (-not (Test-Path (Join-Path $ffdir "ffmpeg.exe"))) {
    Write-Host "==> Fetching static ffmpeg" -ForegroundColor Cyan
    New-Item -ItemType Directory -Force -Path $ffdir | Out-Null
    $zip = Join-Path $env:TEMP "ffmpeg-win64.zip"
    $url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
    Invoke-WebRequest -Uri $url -OutFile $zip
    $tmp = Join-Path $env:TEMP "ffmpeg-extract"
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    Expand-Archive -Path $zip -DestinationPath $tmp
    Get-ChildItem -Path $tmp -Recurse -Include ffmpeg.exe, ffprobe.exe | ForEach-Object {
        Copy-Item $_.FullName -Destination $ffdir -Force
    }
}

# 4. Icon (from logo.png, if present) -------------------------------------
$ico = Join-Path $here "cinefin.ico"
$logo = Join-Path $repo "logo.png"
if ((-not (Test-Path $ico)) -and (Test-Path $logo)) {
    Write-Host "==> Generating icon" -ForegroundColor Cyan
    Push-Location $backend
    poetry run python -c "from PIL import Image; Image.open(r'$logo').save(r'$ico', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])"
    Pop-Location
}

# 5. PyInstaller freeze ----------------------------------------------------
Write-Host "==> Freezing with PyInstaller" -ForegroundColor Cyan
Push-Location $backend
poetry run pyinstaller (Join-Path $here "cinefin.spec") `
    --noconfirm `
    --distpath (Join-Path $here "dist") `
    --workpath (Join-Path $here "build")
Pop-Location

# 6. Inno Setup installer --------------------------------------------------
Write-Host "==> Building installer with Inno Setup" -ForegroundColor Cyan
iscc "/DAppVersion=$Version" (Join-Path $here "installer.iss")

Write-Host "==> Done. Installer in $(Join-Path $here 'Output')" -ForegroundColor Green
