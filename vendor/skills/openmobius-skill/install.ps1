#!/usr/bin/env pwsh
# Thin wrapper for install.py — Windows PowerShell.
$ErrorActionPreference = 'Stop'
$DIR = Split-Path -Parent $MyInvocation.MyCommand.Path

# Prefer 'py -3' (Python launcher); fallback to 'python'
$pyCmd = $null
foreach ($cand in @('py', 'python', 'python3')) {
    if (Get-Command $cand -ErrorAction SilentlyContinue) {
        $pyCmd = $cand
        break
    }
}

if (-not $pyCmd) {
    Write-Host "Error: Python 3.10+ not found. Install from:" -ForegroundColor Red
    Write-Host "  https://www.python.org/downloads/   (check 'Add Python to PATH')" -ForegroundColor Yellow
    exit 1
}

if ($pyCmd -eq 'py') {
    & py -3 "$DIR\install.py" @args
} else {
    & $pyCmd "$DIR\install.py" @args
}
exit $LASTEXITCODE
