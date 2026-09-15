$ErrorActionPreference = "Stop"
$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ROOT
$PY = "F:\Clip\venv\Scripts\python.exe"
& $PY rank_products.py --stage embed
& $PY rank_products.py --stage train
& $PY rank_products.py --stage eval --repeats 500
& $PY validate_temporal.py --preset 913
& $PY export_bundle.py
Write-Host "DONE retrain_through_913"
