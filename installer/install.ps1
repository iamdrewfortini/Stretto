# SPDX-License-Identifier: Apache-2.0
# metacoh installer (Windows, PowerShell 5.1+). STATUS: UNTESTED - written to mirror install.sh; run `-VerifyOnly` first.
# Python wheels only (the native Rust libraries are built for Linux x86_64 in this release).
[CmdletBinding()]
param([string]$Prefix = "$env:LOCALAPPDATA\metacoh", [string]$Python = "py", [switch]$VerifyOnly, [switch]$Uninstall)
$ErrorActionPreference = "Stop"
$Bundle = Split-Path -Parent $PSScriptRoot
$Receipt = Join-Path $Prefix "share\metacoh\receipt.json"
if ($Uninstall) {
  if (-not (Test-Path $Receipt)) { throw "no receipt at $Receipt; refusing to remove anything" }
  $r = Get-Content $Receipt | ConvertFrom-Json
  Remove-Item -Recurse -Force $r.venv -ErrorAction SilentlyContinue; Remove-Item -Force $Receipt
  Write-Host "removed the virtualenv and receipt"; exit 0
}
# integrity: every line of SHA256SUMS is "<hash>  <relative path>"
$bad = 0
foreach ($line in Get-Content (Join-Path $Bundle "SHA256SUMS")) {
  $hash, $rel = $line -split "\s+", 2; $rel = $rel.TrimStart("*")
  $got = (Get-FileHash -Algorithm SHA256 (Join-Path $Bundle $rel)).Hash.ToLower()
  if ($got -ne $hash) { Write-Error "MISMATCH: $rel"; $bad++ }
}
if ($bad -gt 0) { throw "checksum verification FAILED for $bad file(s)" }
Write-Host "[metacoh-install] checksums OK"
if (Test-Path (Join-Path $Bundle "SHA256SUMS.sig")) { Write-Warning "bundle is signed; verify SHA256SUMS.sig with ssh-keygen -Y verify before trusting it (not automated on Windows)" }
if ($VerifyOnly) { exit 0 }
New-Item -ItemType Directory -Force (Join-Path $Prefix "share\metacoh") | Out-Null
& $Python -3 -m venv (Join-Path $Prefix "venv")
$py = Join-Path $Prefix "venv\Scripts\python.exe"
& $py -m pip install --quiet --no-index --find-links (Join-Path $Bundle "wheelhouse") --require-hashes -r (Join-Path $Bundle "wheelhouse\requirements.lock")
& (Join-Path $Prefix "venv\Scripts\metacoh.exe") doctor
if ($LASTEXITCODE -ne 0) { Remove-Item -Recurse -Force (Join-Path $Prefix "venv"); throw "doctor failed; rolled back" }
@{ name = "metacoh"; prefix = $Prefix; venv = (Join-Path $Prefix "venv") } | ConvertTo-Json | Set-Content $Receipt
Write-Host "[metacoh-install] installed to $Prefix"
