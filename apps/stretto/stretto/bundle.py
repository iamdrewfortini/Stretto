"""Builds the agent download for the UI's 'Install agent' button. Pure standard library.

The zip holds the agent's source (so you can read it), an installer for the chosen OS, and agent.json with the server address and a
single-use enrolment code. It never contains the server's master token. Installing does not start recording: the server refuses
all data until a person accepts the notice in Stretto."""
import glob
import io
import json
import os
import zipfile

TARGETS = {"windows", "linux", "macos"}
AGENT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent", "stretto_agent")

README = """Stretto agent
=============
This folder installs the Stretto tracking agent on THIS computer. Read install.{ext} first; it is short.

What installing does
  - copies the agent (plain Python, source included) into your user profile
  - exchanges the one-time code in agent.json for a key that belongs to this computer only
  - starts the agent when you sign in
What installing does NOT do
  - it does not record anything. The Stretto server refuses all data until a person accepts the notices in the Stretto app.
  - it needs no administrator rights and no network access except to your Stretto server.
Uninstall:  {uninstall}
"""

INSTALL_PS1 = r'''# Stretto agent installer for Windows. Review it before running. No administrator rights are needed.
#   .\install.ps1              install and start
#   .\install.ps1 -Uninstall   remove the agent (your data on the Stretto server is untouched)
param([switch]$Uninstall)
$ErrorActionPreference = 'Stop'
$app  = Join-Path $env:LOCALAPPDATA 'StrettoAgent'
$task = 'StrettoAgent'
if ($Uninstall) {
  schtasks /End /TN $task 2>$null | Out-Null
  schtasks /Delete /TN $task /F 2>$null | Out-Null
  if (Test-Path $app) { Remove-Item $app -Recurse -Force }
  Write-Host 'Stretto agent removed.'
  return
}
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$cfg  = Get-Content (Join-Path $here 'agent.json') -Raw | ConvertFrom-Json
$pyExe = $null
foreach ($cand in @(@('py','-3'), @('python'), @('python3'))) {
  if (Get-Command $cand[0] -ErrorAction SilentlyContinue) {
    $rest = @(); if ($cand.Count -gt 1) { $rest = $cand[1..($cand.Count - 1)] }
    $ok = & $cand[0] @rest -c "import sys; print(int(sys.version_info >= (3, 8)))" 2>$null
    if ($ok -eq '1') { $pyExe = (& $cand[0] @rest -c "import sys; print(sys.executable)").Trim(); break }
  }
}
if (-not $pyExe) { Write-Host 'Python 3.8 or newer is required. Install it with:  winget install Python.Python.3.12   then run this again.'; exit 1 }
New-Item -ItemType Directory -Force (Join-Path $app 'app') | Out-Null
Copy-Item (Join-Path $here 'agent\*') (Join-Path $app 'app') -Recurse -Force
$runner = Join-Path $app 'run-agent.pyw'
Set-Content -Encoding ascii $runner ("import sys`nsys.path.insert(0, r'" + (Join-Path $app 'app') + "')`nfrom stretto_agent import cli`ncli.main(sys.argv[1:] or ['run'])`n")
$env:STRETTO_ENROLL = '1'
& $pyExe $runner --server $cfg.server enroll $cfg.enroll_code
if ($LASTEXITCODE -ne 0) { Write-Host 'Enrolment failed. The code may have expired (15 minutes); download the installer again from Stretto.'; exit 1 }
$pyw = Join-Path (Split-Path $pyExe) 'pythonw.exe'
if (-not (Test-Path $pyw)) { $pyw = $pyExe }
Set-Content -Encoding ascii (Join-Path $app 'stretto-agent.cmd') ('@echo off' + "`r`n" + '"' + $pyExe + '" "' + $runner + '" %*' + "`r`n")
schtasks /Create /TN $task /SC ONLOGON /TR ('"' + $pyw + '" "' + $runner + '"') /RL LIMITED /F | Out-Null
schtasks /Run /TN $task | Out-Null
Write-Host ''
Write-Host 'Stretto agent installed and running.'
Write-Host 'It records NOTHING until you accept the notices in the Stretto app (Settings > Data sources).'
Write-Host ('Command line: ' + (Join-Path $app 'stretto-agent.cmd') + ' status')
'''

INSTALL_SH = r'''#!/bin/sh
# Stretto agent installer for macOS and Linux. Review it before running. No root needed.
#   ./install.sh              install and start
#   ./install.sh --uninstall  remove the agent (your data on the Stretto server is untouched)
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
case "$(uname -s)" in
  Darwin) APP="$HOME/Library/Application Support/StrettoAgent"; PLIST="$HOME/Library/LaunchAgents/com.stretto.agent.plist" ;;
  *)      APP="${XDG_CONFIG_HOME:-$HOME/.config}/stretto-agent"; UNIT="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/stretto-agent.service" ;;
esac
if [ "${1:-}" = "--uninstall" ]; then
  if [ "$(uname -s)" = "Darwin" ]; then launchctl unload "$PLIST" 2>/dev/null || true; rm -f "$PLIST"
  else systemctl --user disable --now stretto-agent 2>/dev/null || true; rm -f "$UNIT"; fi
  rm -rf "$APP"; echo "Stretto agent removed."; exit 0
fi
PY=$(command -v python3 || true)
if [ -z "$PY" ] || ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)'; then
  echo "Python 3.8 or newer is required (python3 not found or too old)."; exit 1
fi
SERVER=$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["server"])' "$HERE/agent.json")
CODE=$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["enroll_code"])' "$HERE/agent.json")
mkdir -p "$APP/app"
cp -R "$HERE/agent/." "$APP/app/"
cat > "$APP/run-agent.py" <<PYEOF
import sys
sys.path.insert(0, "$APP/app")
from stretto_agent import cli
cli.main(sys.argv[1:] or ["run"])
PYEOF
if ! "$PY" "$APP/run-agent.py" --server "$SERVER" enroll "$CODE"; then
  echo "Enrolment failed. The code may have expired (15 minutes); download the installer again from Stretto."; exit 1
fi
if [ "$(uname -s)" = "Darwin" ]; then
  mkdir -p "$HOME/Library/LaunchAgents"
  cat > "$PLIST" <<PLEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.stretto.agent</string>
<key>ProgramArguments</key><array><string>$PY</string><string>$APP/run-agent.py</string></array>
<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
</dict></plist>
PLEOF
  launchctl unload "$PLIST" 2>/dev/null || true
  launchctl load -w "$PLIST"
else
  mkdir -p "$(dirname "$UNIT")"
  cat > "$UNIT" <<UNEOF
[Unit]
Description=Stretto agent
[Service]
ExecStart=$PY $APP/run-agent.py
Restart=on-failure
[Install]
WantedBy=default.target
UNEOF
  systemctl --user daemon-reload
  systemctl --user enable --now stretto-agent
fi
echo
echo "Stretto agent installed and running."
echo "It records NOTHING until you accept the notices in the Stretto app (Settings > Data sources)."
echo "Command line: $PY $APP/run-agent.py status"
'''


def _agent_files():
    root = os.path.abspath(AGENT_DIR)
    files = sorted(p for p in glob.glob(os.path.join(root, "*.py")))
    if not files:
        raise ValueError("agent sources were not found next to the server")
    return files


def build(os_name, server, code):
    """Returns (zip bytes, filename)."""
    if os_name not in TARGETS:
        raise ValueError("unknown os")
    buf = io.BytesIO()
    top = "stretto-agent"
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in _agent_files():
            z.write(p, f"{top}/agent/stretto_agent/{os.path.basename(p)}")
        z.writestr(f"{top}/agent.json", json.dumps(dict(server=server, enroll_code=code, note="single use; expires 15 minutes after download"), indent=2))
        if os_name == "windows":
            z.writestr(f"{top}/install.ps1", INSTALL_PS1.replace("\n", "\r\n"))
            z.writestr(f"{top}/README.txt", README.format(ext="ps1", uninstall=r".\install.ps1 -Uninstall"))
        else:
            info = zipfile.ZipInfo(f"{top}/install.sh", date_time=(2026, 11, 4, 0, 0, 0))
            info.external_attr = 0o755 << 16
            info.create_system = 3                      # mark as Unix so the permission bits survive no matter where the zip was built
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, INSTALL_SH)
            z.writestr(f"{top}/README.txt", README.format(ext="sh", uninstall="sh install.sh --uninstall") + "\nInstall:  sh install.sh\n")
    return buf.getvalue(), f"stretto-agent-{os_name}.zip"
