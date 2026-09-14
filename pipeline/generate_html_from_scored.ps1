param(
  [Parameter(Mandatory = $true)]
  [string]$InputCsv,

  [double]$TopPct = 5.0
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = "F:\Clip\venv\Scripts\python.exe"
$Script = Join-Path $Root "screener\src\generate_html.py"

& $Python $Script --input $InputCsv --top-pct $TopPct
