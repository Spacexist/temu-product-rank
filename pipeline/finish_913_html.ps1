$ErrorActionPreference = "Stop"
$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ROOT
$PY = "F:\Clip\venv\Scripts\python.exe"
$env:TEMP = "D:\temu_tmp"
$env:TMP = "D:\temu_tmp"
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
& $PY rank_products.py --stage download --skip-download
& $PY rank_products.py --stage embed
& $PY rank_products.py --stage train
& $PY validate_temporal.py --preset 913
& $PY export_bundle.py
$src = Join-Path $ROOT "_screener_bundle\model"
$dst = Join-Path $ROOT "_screener_pkg\model"
Copy-Item -Path (Join-Path $src "*") -Destination $dst -Force
$html = Join-Path $ROOT "artifacts_v2\时间外推验证报告_913.html"
& $PY build_temporal_validation_html.py --metrics (Join-Path $ROOT "artifacts_v2\temporal_metrics_913.json") --out $html
Copy-Item -LiteralPath $html -Destination "D:\时间外推验证_909-912训913.html" -Force
Write-Host "HTML D:\时间外推验证_909-912训913.html"
