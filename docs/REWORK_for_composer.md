# 返工说明（第 2 轮）

> 上一轮按 `PLAN_rank_products.md` 跑出的 `artifacts_v2\` 已审计。**主体做对了**（特征构造、分组切分、去重、禁用列都合规），但评测环节有一个会导致结论反向的 bug，另有一处 PLAN 要求被漏掉。
> 本文件只描述**需要改什么**，未提到的部分保持原样，不要重写整个 pipeline。
> 参考实现见 `audit_eval.py`（我已写好的配对评测），修正后的指标在 `artifacts_v2\metrics_topk_paired.json`。

---

## 必须修（P0）

### P0-1 评测的 slate 每个对照组都不一样 —— 会让结论反向

`stage_eval` 里：

```python
rng = np.random.RandomState(SEED)      # 只建了一次
for k in ks:
    for name in EVAL_GROUPS:
        results[str(k)][name] = eval_slates(..., rng=rng)   # 按引用传入，状态一路往前走
```

`eval_slates` 内部用这个 rng 抽 slate，所以 8 个组抽到的是 8 批**不同**的 slate。`random` 组还多消耗一次 `rng.random(k)`，进一步错位。

**证据**（已产出的 `metrics_topk.json`）：`rand` 这个量是「整个 slate 的真实销量均值」，与模型无关，本该对所有组完全相同，实测却是 random 4.611 / cat_only 4.243 / tab_only 4.379 / full 5.223；`oracle@1` 从 73.78 跳到 93.33。`full` 抽到了最肥的一批 slate，lift 是拿它自己的分母算的。

**后果**：报告写「LEAK_shop 2.807 低于 full 2.897，店铺特征没用」。用相同 slate 重算后是 **LEAK_shop 3.014 高于 full 2.632**，配对差值 `full − LEAK_shop` = −1.905（95% CI [−3.738, −0.333]），K=50 是 −3.708（CI [−6.005, −1.651]），两个尺度都显著。结论完全反了。

顺便：你自己多产出的 `top5pct_metrics.json` 里 LEAK_shop 的 `prec_sale_ge5` = 0.291 已经高于 full 的 0.265，和报告矛盾，但没被发现。**以后任何两个口径打架，必须停下来查，不能各自写进报告。**

**改法**：slate 先一次性生成、所有组共用。

```python
def make_slates(sources, k, repeats, rng):
    uniq = [s for s in np.unique(sources) if (sources == s).sum() >= k]
    pools = {s: np.flatnonzero(sources == s) for s in uniq}
    slates = np.empty((repeats, k), dtype=np.int64)
    for i in range(repeats):
        src = uniq[rng.integers(len(uniq))]
        slates[i] = rng.choice(pools[src], size=k, replace=False)
    return slates

# 每个 k 只生成一次，然后所有组复用同一个 slates
slates = make_slates(sources, k, repeats, np.random.default_rng(SEED))
# random 组的随机打分用一个**独立**的 rng，不要动 slate 的 rng
```

**并且加一条断言，跑不过就 raise**：

```python
rands = {round(results[str(k)][n]["rand"], 9) for n in EVAL_GROUPS}
oracles = {round(results[str(k)][n]["oracle@1"], 9) for n in EVAL_GROUPS}
assert len(rands) == 1 and len(oracles) == 1, f"slate 未共用: rand={rands} oracle={oracles}"
```

### P0-2 `lift@1` 是噪声，从报告里删掉

`random` 组的 `lift@1` 按定义应恒等于 1.0，实测 0.492。`full` 的 `lift@1` 换 10 个不同 slate 种子在 **2.29 ~ 4.17** 之间跳（标准差 0.54），所以上一轮报的「K=20 是 3.785、K=50 是 1.919」纯粹是抽样运气。原因是它每个 slate 只取 1 个样本、而销量是长尾（test 里 p99.5 = 44，max = 4900），3000 次平均远不够收敛。

`lift@5` 稳定（同样 10 个种子标准差 0.15），保留。

**改法**：`lift@1` / `recovery@1` / `sales@1` 仍可存进 json，但**不许出现在 report.md 的对照表里**，避免误读。

### P0-3 主指标改成全量 top-5%（无抽样噪声）

`top5pct_metrics.json` 那套口径其实比 slate 抽样更可靠：它一次用完全部 6879 行 test，没有抽样方差。把它**升级为报告里的第一张表**，slate 的 `lift@5` 作为第二张表。

第一张表列：`prec(销量>0)`、`prec(销量≥5)`、`prec(销量≥20)`、`rec(销量≥5)`，每列后面附「相对基线的倍数」（基线：>0 是 0.2214，≥5 是 0.0740，≥20 是 0.0158）。

> 注意：这里的 ≥5 / ≥20 只是**报告口径**，训练目标仍然是连续值，不许回退成二分类。

### P0-4 漏了 winsorize

PLAN 第 4 节第 5 条要求 `y = log1p(clip(总销量, 0, p99.5))`，`p99.5` 只在 train 上算。当前代码是：

```python
df["y"] = np.log1p(df["y_raw"].astype(float))     # 没有 clip
```

test 里 p99.5 = 44 而 max = 4900，训练目标被极端值主导。补上 clip 后**需要重训全部 8 组**。请在报告里同时给出「补 winsorize 前 / 后」的对比，如果没变化就明说没变化。

---

## 必须改（P1）

### P1-1 `cat_l1` 是常量列，删掉

全部数据的 `前台分类（中文）` 一级类目都是 **家居厨房用品，占 100%**。所以 `cat_l1` 没有任何信息量，从 `CAT_COLS` 里去掉。

同时要在报告开头**显著位置**写明：这份数据只覆盖家居厨房类目，模型的适用范围仅限于此，不要当成全站选品模型用。

### P1-2 report.md 里有已作废的结论，重写

当前报告写着：

> 需求称「八天观察」，但上架时间分别为 09-09 / 09-10 / 09-11，落盘 09-11~09-12，实际窗口约 1~2 天且文件间不一致。

这是 PLAN 更新**之前**的旧结论，已被推翻。正确版本见 `PLAN_rank_products.md` 第 3 节：窗口是「**≥8 天、众数 8 天、带右尾**」（恰好 7 天占 55.2%，≤8 天占 74.9%，>8 天占 25.1%，均值 8.5 天，最长 67 天）；名为 `上架时间` 的列其实是**抓取时刻**，不是上架时刻。请照第 3 节复述，不要自己重新推断。

泄露清单里补两条（代码里确实没用这两列，做得对，但清单要记上）：

- [x] `收录时间` 未使用（非空 ⇒ 销量>0 精确率 100%，676 行全是正例）
- [x] `美区评分` 未使用（同上，90 行全是正例）

### P1-3 report.md 的结论句写清楚方向

当前写的是「LEAK_shop lift@5=2.807（诊断泄露，不可用），高于 full -0.090」——「高于 … −0.090」这种说法读不出方向。改成明确的句子，并**按下面的口径解释**（这一点上一轮理解错了，重点看）：

> `LEAK_shop` 比 `full` 高出约 14%（lift@5 3.014 vs 2.632，配对差值显著）。这**不是统计意义上的作弊**——切分已按店铺隔离，测试集的店铺模型没见过。准确的结论只有一句：**加入这四个店铺变量后，模型在这批历史数据、这个指标上预测得更准，说明店铺变量携带额外的预测信息。**
>
> 上一轮报告说「店铺特征没用」是 bug 导致的误判，这一点要更正。

> ⚠️ **本节原先还写了一句「这 14% 的差距正是大店红利的量化值 / 搬到自己店不会复现」，这是错的，已删除。** 两个模型表现的相对差异**不能解释为销量里店铺因素的因果贡献**：实验既没有观察「同一个商品换到另一家店会少卖多少」，也没有控制价格、曝光、运营。禁用店铺特征这个决定仍然正确，但理由要换成一个不需要因果假设的：**这些品最终都会进同一家店（自己的店），店铺变量对所有候选取值相同，对排序没有任何贡献。** 报告里不许出现「大店红利 = XX%」这类说法。

### P1-4 新增一项诊断：`full` 有没有间接吃到店铺规模

`full` 不含店铺列，但主图风格 / 标题写法与店铺相关，而店铺规模又与销量相关，所以 `full` 可能通过图片和标题**间接**吃到「这看着像大店拍的图」。做两个检查并写进报告：

1. test 集上 `spearman(full 的预测分, 店铺总销量)` 是多少。
2. 把 test 按 `店铺总销量` 分成低 / 中 / 高三档，分别算 `full` 的 top-5% `prec(销量≥5)`。如果三档差别不大，说明 `full` 挑品不依赖店铺规模，可以放心用；如果高档明显好，要在报告里提示「模型偏向大店的品」。

---

## 验收标准（跑完自查，每条都要在日志里打印）

1. `assert` 通过：同一个 k 下，所有对照组的 `rand` 与 `oracle@1` 完全相同。（这一条是**精确相等**，可以当硬门槛。）
2. ~~`random` 组的 `lift@5` 落在 [0.85, 1.15] 内。~~ **这条验收条件是错的，已删除。** `random` 的 lift 只在**期望**上等于 1.0，有限次抽样必然波动，长尾下波动很大——我自己那次配对评测 K=50 就跑出 0.822，用这个门槛会把正确的实现判为不合格。改成：把 `random` 的 lift 当**参考量打印出来**即可，不设区间、不许通过换随机种子去凑。
3. `y` 的构造里有 `clip(..., p99.5)`，且 `p99.5` 来自 train。
4. `cat_l1` 不在特征列表里。
5. report.md 里没有 `lift@1`，第一张表是全量 top-5%。
6. report.md 的窗口描述与 `PLAN_rank_products.md` 第 3 节一致。
7. 打印 `spearman(pred_full, 店铺总销量)` 和分档 precision。

## 输出

- 覆盖 `artifacts_v2\metrics_topk.json`、`report.md`、`top_picks.csv`
- 新增 `artifacts_v2\metrics_top5pct.json`（P0-3 的主指标表）
- 新增 `artifacts_v2\shop_scale_diagnostic.json`（P1-4）
- 保留旧结果备份成 `artifacts_v2\_round1\`，方便对比

## 顺手清理

- 根目录有 Excel 锁文件 `~$910.csv`（说明 910.csv 还在 Excel 里开着），重跑前删掉，否则读表可能失败。
- `summary.html` 不在 PLAN 里，可以留，但别当交付物。
