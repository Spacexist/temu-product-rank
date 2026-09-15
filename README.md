# Datta 项目结构

这是从 `C:\Users\ZFGJ-WCH\Desktop\8天前数据` 整理出来的干净项目骨架。原目录不动；这里按用途重新归档核心文件。

## 当前状态

- 当前项目根目录：`C:\Users\ZFGJ-WCH\Desktop\datta`
- 当前可部署模型：`screener/model/lgbm_full.txt`
- 当前图片向量：`artifacts/embeddings/img.npz`
- 当前文本向量：`artifacts/embeddings/txt.npz`
- 当前 913 预测输出：`screener/output/913_scored.csv`
- 当前 913 人工筛选入口：`screener/output/913_分享.html`
- 当前增量训练缓存：`artifacts/current/`，已纳入 909-913
- 当前 914 预测输出：`screener/output/914_scored.csv`
- 当前 914 人工筛选入口：`screener/output/914_分享.html`

`img.npz` 已校验：

```text
keys: ids, X
ids: (41308,) object
X:   (41308, 512) float32
```

## 目录约定

```text
datta/
├── data/
│   ├── raw/                 # 原始日报；910/911/912/913 虽然后缀 csv，实际按 Excel 读
│   └── cleaned/             # 已清洗候选池，例如无收录、去训练库、无违禁
├── pipeline/                # 训练、验证、清洗、导出、HTML 生成主入口
│   └── legacy/              # 审计、外测、历史实验脚本，保留但不作为日常入口
├── screener/                # 日常筛子运行包
│   ├── src/                 # 预测/特征/HTML/违禁词代码
│   ├── model/               # 当前可部署 LightGBM 模型与特征配置
│   ├── words/               # 违禁词表
│   └── output/              # 已有打分 CSV 与 HTML 产物
├── artifacts/
│   ├── datasets/            # 训练用清洗数据
│   ├── embeddings/          # 文本/图片 embedding 与测试分数
│   ├── models/              # 实验模型 pkl 与 meta
│   ├── metrics/             # 指标 JSON、split、诊断
│   └── reports/             # md/html 报告与 top picks
├── docs/                    # 项目说明、任务说明、完整报告
└── runs/                    # 以后 daily pipeline 的日期归档目录
```

## 当前核心入口

- 训练/评估：`pipeline/rank_products.py`
- 时间外推验证：`pipeline/validate_temporal.py`
- 日报前置清洗：`pipeline/filter_download_csv.py`
- 模型导出：`pipeline/export_bundle.py`
- 日常预测入口：`screener/src/run.py`，只输出模型打分 CSV
- HTML 生成入口：`screener/src/generate_html.py`，读取打分 CSV 后生成 HTML
- HTML 快捷包装：`pipeline/generate_html_from_scored.ps1`
- 当前部署模型：`screener/model/lgbm_full.txt`

## 日常 pipeline 分层

模型阶段只负责产出 CSV，不再生成 HTML：

```powershell
cd C:\Users\ZFGJ-WCH\Desktop\datta\screener
F:\Clip\venv\Scripts\python.exe src\run.py --input "C:\path\日报.csv"
```

输出：

```text
screener/output/日期_scored.csv
```

HTML 阶段接受模型 CSV，再生成自己看的筛子、人工筛选页、自动过滤后的 Top CSV：

```powershell
F:\Clip\venv\Scripts\python.exe C:\Users\ZFGJ-WCH\Desktop\datta\screener\src\generate_html.py --input C:\Users\ZFGJ-WCH\Desktop\datta\screener\output\日期_scored.csv
```

也可以用包装脚本：

```powershell
C:\Users\ZFGJ-WCH\Desktop\datta\pipeline\generate_html_from_scored.ps1 -InputCsv C:\Users\ZFGJ-WCH\Desktop\datta\screener\output\日期_scored.csv
```

## 913 当前产物

913 已完成预测，输出在：

```text
screener/output/
├── 913_scored.csv
├── 913_screener.html
├── 913_分享.html
├── 913_Top5pct.csv
├── 913_Top5pct_去违禁_有图.csv
└── 913_Top5pct_去违禁_去2D平面.csv
```

当前 `913_分享.html` 是人工筛选入口：

- 默认只展示模型 Top 5%。
- Top500 会先自动剔除违禁词命中商品。
- Top500 会再自动剔除 `2D / 二维 / 平面 / flat printing / frameless / 无框` 等平面印刷类商品。
- 页面支持价格筛选、标题关键词筛选、分类筛选。
- 每张商品卡支持 `打开 / 删除 / 保留`。
- 删除/保留状态会写入浏览器本地存储，按 F5 刷新后仍会保留，防止误触丢筛选进度。
- 人工筛完后点 `保存筛选后HTML`，会另存一个只包含当前保留商品的 HTML。
- 另存出来的人工筛选版 HTML 仍支持价格、关键词、分类筛选，但不再包含删除/保留按钮。

当前过滤结果：

```text
Top500 原始商品：500
自动过滤后保留：203
过滤后违禁命中：0
过滤后 2D/平面命中：0
```

## 注意事项

- `910.csv`、`911.csv`、`912.csv`、`913.csv` 虽然后缀是 `.csv`，实际是 Excel/xlsx 格式，必须用 `pd.read_excel(..., sheet_name="sheet", header=[0, 1])` 读取。
- 正式模型禁止使用店铺规模、销量、GMV、收录时间、美区评分等泄露或不可迁移字段。
- 模型分数只用于同一批商品内部排序，日常按 Top 5% 看，不要设固定分数线。
- `_screener_pkg/cache/images` 那类图片文件缓存没有整体搬入 `datta`，因为体积大且可再生；核心 embedding 已放在 `artifacts/embeddings/`。
- 训练 embedding 阶段必须优先使用 `D:\temu_rank_npz\img.npz` / `txt.npz`，不得为了训练集全量下载主图。
- 日常预测阶段只下载当前日报里图片向量未缓存的主图；下载图片缓存属于可再生文件，不进 git。

## 后续 pipeline 目标

每天输入一个已清洗候选 CSV，输出 Top 5% HTML；下一天运行时，把上一天预测文件按原销量口径纳入累计训练库，重训并导出新 current 模型，再预测当天文件。

## 后续 pipeline 约定

- 每日输入默认是已清洗候选 CSV。
- 第二天运行时，自动从 manifest 找“已预测但未入训练”的上一批文件，也允许手动覆盖。
- 训练方式采用“累计数据 + 全量重训”，embedding 采用增量缓存。
- 训练库应包含每日不可变归档、manifest、当前合并训练表。
- 每天先把前一天日报纳入 `data/raw/` 后重跑训练；例如 914 预测前，训练集为 909-913。
- 模型阶段输出 `*_scored.csv`；HTML 阶段读取该 CSV 生成 HTML，不让模型脚本直接碰前端展示。
- 输出应按 `runs/YYYYMMDD/` 归档，同时最新 HTML 可同步到 `screener/output/`。
- 分享 HTML 先给自己人工筛，人工筛完保存出的 HTML 才发给别人。
