# Production-style serve on Windows (Waitress). Listens on 0.0.0.0:5009 by default.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if (-not (Test-Path .\.venv\Scripts\Activate.ps1)) {
    Write-Error "Run scripts\install-windows.ps1 first."
}

& .\.venv\Scripts\Activate.ps1

if (Test-Path .\.env) {
    Get-Content .\.env | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            return
        }

        $parts = $line -split '=', 2
        if ($parts.Count -ne 2) {
            return
        }

        $name = $parts[0].Trim()
        $value = $parts[1].Trim()

        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }

        if (-not (Test-Path "env:$name")) {
            Set-Item -Path "env:$name" -Value $value
        }
    }
}

$HostAddr = if ($env:BIND_HOST) { $env:BIND_HOST } else { "0.0.0.0" }
$Port = if ($env:PORT) { $env:PORT } else { "5009" }
$Listen = "${HostAddr}:${Port}"

Write-Host "Serving on http://${Listen}"
python -m waitress --listen=$Listen app:app
