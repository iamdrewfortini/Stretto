# Stretto: install and start on Windows. Plain Python 3.8+, no packages to download, no administrator rights.
#   .\install.ps1              set up and start
#   .\install.ps1 -NoStart     set up only
param([switch]$NoStart)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$data = if ($env:STRETTO_DATA) { $env:STRETTO_DATA } else { Join-Path $env:USERPROFILE '.stretto' }
$py = $null
foreach ($cand in @(@('py','-3'), @('python'), @('python3'))) {
  if (Get-Command $cand[0] -ErrorAction SilentlyContinue) {
    $rest = @(); if ($cand.Count -gt 1) { $rest = $cand[1..($cand.Count - 1)] }
    $ok = & $cand[0] @rest -c "import sys; print(int(sys.version_info >= (3, 8)))" 2>$null
    if ($ok -eq '1') { $py = $cand; break }
  }
}
if (-not $py) { Write-Host 'Python 3.8 or newer is required. Install it with:  winget install Python.Python.3.12   then run this again.'; exit 1 }
New-Item -ItemType Directory -Force $data | Out-Null
$envFile = Join-Path $data '.env'
if (-not (Test-Path $envFile)) {
  Copy-Item (Join-Path $here '.env.example') $envFile
  Write-Host "Created $envFile  <- put your Meta Model API key after MODEL_API_KEY= (it stays on this computer)"
}
Set-Location $here
$rest = @(); if ($py.Count -gt 1) { $rest = $py[1..($py.Count - 1)] }
& $py[0] @rest -m stretto doctor --data $data
if ($NoStart) { Write-Host 'Set up. Start later with:  .\run.ps1'; return }
& (Join-Path $here 'run.ps1')
