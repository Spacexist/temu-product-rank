# Datta

Temu 家居厨房用品选品排序筛子。模型只做同一批商品内部排序，每天看 Top 5%，不要设固定分数线。详细约定见 [docs/PIPELINE.md](docs/PIPELINE.md)。

## 一键日常

把当天日报丢进去。脚本会用 `data/raw/` 里除最新文件外的全部日报重训，再预测最新一天并生成 HTML。

```powershell
C:\Users\ZFGJ-WCH\Desktop\datta\pipeline\daily_pipeline.ps1 -Today C:\Users\ZFGJ-WCH\Downloads\917.csv
```

文件已经在 `data/raw/` 时可以省略 `-Today`。训练已在别处跑完时用 `-SkipTrain`；只重出 HTML 用 `-HtmlOnly`。先核对切分用 `-DryRun`。

## 当前状态

- 项目根目录：`C:\Users\ZFGJ-WCH\Desktop\datta`
- 可部署模型：`screener/model/lgbm_full.txt`（当前由 909-916 训出，用于 917 预测）
- 向量缓存：`D:\temu_rank_npz`；仓库里还有一份 `artifacts/embeddings/`
- 最新已完成预测：`screener/output/917_分享.html`
- `data/raw/` 已有 `909` 到 `917`；917 已按规矩使用 909-916 训练

| 预测日 | 训练集 | Top5 去违禁去 2D 后 |
|---|---|---:|
| 913 | 当时现有模型 | 203 |
| 914 | 909-913 | 262 |
| 915 | 909-914 | 284 |
| 916 | 909-915 | 248 |
| 917 | 909-916 | 232 |

## 目录

```text
datta/
├── data/raw/                # 原始日报；910 起后缀常是 csv，实际按 Excel 读
├── data/cleaned/            # 历史清洗候选池
├── pipeline/
│   ├── daily_pipeline.py    # 日常唯一入口
│   ├── rank_products.py     # 训练 prep/embed/train/eval
│   ├── export_bundle.py     # 导出 screener/model
│   └── generate_html_from_scored.ps1
├── screener/
│   ├── src/run.py           # 模型阶段，只出 scored CSV
│   ├── src/generate_html.py # HTML 阶段
│   ├── model/               # 当前 LightGBM
│   └── output/              # 打分 CSV 与 HTML
├── artifacts/current/       # 当天累计训练产物
├── docs/PIPELINE.md         # 总结与 pipeline 约定
└── runs/                    # 按日期归档
```

## 分层入口

模型阶段只出 CSV：

```powershell
F:\Clip\venv\Scripts\python.exe C:\Users\ZFGJ-WCH\Desktop\datta\screener\src\run.py --input C:\Users\ZFGJ-WCH\Desktop\datta\data\raw\917.csv
```

HTML 阶段吃 CSV：

```powershell
F:\Clip\venv\Scripts\python.exe C:\Users\ZFGJ-WCH\Desktop\datta\screener\src\generate_html.py --input C:\Users\ZFGJ-WCH\Desktop\datta\screener\output\917_scored.csv
```

日常不要直接跑 `rank_products.py --stage all`，它会走 `download`，可能把历史主图再下一遍。日常训练只跑 `prep` → `embed` → `train`，由 `daily_pipeline.py` 串好。

## 分享页

`screener/output/*_分享.html`：

- 默认 Top 5%，自动去掉违禁词和 2D/平面印刷
- 价格 / 标题关键词 / 中文分类筛选
- 删除、保留；F5 用 localStorage 记住
- 「保存筛选后HTML」才是发给别人的版本

## 硬约束

- `910.csv` 到后续很多「csv」实际是 xlsx，必须 `pd.read_excel(..., sheet_name="sheet", header=[0, 1])`
- 正式模型不用店铺规模、销量、GMV、收录时间、美区评分
- 训练 embedding 必须优先 `D:\temu_rank_npz`，不得为训练集全量下载主图
- 预测阶段只补当天还没有向量的主图；图片文件不进 git
