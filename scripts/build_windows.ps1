# Build the Windows installer locally -- the same steps GitHub Actions runs.
# Needs Python 3.10+ and Inno Setup 6 (https://jrsoftware.org/isdl.php).
#
#   powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1 -Version 0.1.0

param([string]$Version = "0.0.0-dev")
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

python -m venv .buildenv
.\.buildenv\Scripts\python -m pip install --upgrade pip
.\.buildenv\Scripts\pip install -r requirements.txt pyinstaller
.\.buildenv\Scripts\pip install -e .

.\.buildenv\Scripts\pyinstaller installer\recruiting_desk.spec --noconfirm --distpath dist --workpath build

$iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) { throw "Inno Setup 6 not found. Install it from https://jrsoftware.org/isdl.php" }
& $iscc "/DAppVersion=$Version" installer\recruiting_desk.iss

Write-Host ""
Write-Host "Installer: dist\RecruitingDesk-Setup-$Version.exe"
