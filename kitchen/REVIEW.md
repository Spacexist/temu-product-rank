# 厨房收纳日更管道 — 设计说明（供 Review）

请按「选品筛子、不是爆品预言机」来审。不要建议改成分类器或去刷分。重点看：**泄露、切分、增量训练是否成立、三类合并后 cat_l1 是否用对、词表误伤、磁盘路径、HTML 主图、和人工筛选如何闭环。**

项目根目录：`C:\Users\ZFGJ-WCH\Desktop\厨房收纳`  
和 `Desktop\datta` 平行，**不覆盖** datta 主模型、**不写** `D:\temu_rank_npz`、**不碰**「自动组货」。

---

## 1. 要解决什么

每天 Temu 后台出 **三份不同一级类目 CSV**（家居厨房 / 商用工业 / 宠物），先合并再跑同一条管道：

1. `pipeline/merge_csv.py`（或桌面 `合并.bat`）合成一份；
2. `words/banned.txt` 去掉违禁 / 2D / 杯子等；
3. 算均值中位数，按天追加到 `cache.json`；
4. **第二天预测前**，把前一天人工留下的货加入训练；
5. 训完删训练集原图，图默认在 D 盘；
6. 预测 → HTML 卡片页（可调 Top 5%/10%、可删除）→ 保存后上现有 Cloudflare `datta-picks`。

项目名仍叫厨房收纳，数据范围已经不是单类目。

---

## 2. 已拍板的决策

| 项 | 选择 |
|---|---|
| 和旧日更关系 | 新项目，不替换 datta 全类目日更 |
| 位置 | Desktop 独立文件夹 |
| 每天输入 | **三个类目 CSV 先合并**，不再假设 inbox 里只有厨房 |
| 第一天 | 918 厨房当场按店铺从头训过一版；随后被 **2026-09-18 三份合并全量重训** 覆盖 |
| 交文件 | 合并脚本点名三个路径 **或** inbox 丢合并结果 **或** EXE 导入 |
| 切分 | 文档 12.1：`GroupShuffleSplit` **按 `shop_group`**，禁止随机切、禁止正样本分层 |
| 增量 | LightGBM **warm start**，只喂**昨天保存留下来的 CSV**（不是全历史重训） |
| 人工删除 | 窗口/HTML 里删掉的货 **明天训练不吃** |
| 预览 | HTML 选品页为主（卡片删除），页上调 Top 5% / 10% |
| 上线 | 拷一份 `cf-site`，仍发到现有 Worker `datta-picks` |
| EXE | customtkinter 壳，训练预测调 `F:\Clip\venv` |
| 统计 | 过滤**后**写入一份 `cache.json`，按日期追加：n、动销率、销量 mean/median/P90、价格 mean/median |
| 图 | 默认 `D:\temu_images`；训完可删已进训练集的图，今天预测用的图留到明天训完再删 |
| 类别特征 | 三类并存后 **`cat_l1` 进入 `CAT_COLS`**（不再当常量丢掉） |

---

## 3. 每天数据流

```
Downloads 三份 CSV（工业 / 家居厨房 / 宠物）
  → 合并.bat / merge_csv.py（必须点名文件；无参数会退出，避免误吃 Downloads 最新文件）
  → 按商品ID去重（销量高的留下）
  → data/raw/YYYYMMDD_merged.csv  并复制 inbox/
  → banned.txt 子串过滤 → data/cleaned/{stem}.csv
  → 统计追加 cache.json
  → 训练（见下）
  → 对 cleaned 打分 → output/{stem}_scored.csv
  → generate_html → output/{stem}_分享.html
  → 人在浏览器删卡片、调 Top%
  → 「筛选结果 → 明天训练」写入 data/published/
  → wrangler deploy → https://datta-picks.changkaishen7788.workers.dev
```

合并脚本：

```
合并.bat a.csv b.csv c.csv
python pipeline/merge_csv.py a.csv b.csv c.csv
python pipeline/merge_csv.py --dir C:\Users\ZFGJ-WCH\Downloads --n 3
```

Temu 导出经常是 xlsx 外壳的 csv，读表走 `read_excel(sheet=sheet, header=[0,1])`。

训练分支（`pipeline/daily.py` `run_today`）：

- `--retrain` 或没有模型：用**今天 cleaned** 按店铺从头训（第一天 / 词表大改 / 类目集合变了）。
- 已有模型 **且** 有 `data/published/`：只拿**最新 published** continue，然后删 published 对应原图（今天预测文件的图不删）。
- 已有模型但还没 published：跳过训练，只预测。

三类之后旧厨房-only booster **不能**直接打宠物/工业分（`cat_l1` 对不上）。类目集合变了应 `--retrain`。

---

## 4. 模型（从 datta `rank_products.py` 拷来，路径改隔离）

- 特征：表格（价格、标题长度、`cat_l1`/`cat_l2`/`source`、类目 TE 等）+ ResNet18 512 + BGE-small-zh 512。
- **full 不用店铺规模**（粉丝/店铺总销量等只在 LEAK 对照；日更只训 `full`）。
- 标签：`y = log1p(clip(总销量, 0, train p99.5))`。
- 切分（文档，seed=42）：
  ```
  GroupShuffleSplit(test_size=0.25, groups=shop_group)
  train 再 GroupShuffleSplit(test_size=0.1) → train_fit / valid
  ```
  test 再去近重复（同主图 URL / 标题 / 图像 cosine>0.98）。
- 日更 `DATTA_TRAIN_FULL_ONLY=1`，不训 price_only 等对照。
- LightGBM：`n_estimators=1200, lr=0.03, num_leaves=63, early_stopping=100`。
- continue：`LGBMRegressor.fit(..., init_model=昨天的 lgbm_full.txt)`，数据只有昨天 published。
- 推理必须把 pandas Categorical 的 categories **对齐 booster**：`cast_categories` 覆盖 `cat_l1` / `cat_l2` / `source`；`export_bundle` 写出 `cat_l1_categories`；`write_screener_config(today.name)`，空 `inference_source` 回落到 `meta.inference_source_fixed`。

### 4.1 第一天 918（厨房-only，已被覆盖）

- 原始 6737 → 过滤后 **4156**。
- 店铺切分：fit 2700 / valid 380 / test 1016。
- 注意：用 cleaned 918 **既训练又打分**，训练店会泄漏进榜，只适合冷启动出页。

### 4.2 2026-09-18 三类合并（当前模型）

Downloads：

| 文件 | 类目 | 行数 |
|---|---|---|
| `2100841085869494273.csv` | 商用、工业与科技 | 2569 |
| `2100752710132756482.csv` | 家居厨房用品 | 6737 |
| `2100840469165961217.csv` | 宠物用品 | 1889 |

合并去重 **11195** → 过滤后 **7748**（动销率 22.1%，销量中位数 0，P90=2，价格中位数 $7.08）。  
店铺切分：fit **5166** / valid **588** / test **1703**；`y_cap`≈36.2；`best_iteration=151`。  
打分 7748 条，违禁词命中 **0**（清洗阶段已经丢掉）。  
Top 5% **387** 条：家居厨房 168 / 商用工业 139 / 宠物 80。  
产物：`output/20260918_merged_分享.html`、`*_screener.html`、`*_Top.csv`。

这天仍是「今天训练集 ∩ 今天打分表」重叠，冷启动泄漏仍在。

---

## 5. 违禁词 `words/banned.txt`

匹配：NFKC + 繁转简 + lower + 去掉空格横线后 **子串包含**（`word_filter.py`）。

当前策略：

- **要拦**：IP/品牌、真违禁（水银/石棉/医疗等）、**2D / 二维 / flat print / 无框**、**杯子/水杯/马克杯/咖啡杯/茶杯/保温杯/tumbler/mug**。
- **不要拦**：`家用`、`储物盒`、`支架`、`好物`、`优选`、`牛津`（会误杀收纳本品）。
- 已去掉过短误伤：`LV`、`APP`、`Led`、单独 `hello`/`平面`。
- 词表约 156 条。厨房-only 918 上曾命中 2581/6737；三类合并清洗后预测阶段 0/7748。

请审：子串匹配是否还该改成词边界；`mug`/`遥控` 会不会误伤；杯子是否该只留「杯子」不留 tumbler/mug；**工业/宠物标题**是否会被厨房词表误杀或漏杀。

---

## 6. 路径（磁盘）

| 用途 | 路径 | 说明 |
|---|---|---|
| 代码/CSV/HTML | `C:\Users\ZFGJ-WCH\Desktop\厨房收纳` | 中文路径 |
| 主图 | `D:\temu_images` | 厨房收纳和 datta **共用**，按 URL md5 |
| 向量 npz / LGBM txt | `C:\Users\ZFGJ-WCH\AppData\Local\kitchen_rank\` | ASCII，避免 LGBM `save_model` 中文路径失败 |
| 主模型向量 | `D:\temu_rank_npz` | **禁止本项目写入** |
| 推理 Python | `F:\Clip\venv`，HF `F:\Clip\hf-cache` 离线 | |
| CF | 项目内 `cf-site/`，Worker 名仍 `datta-picks` | 上传会覆盖该站「最新页」 |

C 盘曾 100% 满；已删 C 上主图缓存。以后下图只去 D。

---

## 7. 入口文件

- `pipeline/merge_csv.py` + `合并.bat`：三份类目表合成 `data/raw/YYYYMMDD_merged.csv`。
- `pipeline/daily.py`：日更编排。
- `pipeline/rank_products.py`：prep / download / embed / 店铺切分 train。
- `pipeline/export_bundle.py`：导出 `screener/model/`（含 `cat_l1_categories`）。
- `screener/src/run.py`：预测。
- `screener/src/generate_html.py` + `render_html.py`：分享页。
- `app.py`：customtkinter 壳。
- `cf-site/uploadedCF.py`：日期导航 + wrangler。
- `启动.bat` / `跑今天.bat` / `打包EXE.bat`。

---

## 8. 已经踩过、已修的坑

1. **合并脚本无参数会吃 Downloads 最新 N 个文件**：曾误合成两份工业+宠物，覆盖正确三份。现默认必须写路径，或显式 `--dir`。
2. **`cat_l1` 进模型后预测炸**：LightGBM `train and valid dataset categorical_feature do not match`。原因：screener 只把 `cat_l2`/`source` 转 Categorical；空 `inference_source` 覆盖了 meta。已让 `cast_categories` 覆盖全部 `CAT_COLS`，config 回落 `inference_source_fixed`。
3. **分享 HTML 大量「无图」**：CSV 里 7748 条主图 URL 都在，CDN 抽查 200。页把全部图片一次性 `src` 进 DOM，本地 `file://` 并发打爆 kwcdn，`onerror` 永久换成「无图」。已改成 **只给当前可见卡片赋 `src`**，失败再用 `imageView2/2/w/400` 重试一次。请用 Chrome/Edge 打开，不要用 Cursor 预览。

---

## 9. 请重点 review 的问题

1. **Warm start 只吃昨天 published**：会不会几天后忘掉第一天（以及另外两个类目）？要不要改成「init_model + 全历史 published 再训一轮」？
2. **第二天增量仍对「昨天那一小份」做 25% 店铺 test**：日更 continue 还要不要留 test，会不会浪费标签？
3. **当天 train 和 predict 同一份 merged**：运营能接受泄漏榜吗？是否应只展示 test 店铺？
4. **三类一个模型**：工业/宠物/厨房销量分布差很多，一个 `y` cap、一个 LightGBM 会不会被某一类带跑？要不要按 `cat_l1` 分层评估，或分三个 booster？
5. **合并去重按商品ID留高销量**：跨类目同 ID 几乎不该出现；若出现，留高销量是否掩盖类目错绑？
6. **published 来源**：人在浏览器 localStorage 删卡片，必须再「保存 HTML / 导入」才进训练。掉步骤就会用错训练集。
7. **CF 共用 datta-picks**：厨房收纳上传会变成全站 latest。三类页和旧家居页抢「最新」。是否该分子路径？
8. **删图时机**：`D:\temu_images` 与 datta 共用哈希。厨房收纳删「昨天训练图」可能删掉 datta 还要用的同一张图。
9. **ASCII 模型仍在 C:`AppData\Local\kitchen_rank`**：C 盘紧时是否应迁到 D（例如 `D:\kitchen_rank`），与 `D:\temu_rank_npz` 分开。
10. **过滤在训练前丢掉行**：2D/杯子永远不进模型。若以后要给 2D 打低分而不是直接删，当前做不到。
11. **EXE**：壳调 venv，并未真正打进 torch；`打包EXE.bat` 只是计划。
12. **HTML 主图仍走 kwcdn 直链**：可见卡片方案减轻并发，但离线/CDN 风控仍会无图。要不要把 Top 缩略图下到本地再写进 HTML？

审完请按：必须改 / 可以接受 / 建议以后再做，三条给结论，不要空泛夸架构。
