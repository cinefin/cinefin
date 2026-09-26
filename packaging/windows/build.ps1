<#
Assemble the Cinefin Windows package WITHOUT freezing: a relocatable Python
(python-build-standalone) with the cinefin wheel pip-installed into it, plus
ffmpeg and the tray, wrapped by Inno Setup. Because it's a real Python env,
every data file / native lib / dynamic import resolves normally — no PyInstaller
spec, no hidden-imports.

Inputs:
  -Wheel    path to cinefin3-*.whl (built by packaging/pip/build-wheel.sh / the
            `wheel` CI job). Required.
  -Version  installer version (default: from backend/pyproject.toml).

Prereqs: Inno Setup 6 (iscc on PATH), tar (built into Windows 10+), internet.

Usage (local):
  bash packaging/pip/build-wheel.sh                       # -> backend/dist/*.whl
  pwsh packaging/windows/build.ps1 -Wheel backend/dist/cinefin3-0.36.0-py3-none-any.whl
#>
[CmdletBinding()]
param([string]$Wheel = "", [string]$Version = "")

$ErrorActionPreference = "Stop"
function Invoke-Checked { param([scriptblock]$Cmd, [string]$What) & $Cmd; if ($LASTEXITCODE -ne 0) { throw "$What failed (exit $LASTEXITCODE)" } }

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Resolve-Path (Join-Path $here "..\..")

if (-not $Wheel) { throw "-Wheel is required (build it: bash packaging/pip/build-wheel.sh)" }
$Wheel = (Resolve-Path $Wheel).Path
if (-not $Version) {
    $m = Select-String -Path (Join-Path $repo "backend\pyproject.toml") -Pattern '^version\s*=\s*"(.+)"'
    $Version = if ($m) { $m.Matches[0].Groups[1].Value } else { "0.0.0" }
}
Write-Host "==> Packaging Cinefin $Version from $Wheel" -ForegroundColor Cyan

$stage = Join-Path $here "stage"
Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $stage | Out-Null

# 1. Relocatable Python (python-build-standalone, latest install_only) ------
Write-Host "==> Fetching a relocatable Python" -ForegroundColor Cyan
$rel = Invoke-RestMethod "https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest"
$asset = $rel.assets |
    Where-Object { $_.name -match 'cpython-3\.13\.\d+\+.*-x86_64-pc-windows-msvc-install_only\.tar\.gz$' } |
    Select-Object -First 1
if (-not $asset) { throw "no cpython-3.13 windows install_only asset found" }
$pytar = Join-Path $env:TEMP "cpython.tar.gz"
Invoke-WebRequest $asset.browser_download_url -OutFile $pytar
tar -xzf $pytar -C $stage          # -> $stage\python\
$py = Join-Path $stage "python\python.exe"

# 2. Install cinefin + the tray dep into it --------------------------------
Write-Host "==> Installing the wheel" -ForegroundColor Cyan
Invoke-Checked { & $py -m pip install --no-input --no-warn-script-location $Wheel pystray } "pip install"

# 3. ffmpeg (static win64) -------------------------------------------------
Write-Host "==> Fetching static ffmpeg" -ForegroundColor Cyan
$ffdir = Join-Path $stage "ffmpeg"
New-Item -ItemType Directory -Force -Path $ffdir | Out-Null
$ffzip = Join-Path $env:TEMP "ffmpeg-win64.zip"
Invoke-WebRequest "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip" -OutFile $ffzip
$fftmp = Join-Path $env:TEMP "ffmpeg-extract"
Remove-Item -Recurse -Force $fftmp -ErrorAction SilentlyContinue
Expand-Archive -Path $ffzip -DestinationPath $fftmp
Get-ChildItem -Path $fftmp -Recurse -Include ffmpeg.exe, ffprobe.exe | ForEach-Object { Copy-Item $_.FullName $ffdir -Force }

# 4. Tray + icon -----------------------------------------------------------
Copy-Item (Join-Path $here "tray.py") $stage
$mark = Join-Path $here "cinefin-mark-light.png"    # the Cinefin brand mark
if (Test-Path $mark) {
    & $py (Join-Path $here "make_icon.py") $mark (Join-Path $stage "cinefin.ico")
}

# 5. Installer -------------------------------------------------------------
Write-Host "==> Building installer with Inno Setup" -ForegroundColor Cyan
Invoke-Checked { iscc "/DAppVersion=$Version" "/DStageDir=$stage" (Join-Path $here "installer.iss") } "Inno Setup"

Write-Host "==> Done. Installer in $(Join-Path $here 'Output')" -ForegroundColor Green
