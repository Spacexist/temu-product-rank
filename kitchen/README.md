# 厨房收纳日更

独立项目。不碰 datta 主模型，不写 `D:\temu_rank_npz`。

## 每天

1. 三个类目 CSV 先合并：`合并.bat a.csv b.csv c.csv`（写出 `data/raw/YYYYMMDD_merged.csv` 并拷到 `inbox\`）。
2. 或把已合并 CSV 丢进 `inbox\`，双击 `启动.bat` 点导入。
3. 流水线：`words/banned.txt` 过滤（含 2D/平面/杯子）→ 统计写入 `cache.json` → **按店铺 GroupShuffleSplit** 训练（有昨天保存结果则 continue）→ 预测 → `output/*_分享.html`。
4. 浏览器里删卡片，可调 Top 5% / 10%。保存筛选后 HTML。
5. 「筛选结果 → 明天训练」或「上传 Cloudflare」时生成上传包：数分 HTML + 数据写入 `data_cache/YYYY-MM-DD/`（按天留档，不覆盖旧天）。
6. 「上传 Cloudflare」发到现有 [datta-picks](https://datta-picks.changkaishen7788.workers.dev)。

当前模型是 2026-09-18 三类合并重训。没有模型或类目集合变了会按店铺切分从头训；之后只拿你保存的昨天清单 continue。

## 路径

| 用途 | 位置 |
|---|---|
| 过滤词 | `words/banned.txt` |
| 统计 | `cache.json`（按天追加） |
| 图片 | `D:\temu_images`（默认下载到 D 盘；训完可删） |
| 向量 / LightGBM txt | `%LOCALAPPDATA%\kitchen_rank\`（ASCII 路径） |
| 人工清单 | `data/published\` |
| 每天上传包 / 数分 | `data_cache/YYYY-MM-DD/`（`上传.html` `分析.html` `分析.json`） |

命令行：`跑今天.bat` 或 `python pipeline/daily.py --today 某.csv`

EXE 壳是 customtkinter，训练仍走 `F:\Clip\venv`。
