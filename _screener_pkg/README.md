# 选品筛子

1. 把新的日报表丢进来（xlsx，后缀叫 csv 也行）
2. 运行：

```powershell
cd C:\Users\ZFGJ-WCH\Desktop\选品筛子
$env:HF_HOME = "F:\Clip\hf-cache"
$env:HF_HUB_OFFLINE = "1"
F:\Clip\venv\Scripts\python.exe src\run.py --input "路径"
```

3. 打开 `output\` 里的 HTML，用价格框和「前 5%」筛
4. 主图拉不到的、标了违禁的，默认先别上架

自测（911，`--skip-download`）：违禁命中 **1740/10000**；与 `test_scores.npz` 交集 Spearman **1.00**（需 `config.json` 指向实验场 `artifacts_v2` 向量缓存）。

```powershell
F:\Clip\venv\Scripts\python.exe src\run.py --input "..\8天前数据\911.csv" --skip-download --self-test
```

同步到桌面目录：在实验场运行 `python bootstrap_screener.py`。
