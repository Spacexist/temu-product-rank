param(
  [string]$Today = "",
  [string]$FromStage = "ingest",
  [switch]$SkipTrain,
  [switch]$HtmlOnly,
  [switch]$DryRun,
  [switch]$WithEval
)

$ErrorActionPreference = "Stop"
$env:HF_HOME = "F:\Clip\hf-cache"
$env:HF_HUB_OFFLINE = "1"
$env:OMP_NUM_THREADS = "1"
$env:PYTHONIOENCODING = "utf-8"

$Root = Split-Path -Parent $PSScriptRoot
$Python = "F:\Clip\venv\Scripts\python.exe"
$Script = Join-Path $PSScriptRoot "daily_pipeline.py"

$ArgsList = @()
if ($Today) { $ArgsList += @("--today", $Today) }
if ($FromStage -and $FromStage -ne "ingest") { $ArgsList += @("--from-stage", $FromStage) }
if ($SkipTrain) { $ArgsList += "--skip-train" }
if ($HtmlOnly) { $ArgsList += "--html-only" }
if ($DryRun) { $ArgsList += "--dry-run" }
if ($WithEval) { $ArgsList += "--with-eval" }

& $Python $Script @ArgsList
exit $LASTEXITCODE
