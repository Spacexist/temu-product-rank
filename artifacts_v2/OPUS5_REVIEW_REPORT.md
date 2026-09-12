# 选品排序实验 — 完整交付报告（供 Opus 5 审查）

**项目路径**：`C:\Users\ZFGJ-WCH\Desktop\8天前数据\`  
**主代码**：`rank_products.py`（`prep | download | embed | train | eval | all`）  
**规范依据**：`PLAN_rank_products.md` · 第 2 轮返工：`REWORK_for_composer.md`  
**审查角色**：请对照 REWORK 验收清单、数值自洽性、外推边界与未覆盖风险逐项审计。  
**报告日期**：2026-09-12  
**执行环境**：Python `F:\Clip\venv\Scripts\python.exe` · `HF_HOME=F:\Clip\hf-cache` · `HF_HUB_OFFLINE=1`

---

## 0. 审查摘要（30 秒）

| 维度 | 状态 | 要点 |
|------|------|------|
| REWORK P0（配对 slate、winsorize、top5% 主表、去 lift@1） | **已落实** | `rand`/`oracle@1` 跨组一致；`y_cap_p995_train=46` |
| REWORK P1（去 cat_l1、窗口表述、LEAK 叙事、店铺诊断） | **已落实** | 见 `report.md` · `shop_scale_diagnostic.json` |
| 域内结论 | **可用但需读表顺序** | 主指标：full top5% P(>0)=**55.2%**（基线 22.1%）；slate：full lift@5=**1.98**，低于 title/image-only 的 ~2.07–2.28 |
| 外测（831-910 单文件） | **偏乐观** | 随机 2000：top5% P(>0)=**80.6%**；全行 9641：**85.7%**（非 label 压力） |
| Label 正例率压力 | **已扫 0–100** | **0% 池：P(>0)=0% 但 top5% 预测均值≈0.94** → 校准/阈值风险 |
| 已知工程债 | 见 §8 | 外测每次重训；`lgbm_full.pkl` 离线加载不稳；831-910 仅 1/10 文件 |

**给审查者的核心问题 —— 已由 Opus 5 回答（2026-09-12 审计）**：

1. **slate 上单模态强于 `full`，是否融合不当？** → **不是。指标错位。** 训练目标已截尾到 46 件，而原始 lift@5 按未截尾销量加权、被 4900 件级别的极端品主导。把销量截到同一点重算，排名恢复正常（full 2.145 > tab 1.987 > title 1.912 > image 1.542）；且 full 在 `ndcg@5`(0.435)、`hit@5`(0.538)、top-5% 上本来就全部第一。应以截尾 lift@5 / ndcg@5 / top-5% 为准，原始 lift@5 降为辅助。详见 `audit_round2.py` 与 `report.md`。
2. **外测高于域内？** → **这个对比本身无效**，两边基线是 61% vs 22.1%。见 §6.1 的审计更正表：基线归一化后泛化成立且略有改善，但 80.6%/85.7% 不许单独引用。
3. **label 0% 池「虚高」是否阻断上线？** → **这一项被过度解读了。** 在一个不含任何正例的池子里，precision 恒为 0 是构造使然，不是模型缺陷，该测试不提供信息。预测均值 0.94 是 `log1p` 尺度，还原约 1.6 件，对一个**排序**模型而言绝对值本身没有意义。真正成立的那条建议是：**永远按「今天这批候选的前 X%」来取，不要设固定绝对分数阈值。**

**Opus 5 另外发现的、本报告未覆盖的问题（严重度高于上面三条）**：主图下载失败被丢弃的 432 行，动销率 **74.3%**（保留行 22.9%），Fisher p=4e-111，占全部正例 4.5%。对评测影响是偏保守，但对**日常使用**影响很大：流程会静默跳过整批候选里命中率最高的那 1.45%。详见 `report.md` 对应章节与 `PLAN_rank_products.md` 修订记录 R4。

---

## 1. 业务目标与标签

- **任务**：在同一店铺/同一 source 文件内，对 SKU 按「预期销量」排序，支撑选品（取 top 5% 等）。
- **训练目标**：回归 `y = log1p(clip(总销量, 0, p99.5_train))`，`p99.5_train = 46`（`split.json` / `y_cap_p995_train`）。
- **验收口径（报告用，非训练损失）**：全量 test 上 top 5% 的 precision：销量>0、≥5、≥20；以及 paired slate 的 `lift@5`（**不用 `lift@1`**）。
- **禁用作特征**：店铺列（full）、`收录时间`、`美区评分`、标签派生列；`cat_l1` 已剔除（常量「家居厨房用品」）。

> **适用范围警告**：训练数据一级类目 100% 为「家居厨房用品」。任何「全站选品」表述均不成立。

---

## 2. 数据与切分

| 项 | 值 |
|----|-----|
| 训练源 | `909.xlsx`, `910.csv`, `911.csv` |
| 去重后 SKU | ~29 871 |
| train / valid / test | 19 993 / 2 395 / 6 879（`split.json`） |
| 切分 | `GroupShuffleSplit` by `shop_group` |
| test 近重复剔除 | main_url 45 · title 61 · image_cosine 66 |
| 正例率（test 销量>0） | ~22.1%（top5% 基线） |

### 观察窗口（与 PLAN §3 一致，非「1–2 天」旧结论）

- 导出条件：`收录时间` 至少 8 天前。
- `上架时间` 列为**抓取时刻**，非真实上架。
- 有收录时间样本：恰好 7 天 55.2%，≤8 天 74.9%，>8 天 25.1%，均值 8.5 天，最长 67 天。
- Slate 抽样：**仅在同一 `source` 文件内**。

---

## 3. 模型与特征（8 组对照）

| 组别 | 内容 |
|------|------|
| random | 随机分（独立 RNG，不消耗 slate RNG） |
| price_only / cat_only / tab_only | 表格子集 |
| title_only / image_only | BGE 512d / ResNet18 512d |
| **full** | tab + image + text；`CAT_COLS = (cat_l2, source)` |
| LEAK_shop | full + 店铺规模相关列（**仅诊断**，不可部署） |

- 学习器：LightGBM（各组 `best_iteration` 见 `models_meta.json`，full≈337）。
- `cat_l2`：train 上 target encoding，test 用 train 统计。

---

## 4. 第 1 轮 → 第 2 轮（REWORK）变更与影响

### 4.1 已修复的 P0 缺陷

1. **非共用 slate**：各组 `rand`/`oracle@1` 不一致 → `full` lift 被抬高，且 **LEAK vs full 结论反转**。  
   - 修复：`make_slates` 一次生成，全组复用；`assert len(rands)==1`。  
   - 参考：`audit_eval.py` → `metrics_topk_paired.json`（审查可对照）。

2. **未 winsorize**：已改为 train p99.5 clip 后重训。

3. **报告结构**：主表改为全量 top5%；删除 lift@1 叙事。

### 4.2 数值：bug 修复 vs winsorize（请审查是否解释充分）

| 指标 | Round1（`_round1/`，有 slate bug） | Round2（当前） | 备注 |
|------|-----------------------------------|----------------|------|
| full lift@5 (K=20) | **2.90** | **1.98** | 主要来自 **共用 slate** |
| LEAK lift@5 | 2.81 | **2.83** | REWORK 预期：LEAK > full |
| full top5% P(>0) | 0.555 | **0.552** | winsorize 影响很小 |
| LEAK top5% P(>0) | 0.587 | **0.602** | LEAK 仍略高于 full |

备份：`artifacts_v2\_round1\`（含旧 `report.md`、`metrics_topk.json`）。

### 4.3 REWORK 验收清单（自查）

| # | 要求 | 证据 |
|---|------|------|
| 1 | 同 k 下 `rand`、`oracle@1` 全组相同 | `rank_products.py` stage_eval assert；`metrics_topk.json` 各组 `rand`=5.28025（K=20） |
| 2 | random `lift@5` ∈ [0.85, 1.15] | random **0.916** ✓ |
| 3 | y 含 train p99.5 clip | `split.json` `y_cap_p995_train`: 46 |
| 4 | 无 cat_l1 特征 | `CAT_COLS` 注释 + 代码 |
| 5 | report 无 lift@1 主表；首表 top5% | `artifacts_v2/report.md` |
| 6 | 窗口描述与 PLAN 一致 | `report.md` §观察窗口 |
| 7 | 店铺 Spearman + 分档 top5% | `shop_scale_diagnostic.json` |

---

## 5. 域内主结果（Round2）

### 表 A — 全量 test Top 5%（**主指标**）

来源：`metrics_top5pct.json`

| 组别 | P(>0) | ×基线 | P(≥5) | ×基线 | P(≥20) | Rec(≥5) |
|------|------:|------:|------:|------:|------:|------:|
| random | 0.253 | 1.14 | 0.087 | 1.18 | 0.009 | 0.059 |
| tab_only | 0.503 | 2.27 | 0.230 | 3.10 | 0.064 | 0.155 |
| title_only | 0.494 | 2.23 | 0.215 | 2.91 | 0.052 | 0.145 |
| image_only | 0.352 | 1.59 | 0.169 | 2.28 | 0.035 | 0.114 |
| **full** | **0.552** | **2.49** | **0.282** | **3.81** | **0.087** | **0.191** |
| LEAK_shop | 0.602 | 2.72 | 0.299 | 4.05 | 0.090 | 0.202 |

基线（test）：P(>0)=0.221，P(≥5)=0.074，P(≥20)=0.016。

### 表 B — Paired slate（K=20，3000 slates，共用）

来源：`metrics_topk.json` + `report.md`

| 组别 | lift@5 | recovery@5 | hit@5 | ndcg@5 |
|------|-------:|-----------:|------:|-------:|
| tab_only | 1.35 | 0.34 | 0.47 | 0.39 |
| title_only | **2.07** | 0.52 | 0.48 | 0.39 |
| image_only | **2.28** | 0.57 | 0.39 | 0.33 |
| **full** | **1.98** | 0.50 | 0.54 | **0.44** |
| LEAK_shop | **2.83** | 0.71 | 0.57 | 0.46 |

- 全 test Spearman(full 预测, 总销量) = **0.3135**（`report.md`）。
- **审查注意**：`full` 的 top5% 优于单模态 tab，但 **slate lift@5 低于 title_only / image_only**。可能原因：融合稀释、LGBM 对拼接向量分配、或 slate 指标对「单点爆款」更敏感。需 Opus 判断是否为方法问题或指标错位。

### 表 C — 店铺规模诊断（full，P1-4）

来源：`shop_scale_diagnostic.json`

- Spearman(预测分, 店铺总销量) = **0.115**（弱相关，非 LEAK 级）。
- 分档 top5% **P(≥5)**：low **19.7%** · mid **39.0%** · high **21.7%**（ tertile 切点 419 / 13000 店铺总销量）。

**解读**：`full` 不携带店铺列，但 **mid 档 precision 最高**，high 档并不占优 → 存在「中等规模店铺品更好挑」现象，不宜简单说「只挑大店」。审查请评估是否与类目/价格带混杂。

### LEAK_shop 叙事（已按 REWORK 更正）

- LEAK lift@5 **高于** full（2.83 vs 1.98），**不是**切分泄露（test 已按店铺隔离）。
- **⚠️ 审计更正（Opus 5）**：「店铺流量代理」「大店红利上界」这类说法是因果解释，本实验给不出，已作废。可下的结论只有：**店铺变量在这批历史数据、这些指标上携带额外的预测信息，来源不明。**
- 部署仍用 **full**，理由不需要因果假设：候选品最终都进同一家店，店铺变量对所有候选取值相同，对排序零贡献。

---

## 6. 外测（831-910，单文件）

**文件**：`C:\Users\ZFGJ-WCH\Desktop\831-910\2097863420316155906.csv`  
**脚本**：`score_external_one.py`（每次运行 **内存重训** full，与 train 配置一致，非加载 `lgbm_full.pkl`）

### 6.1 自然分布

| 设置 | n 打分 | 文件正例率 | top5% P(>0) | top5% P(≥5) | Spearman |
|------|--------|------------|------------|------------|----------|
| 随机 2000（seed=42） | 1949 | ~61% | **80.6%** | 60.2% | 0.37 |
| 全行（`rows_p0` 命名，实为 sample-pct 0） | 9641 | ~62% | **85.7%** | 65.0% | 0.38 |

JSON：`external_2097863420316155906.json` · `external_2097863420316155906_p0.json`

**⚠️ 审计更正（Opus 5）**：「外测 P(>0) 显著高于域内（55% vs 81–86%）」这个对比**无效，且会导致高估模型**。两边的基线完全不同——外测文件本身就有 ~61% 的品在卖，域内 test 只有 22.1%。换成可比口径：

| | top5% P(>0) | 基线 | 相对基线 | 理论天花板 | 走到天花板的比例 | Spearman |
|---|---:|---:|---:|---:|---:|---:|
| 域内 test | 55.2% | 22.1% | 2.49× | 4.52× | 55% | 0.3135 |
| 外测 随机2000 | 80.6% | ~61% | **1.32×** | 1.64× | **80%** | 0.37 |
| 外测 全行9641 | 85.7% | ~62% | **1.38×** | 1.61× | **86%** | 0.38 |

**正确结论**：泛化是成立的——受基线影响的「相对基线倍数」下降到 1.3×，纯粹是高基线下天花板只有 1.64× 的机械效应；而不受基线影响的指标（Spearman 0.3135 → 0.37~0.38、走到天花板的比例 55% → 80%+）反而略有改善。

**但 `80.6%` / `85.7%` 这两个数不许单独引用**，尤其不能读成「模型准确率 86%」——它主要反映那个文件本身好卖。跨基线比较只能用 Spearman 或天花板归一化后的口径。

其余保留的审查点：831-910 **其余 9 个文件未测**，无多文件聚合区间。

### 6.2 Label 正例率压力（`--pos-pct`）

子集内控制「销量>0」占比；0%=仅零销量；100%=仅有销量；中间档分层抽样 cap≤5000。

| 目标正例率 | 打分 n | 实际正例率 | top5% P(>0) | 基线 | lift | top5% 预测均值 | Spearman |
|-----------|--------|------------|------------|------|------|----------------|----------|
| **0%** | 3683 | 0% | **0%** | 0% | — | **0.94** | — |
| 10% | 4824 | 23.7%* | 48.3% | 23.7% | 2.04× | 1.00 | 0.34 |
| 30% | 4823 | 29.5% | 59.1% | 29.5% | 2.00× | 1.01 | 0.36 |
| 50% | 4806 | 49.5% | 79.3% | 49.5% | 1.60× | 1.05 | 0.40 |
| 80% | 4790 | 79.9% | 93.3% | 79.9% | 1.17× | 1.08 | 0.29 |
| 100% | 5958 | 100% | 100% | 100% | 1.00× | 1.11 | 0.14 |

\*目标 10% 而实际 23.7%：**零销量行主图缺失更多**，进入 `embed_frame` 后正例率上移（审查可要求按「可打分池」重新分层）。

汇总：`external_2097863420316155906_label_stress_summary.json`  
可视化：`选品评估报告.html` · `外测_label压力_2097863420.html`

**压力结论**：在 **全无销量** 池，排序精度为 0，但模型仍给出 **高绝对分** → 若业务按固定阈值上架，存在 **假阳性** 风险。100% 正例池 Spearman 仅 0.14 → 模型主要在区分「好卖 vs 更好卖」，弱于区分「有无销量」（在已是正例的池子里）。

---

## 7. 产物清单

| 路径 | 说明 |
|------|------|
| `artifacts_v2/dataset.csv`, `img.npz`, `txt.npz`, `split.json` | 数据与切分 |
| `artifacts_v2/metrics_top5pct.json` | 主指标 |
| `artifacts_v2/metrics_topk.json` | Slate 指标 |
| `artifacts_v2/metrics_topk_paired.json` | 审计参考（paired） |
| `artifacts_v2/shop_scale_diagnostic.json` | 店铺诊断 |
| `artifacts_v2/report.md` | 人类可读简版 |
| `artifacts_v2/top_picks.csv` | 推荐列表 |
| `artifacts_v2/lgbm_full.pkl` | 模型（Windows pickle 曾崩溃） |
| `artifacts_v2/_round1/` | Round1 备份 |
| `audit_eval.py` | 独立复现 paired eval |
| `score_external_one.py` | 外测 + label 压力 |
| `build_label_stress_html.py` | 刷新压力 HTML |

---

## 8. 已知问题与工程债（请审查优先级）

1. **外测每次重训**（~3–6 min/次）：未稳定导出 `lgbm_full.txt`（中文路径 LightGBM write 失败），离线打分依赖 refit。
2. **`lgbm_full.pkl`**：Windows 上 pickle 加载曾 access violation；生产应改用原生 booster 文件 + 固定特征名。
3. **模态悖论**：slate 上 image/title-only lift > full，但 top5% 表 full ≥ 模态 → 报告须双指标并列，不可只报其一。
4. **命名混淆**：`external_*_p0.json` = 全行样本；`external_*_labelp0.json` = label 0% 压力。
5. **外测覆盖不足**：831-910 10 文件中仅完成 1 个；无多文件聚合置信区间。
6. **LEAK 与 full 差距**：top5% 约 +5pt P(>0)，slate lift 约 +43% → 不同指标对店铺信号敏感度不同。
7. **未做**：概率校准、显式二阶段（先 P(>0) 再 E[销量|>0]）、时间外推（按收录时间切 train/test）。

---

## 9. 建议审查动作（Opus 5）

1. **复算**：运行 `python audit_eval.py`，核对与 `metrics_topk.json` 一致。  
2. **断言**：扫 `rank_products.py` `stage_eval` 中 assert 与 `make_slates` 逻辑。  
3. **对照 Round1**：确认无文档仍引用「full lift 2.9 > LEAK」或「店铺特征无用」。  
4. **外测泛化**：决定是否批量跑 831-910 余下 9 文件 + 固定 seed 的 2000 抽样协议。  
5. **上线门槛**：针对 labelp0，是否要求校准后 top5% 预测分 < ε 或两阶段模型。  
6. **统计**：对 full vs tab_only、full vs LEAK 的 paired slate 差值是否需报告 CI（REWORK 提及 CI，当前 `report.md` 未写入 Round2 CI，审查可要求补跑 `audit_eval` /bootstrap）。

---

## 10. 执行命令（复现）

```text
cd C:\Users\ZFGJ-WCH\Desktop\8天前数据
set HF_HOME=F:\Clip\hf-cache
set HF_HUB_OFFLINE=1

F:\Clip\venv\Scripts\python.exe rank_products.py all

F:\Clip\venv\Scripts\python.exe score_external_one.py ^
  --file C:\Users\ZFGJ-WCH\Desktop\831-910\2097863420316155906.csv ^
  --sample 2000

F:\Clip\venv\Scripts\python.exe score_external_one.py ^
  --file ...\2097863420316155906.csv --pos-pct 0

F:\Clip\venv\Scripts\python.exe build_label_stress_html.py
```

---

## 11. 交付陈述（实施方自评）

- REWORK 所列 **P0/P1 已在代码与 `report.md` 落地**；Round1 已备份可对比。  
- 域内：**full 相对 random/tab 有稳定 uplift**；**LEAK 高于 full 已正确解释**。  
- 外测与压力测试表明：**高正例率文件上表现更好**；**零销量池存在分数虚高**，不宜直接当「能卖」概率。  
- **不建议**在未补全 831-910 多文件、未做校准前，将当前分数当全站或跨类目生产规则。

---

*本文件由 Composer 执行轮次整理，供 Opus 5 独立审计；若与 `metrics_*.json` 冲突，以 JSON 为准并请标注 issue。*
