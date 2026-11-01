param(
  [ValidateSet("haha", "claude", "dsh")]
  [string]$HostName = "haha",
  [string]$ConfigDir = "",
  [switch]$Apply
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = (Get-Command python).Source

$argList = @("$Root/host/install.py", "--host", $HostName)
if ($ConfigDir) { $argList += @("--config-dir", $ConfigDir) }
if ($Apply) { $argList += "--apply" }

& $python @argList
exit $LASTEXITCODE
