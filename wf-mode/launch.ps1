param(
  [Parameter(Position=0, ValueFromRemainingArguments=$true)]
  [string[]]$TaskParts
)

$ErrorActionPreference = 'Stop'
$task = ($TaskParts -join ' ').Trim()
if ([string]::IsNullOrWhiteSpace($task) -or $task -match '^(<\s*>|__TASK__|<TASK>)$') {
  Write-Output 'wf: task text is required.'
  exit 1
}

$wfRoot = 'D:/claude-code/workflow/wf-mode'
$sidecar = 'D:/claude-code/gui/Claude Code Haha/resources/app.asar.unpacked/src-tauri/binaries/claude-sidecar-x86_64-pc-windows-msvc.exe'

# 每次运行一个独立账本目录，按对话/任务分类；固定三个文件由管线写入。
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$slug = ($task.ToLower() -replace '[^a-z0-9]+', '-').Trim('-')
if ($slug.Length -gt 24) { $slug = $slug.Substring(0, 24) }
if ([string]::IsNullOrWhiteSpace($slug)) { $slug = 'task' }
$runDir = Join-Path (Get-Location).Path ".wf/runs/$stamp-$slug"
New-Item -ItemType Directory -Force -Path $runDir | Out-Null
$runDir = ($runDir -replace '\\', '/')

$payload = @{ task = $task; runDir = $runDir } | ConvertTo-Json -Compress

$mode = 'wf-research'
if ($task -match '^@?(wf-retrieval|wf-project-eval|wf-project-reading)') {
  $mode = 'wf-exempt'
}

$prompt = "Use the Workflow tool to run the saved workflow $mode. Pass the following string verbatim as args:`n$payload`nReturn only the workflow result. Do nothing else."

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $sidecar
$psi.Arguments = 'cli -p --permission-mode bypassPermissions --output-format stream-json --verbose --max-budget-usd 1.5'
$psi.UseShellExecute = $false
$psi.RedirectStandardInput = $true
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.CreateNoWindow = $true
$psi.WorkingDirectory = (Get-Location).Path
$psi.StandardOutputEncoding = New-Object System.Text.UTF8Encoding($false)
$psi.StandardErrorEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:CLAUDE_CONFIG_DIR = $wfRoot

$proc = [System.Diagnostics.Process]::Start($psi)
$bytes = [System.Text.Encoding]::UTF8.GetBytes($prompt)
$proc.StandardInput.BaseStream.Write($bytes, 0, $bytes.Length)
$proc.StandardInput.BaseStream.Flush()
$proc.StandardInput.Close()
$out = $proc.StandardOutput.ReadToEnd()
$null = $proc.StandardError.ReadToEnd()
$proc.WaitForExit()

if (-not $out) {
  Write-Output 'wf: workflow returned no result.'
  exit 1
}

$tag2 = [guid]::NewGuid().ToString('N')
$sf = Join-Path ([IO.Path]::GetTempPath()) ("wf_stream_$tag2.jsonl")
[IO.File]::WriteAllText($sf, $out, (New-Object System.Text.UTF8Encoding($false)))
$extract = Join-Path $wfRoot 'extract_result.py'
$resultText = & python $extract $sf
Remove-Item $sf -ErrorAction SilentlyContinue
if ($resultText) { Write-Output $resultText } else { Write-Output 'wf: workflow returned no result.'; exit 1 }
