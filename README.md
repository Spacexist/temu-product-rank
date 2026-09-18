# Temu Product Rank

同一批 Temu 商品里的**排序筛子**，不是爆品分类器，也不是销量预言机。

模型只回答一件事：今天这批货里，哪些更该先看。日常只看 **Top 5%**，不要设固定分数线。

线上选品页：[datta-picks](https://datta-picks.changkaishen7788.workers.dev)

---

## 它做什么

每天从 Temu 后台导出类目日报（xlsx 外壳的 csv），流水线会：

1. 用历史日报训练一个排序模型
2. 给当天全量打分
3. 出 HTML 卡片页（默认 Top 5%，自动去掉违禁词和 2D/平面印刷）
4. 人在浏览器里删卡片
5. 保存后上传 Cloudflare，首页覆盖成最新一天，旧天按日期归档

发给别人的是人工筛过的页面，不是模型原始榜。

---

## 模型

三路特征拼给 LightGBM 回归：

| 路 | 来源 | 维度 |
|---|---|---|
| 图 | 主图 ResNet18 | 512 |
| 文 | 中文标题 `BGE-small-zh` | 512 |
| 表 | 价格、是否有视频、轮播图数、标题长度/中文占比、二级类目目标编码 | 若干 |

标签：

```text
y = log1p(clip(总销量, 0, 训练集 p99.5))
```

空销量当 0。正式模型 **不用** 店铺粉丝、店铺总销量、GMV、收录时间、美区评分——那些是店的规模，不是货的样子。

### 怎么切分

按 **店铺** `GroupShuffleSplit`，禁止按行随机切：

```text
25% 店铺 → test
剩下再 10% 店铺 → valid
其余 → train_fit
```

test 再去掉和训练集过近的货（同主图 URL / 同标题 / 图像余弦 > 0.98）。这样评估的是「没见过的店」，不是同一店换个 SKU。

默认不按正样本率分层。需要时设 `DATTA_STRATIFY_POS=1`。

---

## 每天在干什么

```text
第 N 天
  日报进 data/raw/
  用 raw 里除最新外的全部文件全量重训
  预测第 N 天 → *_scored.csv
  生成 *_分享.html
  人工删/留，另存
  上传 Cloudflare（首页 = 最新，/days/日期/ = 归档）

第 N+1 天
  第 N 天留在 raw 里当带标签训练数据
  再全量重训，预测 N+1
```

训练是「累计数据 + 每天重训」，不是 LightGBM 在线加树。图片/文本向量缓存在本机 `D:\temu_rank_npz`，训练阶段不为历史样本重新下载主图。

---

## 怎么跑

Python 环境需要 PyTorch、LightGBM、sentence-transformers、pandas。本机默认：

```powershell
F:\Clip\venv\Scripts\python.exe
```

一键日常（把今天的导出丢进去）：

```powershell
.\pipeline\daily_pipeline.ps1 -Today C:\path\今天.csv
```

文件已经在 `data/raw/` 时可以省略 `-Today`。常用开关：

| 参数 | 作用 |
|---|---|
| `-DryRun` | 只打印计划 |
| `-SkipTrain` | 训练已完成，只预测 + HTML |
| `-HtmlOnly` | 已有 `*_scored.csv`，只重出 HTML |

分层入口：

```powershell
# 模型阶段：只出 CSV
python screener/src/run.py --input data/raw/今天.csv

# HTML 阶段：吃 scored CSV
python screener/src/generate_html.py --input screener/output/今天_scored.csv
```

不要直接 `rank_products.py --stage all`：它会走 download，可能把历史主图再下一遍。日常训练由 `daily_pipeline.py` 串 `prep → embed → train`。

### 本机路径 / 环境变量

| 用途 | 默认 | 环境变量 |
|---|---|---|
| 向量 npz | `D:\temu_rank_npz` | `DATTA_NPZ` |
| 主图缓存 | `D:\temu_images` | `DATTA_IMG` |
| 训练产物 | `artifacts/current` | `DATTA_ART` |
| 日报目录 | `data/raw` | `DATTA_RAW` |

---

## 分享页和上线

`screener/output/*_分享.html`：

- 默认 Top 5%，自动去掉违禁词和 2D / 二维 / flat print / 无框
- 价格、标题关键词、中文分类筛选
- 删除 / 保留；F5 用 localStorage 记住
- 「保存筛选后 HTML」才是对外版本（不再带工作台标题）

上传：

```text
cf-site/uploadedCF.bat
```

或 `python cf-site/uploadedCF.py 文件.csv|.html`。站点是独立 Worker `datta-picks`，不要和「自动组货」混用。

---

## 目录

```text
data/raw/              原始日报（很多 .csv 其实是 xlsx）
data/cleaned/          历史清洗候选
pipeline/              训练、日更编排、导出
screener/              预测、违禁词、HTML
screener/model/        当前可部署 LightGBM
cf-site/               Cloudflare 静态站
docs/PIPELINE.md       操作约定和已跑日期
artifacts/current/     当天训练产物
runs/                  按日期归档
```

详细约定见 [docs/PIPELINE.md](docs/PIPELINE.md)。

---

## 硬约束

- `910.csv` 起很多「csv」实际是 Excel。读取必须 `pd.read_excel(..., sheet_name="sheet", header=[0, 1])`。
- 正式模型禁止店铺规模、销量本身、GMV、收录时间、美区评分。
- 分数只用于**同一批内部排序**。换一天、换类目不能拿绝对分对比。
- 训练 embedding 优先读 npz 缓存，禁止为训练集全量下载主图。
- 预测只补「当天还没有向量」的主图。图片文件不进 git。

---

## 已跑过的家居厨房日更

| 预测日 | 训练集 | Top 5% 去违禁去 2D |
|---|---|---:|
| 913 | 当时现有模型 | 203 |
| 914 | 909–913 | 262 |
| 915 | 909–914 | 284 |
| 916 | 909–915 | 248 |
| 917 | 909–916 | 232 |
