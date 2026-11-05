# SPDX-License-Identifier: Apache-2.0
# Start Stretto and open it in your browser. Stop with Ctrl-C.
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$data = if ($env:STRETTO_DATA) { $env:STRETTO_DATA } else { Join-Path $env:USERPROFILE '.stretto' }
$port = if ($env:STRETTO_PORT) { $env:STRETTO_PORT } else { '8760' }
$py = $null
foreach ($cand in @(@('py','-3'), @('python'), @('python3'))) {
  if (Get-Command $cand[0] -ErrorAction SilentlyContinue) { $py = $cand; break }
}
if (-not $py) { Write-Host 'Python 3.8+ not found.'; exit 1 }
$rest = @(); if ($py.Count -gt 1) { $rest = $py[1..($py.Count - 1)] }
Set-Location $here
Start-Job -ScriptBlock { param($p) Start-Sleep 2; Start-Process "http://127.0.0.1:$p" } -ArgumentList $port | Out-Null
& $py[0] @rest -m stretto --data $data --port $port
