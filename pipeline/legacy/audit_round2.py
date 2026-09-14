# -*- coding: utf-8 -*-
"""第 2 轮独立核对 + 两篇 review 里未查清的一件事：丢图是否与 label 相关。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
ART = Path(__file__).resolve().parent / "artifacts_v2"

# ---- 1. 共用 slate 是否真的生效 ----
m = json.loads((ART / "metrics_topk.json").read_text(encoding="utf-8"))
print("=== 1. 共用 slate 断言核对（rand / oracle@1 必须全组相同）===")
for k, groups in m.items():
    gs = {n: v for n, v in groups.items() if isinstance(v, dict)}
    rands = {round(v["rand"], 9) for v in gs.values()}
    orac = {round(v["oracle@1"], 9) for v in gs.values()}
    print(f"  K={k}: rand 取值数={len(rands)} {rands}  oracle@1 取值数={len(orac)}")
    print(f"        random lift@5 = {gs['random']['lift@5']:.4f}  "
          f"full lift@5 = {gs['full']['lift@5']:.4f}  LEAK = {gs['LEAK_shop']['lift@5']:.4f}")
    print(f"        full ndcg@5={gs['full']['ndcg@5']:.4f}  "
          f"title={gs['title_only']['ndcg@5']:.4f}  image={gs['image_only']['ndcg@5']:.4f}  "
          f"tab={gs['tab_only']['ndcg@5']:.4f}")
    print(f"        full hit@5={gs['full']['hit@5']:.4f}  "
          f"title={gs['title_only']['hit@5']:.4f}  image={gs['image_only']['hit@5']:.4f}")

# ---- 2. lift@5 是否被极端值主导 ----
print("\n=== 2. lift@5 的长尾依赖：把销量截到 p99.5(=46) 后重算，看排名是否翻转 ===")
z = np.load(ART / "test_scores.npz", allow_pickle=True)
sales = z["sales"].astype(float)
sources = np.array([str(x) for x in z["source"]])
GROUPS = ("random", "price_only", "cat_only", "tab_only", "title_only", "image_only", "full", "LEAK_shop")


def slates(k, R, seed):
    rng = np.random.default_rng(seed)
    uniq = [s for s in np.unique(sources) if (sources == s).sum() >= k]
    pools = {s: np.flatnonzero(sources == s) for s in uniq}
    out = np.empty((R, k), dtype=np.int64)
    for i in range(R):
        out[i] = rng.choice(pools[uniq[rng.integers(len(uniq))]], size=k, replace=False)
    return out


def lift5(sl, pred, sal, rng=None):
    num, den = [], []
    for idx in sl:
        s = sal[idx]
        p = rng.random(len(idx)) if pred is None else pred[idx]
        num.append(s[np.argsort(-p)[:5]].mean())
        den.append(s.mean())
    return float(np.mean(num) / np.mean(den))


cap = float(np.percentile(sales, 99.5))
sl = slates(20, 3000, 42)
print(f"  截尾点 p99.5 = {cap:.0f}（原始 max = {sales.max():.0f}）")
print(f"  {'组别':<12}{'lift@5 原始':>14}{'lift@5 截尾后':>15}")
for n in GROUPS:
    pred = None if n == "random" else z[f"pred_{n}"]
    r = np.random.default_rng(7)
    a = lift5(sl, pred, sales, r)
    r = np.random.default_rng(7)
    b = lift5(sl, pred, np.minimum(sales, cap), r)
    print(f"  {n:<12}{a:>14.3f}{b:>15.3f}")

# ---- 3. 丢图是否与 label 相关（两篇 review 都没查清）----
print("\n=== 3. 丢图行的销量分布：主图下载失败是否偏向零销量 ===")
ds = pd.read_csv(ART / "dataset.csv", encoding="utf-8-sig", dtype={"商品ID": str}, low_memory=False)
emb_ids = set(str(x) for x in np.load(ART / "img.npz", allow_pickle=True)["ids"])
ds["有图"] = ds["商品ID"].isin(emb_ids)
s = pd.to_numeric(ds["总销量"], errors="coerce").fillna(0)
for name, mask in [("有图(进入建模)", ds["有图"]), ("无图(被丢弃)", ~ds["有图"])]:
    g = s[mask]
    print(f"  {name}: n={len(g):6d}  >0率 {(g > 0).mean():.4f}  中位 {g.median():.0f}  均值 {g.mean():.2f}")
tot = (~ds["有图"]).sum()
print(f"  被丢弃 {tot} 行（占 {tot / len(ds) * 100:.2f}%）")
if tot:
    from scipy.stats import fisher_exact
    a = int(((s > 0) & ds["有图"]).sum()); b = int(((s == 0) & ds["有图"]).sum())
    c = int(((s > 0) & ~ds["有图"]).sum()); d = int(((s == 0) & ~ds["有图"]).sum())
    odds, p = fisher_exact([[a, b], [c, d]])
    print(f"  Fisher 精确检验 odds={odds:.3f} p={p:.4g}  -> "
          f"{'丢图与销量显著相关，存在选择偏差' if p < 0.05 else '未见显著关联，选择偏差可忽略'}")

# ---- 4. source 是否还在特征里 ----
print("\n=== 4. source 特征（部署时必然是未见类别）===")
src = Path(__file__).resolve().parent / "rank_products.py"
txt = src.read_text(encoding="utf-8")
for line in txt.splitlines():
    if "CAT_COLS" in line and "=" in line:
        print("  " + line.strip())

# ---- 5. 时间外推：按天切分是否做过 ----
print("\n=== 5. 训练/测试是否做过按天切分 ===")
print("  split.json:", (ART / "split.json").read_text(encoding="utf-8").replace("\n", " "))
print("  测试集里三个 source 的行数:", {s_: int((sources == s_).sum()) for s_ in np.unique(sources)})
print("  -> 三天混在一起按店铺切，未验证「用前两天训练、挑第三天新品」")
