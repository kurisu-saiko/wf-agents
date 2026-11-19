param(
  [ValidateSet("antigravity", "claude", "cursor", "codex", "gemini", "opencode", "generic")]
  [string]$HostName = "antigravity",
  [string]$Target = "",
  [string]$ConfigDir = "",
  [switch]$Apply
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = (Get-Command python).Source

$argList = @("$Root/host/install.py", "--host", $HostName)
if ($Target) { $argList += @("--target", $Target) }
if ($ConfigDir) { $argList += @("--config-dir", $ConfigDir) }
if ($Apply) { $argList += "--apply" }

& $python @argList
exit $LASTEXITCODE
