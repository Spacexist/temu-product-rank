# 选品排序总结与日常 Pipeline

对外说明看仓库根目录 [README.md](../README.md)。本文是操作约定：怎么训、怎么切分、怎么出 HTML、怎么上 Cloudflare。

这是 Temu 家居厨房用品的选品排序筛子，不是爆品预言机。模型只负责同一批商品内部排序；每天看 Top 5%，不要设固定分数线。

## 模型怎么做判断

每个商品拆成三块特征，喂给 LightGBM 回归：

1. 主图：ResNet18，512 维
2. 中文标题：BGE-small-zh，512 维
3. 表格：价格、是否有视频、轮播图数、标题长度、中文占比、二级类目目标编码

训练目标：

```text
y = log1p(clip(总销量, 0, train_p99.5))
```

空销量按 0。正式模型禁止店铺规模、销量、GMV、收录时间、美区评分。店铺特征只允许出现在诊断对照 `LEAK_shop`，不能进推荐。

时间外推（909+910 训，挑 911）Top 5% 动销大约是当天基线的 2x。日常按这个预期用。

## 每天实际在干什么

```text
第 N 天：
  把 N 的日报放进 data/raw/
  用 909 .. N-1 全量重训
  预测 N，只出 scored CSV
  HTML 阶段生成分享页
  你手动删/留，另存后再发给别人
  或用 cf-site/uploadedCF.bat 导入 CSV，标准化 HTML 后上传 Cloudflare

第 N+1 天：
  把 N 留在 data/raw/ 当带标签训练数据
  重训后再预测 N+1
```

训练不是 LightGBM 在线加树，是累计数据每天重训。向量缓存在 `D:\temu_rank_npz`，训练阶段禁止为了历史样本全量下载主图。

## 一键入口

把当天文件丢进去即可。下面这行会自动：复制到 `data/raw/`、用除最新外的全部日报训练、导出模型、预测最新一天、生成 HTML、归档到 `runs/YYYYMMDD/`。

```powershell
C:\Users\ZFGJ-WCH\Desktop\datta\pipeline\daily_pipeline.ps1 -Today C:\Users\ZFGJ-WCH\Downloads\917.csv
```

或：

```powershell
F:\Clip\venv\Scripts\python.exe C:\Users\ZFGJ-WCH\Desktop\datta\pipeline\daily_pipeline.py --today C:\Users\ZFGJ-WCH\Downloads\917.csv
```

`917.csv` 已经在 `data/raw/` 时，可以省略 `--today`，pipeline 会把 raw 里最新文件当今天。

常用续跑：

```powershell
# 只看计划，不跑
.\pipeline\daily_pipeline.ps1 -DryRun

# 训练已在别处跑完，只预测 + HTML
.\pipeline\daily_pipeline.ps1 -SkipTrain

# 已有 *_scored.csv，只重出 HTML
.\pipeline\daily_pipeline.ps1 -HtmlOnly
```

不要和正在跑的 `rank_products.py --stage train` 并行再开一轮训练。

## 分层

| 阶段 | 脚本 | 产物 |
|---|---|---|
| 训练 prep/embed/train | `pipeline/rank_products.py` | `artifacts/current/`，向量写入 `D:\temu_rank_npz` |
| 导出 | `pipeline/export_bundle.py` | `screener/model/lgbm_full.txt` |
| 预测 | `screener/src/run.py` | `screener/output/日期_scored.csv` |
| HTML | `screener/src/generate_html.py` | 分享页、完整筛子、过滤 Top CSV |
| 上传 | `cf-site/uploadedCF.py` | 标准选品页发布到 Cloudflare |
| 编排 | `pipeline/daily_pipeline.py` | 串以上步骤，并写入 `runs/` |

日常默认跳过 `download` 和 `eval`。训练只从 NPZ 和已有本地图补向量。预测阶段才下载「当天还没有向量缓存」的主图。

## HTML 规则

`*_分享.html` 默认只展示 Top 5%，并先自动剔除违禁词和 2D/平面印刷类。页面支持价格、标题关键词、中文前台分类筛选。卡片可删除/保留；删除状态写入 localStorage，F5 不会丢。筛完点「保存筛选后HTML」再发给别人。

## 上传 Cloudflare

对外站点（独立 Worker `datta-picks`，不是「自动组货」）：

https://datta-picks.changkaishen7788.workers.dev

- `/` 默认最新一天
- `/days/2026-09-18/` 或 `/days/918/` 按日期归档
- 页顶可改日期、下拉已发布列表

本机上传窗口：

```text
C:\Users\ZFGJ-WCH\Desktop\datta\cf-site\uploadedCF.bat
```

逻辑：

1. 导入 CSV（`*_scored.csv` 或 `*_Top5pct_去违禁_去2D平面.csv`）或已有 HTML
2. 手动核对发布日期（年/月/日，可改 ISO；短码跟随，如 918）
3. 按分享页同一口径标准化：可选 Top 5%、去违禁、去 2D/平面
4. 生成统一卡片页（价格/关键词/分类筛选，无删除按钮）
5. 预览后上传；`public/index.html` 换成这一天，`days.json` 追加归档

已是过滤结果的 CSV 会默认不再截 Top5%。命令行也可以：`python uploadedCF.py 文件.csv|.html`

## 已跑过的日期

| 预测日 | 训练集 | Top5 自动过滤后 |
|---|---|---:|
| 913 | 当时现有模型 | 203 |
| 914 | 909-913 | 262 |
| 915 | 909-914 | 284 |
| 916 | 909-915 | 248 |
| 917 | 909-916 | 232 |

917 训练日志：`full K=20 lift@5=1.231`，`full K=50 lift@5=1.050`。

## 路径

- 项目：`C:\Users\ZFGJ-WCH\Desktop\datta`
- 仓库：https://github.com/Spacexist/temu-product-rank
- 向量缓存：`D:\temu_rank_npz\img.npz`、`txt.npz`
- Python：`F:\Clip\venv\Scripts\python.exe`
- 上传窗口：`C:\Users\ZFGJ-WCH\Desktop\datta\cf-site\uploadedCF.bat`
- 对外链接：https://datta-picks.changkaishen7788.workers.dev
