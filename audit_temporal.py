# -*- coding: utf-8 -*-
"""核对时间外推结论：把「按店铺切分」的旧模型限定到 911 上重算，做同population对比；并给置信区间。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from scipy.stats import beta

sys.stdout.reconfigure(encoding="utf-8")
ART = Path(__file__).resolve().parent / "artifacts_v2"


def ci(hits, n, a=0.05):
    """精确二项 CI。"""
    lo = beta.ppf(a / 2, hits, n - hits + 1) if hits > 0 else 0.0
    hi = beta.ppf(1 - a / 2, hits + 1, n - hits) if hits < n else 1.0
    return lo, hi


def top5(sales, pred, label=""):
    n = len(sales)
    k = int(round(n * 0.05))
    top = np.argsort(-pred)[:k]
    out = {"n": n, "k": k}
    for name, thr in [("P(>0)", 0), ("P(>=5)", 4), ("P(>=20)", 19)]:
        base = float((sales > thr).mean())
        hits = int((sales[top] > thr).sum())
        p = hits / k
        lo, hi = ci(hits, k)
        out[name] = dict(base=base, prec=p, mult=p / base if base else float("nan"),
                         mult_lo=lo / base if base else float("nan"),
                         mult_hi=hi / base if base else float("nan"), hits=hits)
    return out


def show(tag, r):
    print(f"\n{tag}   (n={r['n']}, 取前 5% = {r['k']} 个)")
    print(f"  {'指标':<10}{'基线':>8}{'精确率':>9}{'×基线':>8}{'×基线 95%CI':>20}")
    for name in ("P(>0)", "P(>=5)", "P(>=20)"):
        d = r[name]
        print(f"  {name:<10}{d['base']:>8.3f}{d['prec']:>9.3f}{d['mult']:>8.2f}"
              f"{f'[{d[chr(109)+chr(117)+chr(108)+chr(116)+chr(95)+chr(108)+chr(111)]:.2f}, {d[chr(109)+chr(117)+chr(108)+chr(116)+chr(95)+chr(104)+chr(105)]:.2f}]':>20}")


# ---- 旧模型（按店铺切分，含 source 特征）----
z = np.load(ART / "test_scores.npz", allow_pickle=True)
sales_old = z["sales"].astype(float)
pred_old = z["pred_full"]
src_old = np.array([str(x) for x in z["source"]])

print("=" * 88)
print("对比 A：按店铺切分的旧模型 —— 全部 test（现有报告口径）")
show("shop-split / 全部三天", top5(sales_old, pred_old))

print("\n" + "=" * 88)
print("对比 B：同一个旧模型，只看它 test 里的 911 那部分（population 与时间外推一致）")
m = src_old == "911.csv"
show("shop-split / 仅 911", top5(sales_old[m], pred_old[m]))

# ---- 新模型（按天切分，无 source 特征）----
tm = json.loads((ART / "temporal_metrics.json").read_text(encoding="utf-8"))
print("\n" + "=" * 88)
print("对比 C：按天切分（composer 本次结果，直接读 temporal_metrics.json）")
print(json.dumps(tm, ensure_ascii=False, indent=2)[:1800])

# ---- source 特征在旧模型里到底有多重要 ----
print("\n" + "=" * 88)
print("检查：旧模型是否含 source 特征、新模型是否去掉了")
rp = (Path(__file__).resolve().parent / "rank_products.py").read_text(encoding="utf-8")
vt = (Path(__file__).resolve().parent / "validate_temporal.py").read_text(encoding="utf-8")
for tag, txt in [("rank_products.py", rp), ("validate_temporal.py", vt)]:
    hits = [l.strip() for l in txt.splitlines() if "CAT_COLS" in l and "=" in l and "for" not in l]
    print(f"  {tag}: {hits[:2]}")

# ---- 三天各自的基线，看 911 是否天然更好挑 ----
print("\n" + "=" * 88)
print("各 source 在旧 test 里的基线与旧模型表现（说明 911 本身难度是否不同）")
for s in np.unique(src_old):
    mm = src_old == s
    r = top5(sales_old[mm], pred_old[mm])
    print(f"  {s:<12} n={r['n']:<5} 基线(>0)={r['P(>0)']['base']:.3f}  "
          f"×基线={r['P(>0)']['mult']:.2f}  ×基线(≥5)={r['P(>=5)']['mult']:.2f}")
