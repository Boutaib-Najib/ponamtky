# Install news-classifier on Windows (PowerShell). From repo root:
#   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force
#   .\scripts\install-windows.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if (Get-Command py -ErrorAction SilentlyContinue) {
    py -3 -m venv .venv
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    python -m venv .venv
} else {
    Write-Error "Python 3.10+ required. Install from https://www.python.org/downloads/ (enable 'Add python.exe to PATH')."
}

& .\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -r requirements.txt

Write-Host "Installing Playwright Firefox..."
python -m playwright install firefox

Write-Host ""
Write-Host "Done. Next:"
Write-Host "  .\.venv\Scripts\Activate.ps1"
Write-Host "  set OPENAI_API_KEY using $env:OPENAI_API_KEY=<your_api_key_here>"
Write-Host "  set PROMPTS_PATH using $env:PROMPTS_PATH=<your_api_key_here>"
Write-Host "  .\scripts\run-windows.ps1"
