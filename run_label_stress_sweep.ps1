$ErrorActionPreference = "Stop"
$env:HF_HOME = "F:\Clip\hf-cache"
$env:HF_HUB_OFFLINE = "1"
$py = "F:\Clip\venv\Scripts\python.exe"
$root = "C:\Users\ZFGJ-WCH\Desktop\8天前数据"
$csv = "C:\Users\ZFGJ-WCH\Desktop\831-910\2097863420316155906.csv"
$art = Join-Path $root "artifacts_v2"
New-Item -ItemType Directory -Force -Path $art | Out-Null
$log = Join-Path $art "label_stress_sweep.log"

foreach ($p in 10, 30, 50, 80, 100) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $log -Value "=== pos-pct $p start $ts ==="
    & $py (Join-Path $root "score_external_one.py") --file $csv --pos-pct $p 2>&1 | Tee-Object -FilePath $log -Append
}
& $py (Join-Path $root "build_label_stress_html.py") 2>&1 | Tee-Object -FilePath $log -Append
Add-Content -Path $log -Value "=== sweep done $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ==="
