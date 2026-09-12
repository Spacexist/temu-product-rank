# 任务：把选品模型拆成独立工具包 + 违禁词过滤 + 可筛价格的 HTML

只做这一件事。**不要改** `rank_products.py`、`validate_temporal.py`、`artifacts_v2\` 里的已有结果。新东西全部放到一个**新的独立文件夹**。

目标工作流（以后每天都用这个）：

```
新的 csv/xlsx  ──►  模型打分  ──►  违禁词过滤  ──►  一个 HTML
                                              ▲
                                    页面上能筛价格
```

---

## 0. 独立文件夹放哪

```
C:\Users\ZFGJ-WCH\Desktop\选品筛子\
```

不要建在 `8天前数据` 里面。那个目录是实验场，这个目录是工具。

完成后的结构必须是：

```
选品筛子/
  README.md                 # 给人看的三行用法
  requirements.txt
  config.json               # 路径、阈值、种子；不要把绝对路径写死到代码里
  words/
    违禁词与侵权.txt         # 从源文件复制过来，工具不依赖微信缓存路径
  model/
    lgbm_full.txt           # LightGBM 原生文本（不要用 pickle）
    feature_names.json      # 训练时列顺序
    cat_l2_te.json          # {类目: 编码值, "_global": 全局均值, "m": 20}
    y_cap.json              # {"p995": 46.0}
    meta.json               # 训练日期、n、特征清单、禁止列
  src/
    read_table.py           # 读 xlsx/伪csv
    features.py             # 抽表格特征 + 对齐类别
    embed.py                # ResNet18 + BGE
    score.py                # 加载 booster 打分
    word_filter.py          # 违禁词
    render_html.py          # 出 HTML
    run.py                  # 唯一入口
  cache/images/             # 主图缓存（可复用实验场 hit_cache/images）
  output/                   # 每次运行的 csv + html
```

入口只有一个：

```powershell
cd C:\Users\ZFGJ-WCH\Desktop\选品筛子
$env:HF_HOME = "F:\Clip\hf-cache"
$env:HF_HUB_OFFLINE = "1"
F:\Clip\venv\Scripts\python.exe src\run.py --input "某天的文件.csv"
```

---

## 1. 从实验场「抽象」模型，不要重训

用现有实验场导出，**不要重新训练**（数字必须和报告里的 full 对得上）。

实验场：`C:\Users\ZFGJ-WCH\Desktop\8天前数据`

导出步骤（写一个一次性脚本 `export_bundle.py` 可以放在实验场，跑完即可；产物只写入 `选品筛子\model\`）：

1. 用 `rank_products.make_split_bundle()` 拿到和当时相同的 train_fit / valid / test。
2. 按 `full` 组拼特征（`tab + img + txt`，**不要**店铺列）。
3. 用同一套 `LGB_PARAMS` + `early_stopping(100)` 拟合，确认 test 上 Spearman 仍约 **0.31**、top5% P(>0) 仍约 **0.55**。对不上就停，不要继续打包。
4. 保存：
   - `model.booster_.save_model("选品筛子/model/lgbm_full.txt")` —— **禁止 pickle**
   - `feature_names.json` = 训练矩阵列名，顺序必须与 booster 一致
   - `cat_l2_te.json`：只来自 **train_fit** 的目标编码映射 + `_global` + `m=20`
   - `y_cap.json`：`p995`（当前是 46.0）
   - `meta.json`：写明 `CAT_COLS` 当时含 `source`；**推理时 `source` 一律填训练里出现过的某个值（建议 `"911.csv"`），不要把新文件名喂进去**（新文件名是未见类别）
5. 推理时未见的 `cat_l2` → `_global`。

图像 / 文本编码器不要另存权重，推理时现加载本地缓存：

- ResNet18：`torchvision.models.ResNet18_Weights.IMAGENET1K_V1`，`fc=Identity()`，L2 归一化，batch 32
- 标题：`SentenceTransformer("BAAI/bge-small-zh-v1.5")`，`normalize_embeddings=True`，batch 32
- 环境：`F:\Clip\venv\Scripts\python.exe`，`HF_HOME=F:\Clip\hf-cache`，`HF_HUB_OFFLINE=1`

主图下载逻辑照抄实验场：aiohttp 并发 200，Referer `https://www.temu.com/`，缓存目录可先指向实验场 `hit_cache\images`（只读复用），新图写到 `选品筛子\cache\images`。

**主图下载失败的行不要丢。** 实验场那条指令是错的。推理时：无图则图像向量置零 + `img_missing=1`（如果训练特征里没有这一列，就先置零，并在 HTML 上单独标红「无图，建议人工看」）。不要从结果里删除。

---

## 2. 读新输入

新文件和训练文件同构：两行表头的 xlsx。后缀是 `.csv` 也按 Excel 读：

```python
pd.read_excel(path, sheet_name="sheet", header=[0, 1])
```

清洗与实验场一致：商品 ID 去重、价格 > 0、抽主图 URL、标题优先中文否则英文。  
**不要过滤英文标题。不要用店铺列当特征。不要用销量/GMV/收录时间/美区评分当特征。**

`source` 特征：推理固定为 `"911.csv"`（见上）。在 HTML 里另存一列「来源文件名」给人看，那是展示，不是特征。

---

## 3. 违禁词过滤器（必须认真做）

源文件（只用来复制一次）：

```
c:\Users\ZFGJ-WCH\xwechat_files\wxid_bz7neadi4p6t12_8f47\business\favorite\temp\新建文件夹\查价格与违规\违禁词与侵权.txt
```

复制到 `选品筛子\words\违禁词与侵权.txt`。之后只读工具包里这份。

### 3.1 读词

- UTF-8，一行一个
- `strip`，空行丢掉
- 整表去重（源文件大量重复：三丽鸥、迪士尼、皮卡丘、战锤3……）
- 丢掉明显不是词的行：`那些大Ip`、`韩漫将杀类` 这种说明性句子（含「那些」「类」且长度 > 4 的可以跳过；拿不准就保留并在日志里打印「可疑行」）
- 保存一份 `words\words_normalized.json`：每条原始词 + 归一化后的匹配串，方便以后改词表不用改代码

### 3.2 匹配范围

对每条商品，拼一段「待查文本」，**中英文都查**：

- `商品标题（中文）`
- `商品标题（英文）`
- 工具里的 `标题`
- `前台分类（中文）` + `前台分类（英文）`（有就查）

不要只查一列。IP 侵权经常只写在英文标题里。

### 3.3 归一化（简体 + 中英文）

匹配前，词和文本都做同一套归一化：

1. 转 Unicode NFKC
2. 英文全部 **小写**
3. 去掉空格、下划线、连字符、点号：`hello kitty` / `HelloKitty` / `hello-kitty` 视为同一段
4. **繁体 → 简体**。优先用 `zhconv.convert(s, "zh-cn")`（若 venv 没有就 `pip install zhconv`，这是唯一允许新增的依赖）。词表按简体匹配，输入里的繁体也能打中
5. 全角英文/数字转半角（NFKC 已覆盖大部分）

### 3.4 怎么算「命中」

源词表里既有 `hellokitty` 也有单独的 `hello`、`kitty`，还有单字 `烟` `酒`。按用户要求：**词表里有的都要匹配**，不要擅自删短词。

规则：

- 归一化后做 **子串包含**（`norm_word in norm_text`）
- 中文、英文同一套，不区分语言
- 一条商品命中多个词：全部记下来，不要只留第一个
- 命中后 **不要从结果里删除**，打两个标记：
  - `banned = true/false`
  - `banned_hits = "迪士尼|皮卡丘"`（用 `|` 拼）

默认 HTML **先隐藏** `banned=true` 的行，页面上留一个开关「显示违禁（N 条）」。用户要看误伤时能打开。

### 3.5 日志（必须打印，方便发现误伤）

跑完打印：

- 词表条数（去重后）
- 命中商品数 / 总商品数
- **命中次数最多的 20 个词**（`hello`、`支架`、`家用`、`Usb` 这种短词会炸，必须让人看见）

不要在第一版里做「短词要词边界」的聪明逻辑。先如实匹配，用日志暴露误伤。以后改词表比改代码快。

---

## 4. 打分

对每个商品：

1. 抽表格特征（`cat_l2_te` 用导出的 json，未见类目用 `_global`）
2. 下主图 → ResNet18 → 512d L2
3. 标题 → BGE → 512d
4. 按 `feature_names.json` **逐列对齐**（缺的列填 0，多的列丢掉）。对不齐就报错退出，不要默默错位
5. `booster.predict` → `预测分`
6. 按预测分降序排名
7. 再跑违禁词

输出 csv：`output/<文件名>_scored.csv`，编码 `utf-8-sig`。至少含：

```
排名, 预测分, 商品ID, 标题, 美元价格, 一级类目, 二级类目,
主图URL, 商品链接, 来源文件,
banned, banned_hits, img_missing
```

有总销量列就附在最后（新文件可能没有，没有就空着）。

---

## 5. HTML（这是交付物）

`output/<文件名>_screener.html`，**单文件**，CSS/JS 内联，双击就能开，不要依赖外网 CDN。

页面必须能做的事：

1. **价格筛选**：最低价、最高价两个数字框 + 一键应用。改了立刻隐藏不符合的卡片/行，不用刷新。默认显示全部价格。
2. **违禁开关**：默认隐藏命中违禁的；打开后这些行用红底或红标显示，并写出命中了哪些词。
3. **只看前 N%**：默认 5%，可改 1 / 5 / 10 / 20 / 全部。这是按**预测分排名**截的，不是按价格。
4. 每条展示：缩略图（主图 URL）、预测分、价格、标题、类目、商品链接（新标签打开）、违禁词、无图标记。
5. 顶栏统计随筛选变化：**当前可见条数 / 总条数 / 其中违禁隐藏了多少 / 当前可见的价格区间**。
6. 表格或卡片都行，商品多时（上万行）不要卡死：用简单分页（每页 50）或虚拟列表，不要一次渲染 10000 张大图。缩略图 `loading="lazy"`，失败显示占位。

视觉要求：能看清、能筛、能点链接。不要做成营销站。中文界面。

用 `top_picks.csv` 的前 30 行先出一版静态 HTML 看样式，再接到真正的打分结果上。

---

## 6. 自测（做完必须跑）

1. 用实验场的 `911.csv`（其实是 xlsx）跑一遍完整流水线。
2. 打分应与 `artifacts_v2/test_scores.npz` 里 `pred_full` **对同一批商品 ID 大致同序**（Spearman > 0.95）。若对不上，先查特征列顺序和 `source` 填法，不要改模型去凑。
   - 注意：新工具会对 911 **全文件**打分，实验场 test 只是其中按店铺切出来的 2290 行。对齐时只拿两边都有的商品 ID 比。
3. 违禁词：在结果里应能找到至少若干 `banned=true`（迪士尼/凯蒂猫/Nike 这类标题很常见）。若 0 命中，过滤器写错了。
4. HTML：手动改价格上下限，行数会变；打开违禁开关，红标行出现。
5. 主图缺失的行还在结果里，并带 `img_missing`。

日志打印耗时：读表 / 下载 / 图像 / 文本 / 预测 / 过滤 / 出 HTML。

---

## 7. README 只写这些

```text
1. 把新的日报表丢进来（xlsx，后缀叫 csv 也行）
2. 运行：
   F:\Clip\venv\Scripts\python.exe src\run.py --input 路径
3. 打开 output\ 里的 HTML，用价格框和「前 5%」筛
4. 主图拉不到的、标了违禁的，默认先别上架
```

不要把实验结论、AUC、lift 写进 README。那是给实验场看的。

---

## 8. 约束

- 解释器必须是 `F:\Clip\venv\Scripts\python.exe`
- 唯一允许新装的包：`zhconv`（繁转简）。别的都用 venv 里已有的
- 不要把微信那个绝对路径写进运行时代码
- 不要 pickle
- 不要店铺特征
- 不要在这个任务里重训、调参、改 LightGBM 叶子数
- 不要改实验场已有指标文件
- 完成后在 `选品筛子\README.md` 里写实际命令和一次自测的命中违禁条数
