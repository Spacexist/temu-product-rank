# -*- coding: utf-8 -*-
"""审计：用完全相同的 slate 重跑对照组，并给配对 bootstrap 置信区间。

composer 的 stage_eval 把同一个 RandomState 依次传给每个对照组，
RNG 状态会往前走，导致每个组抽到的是不同的 3000 个 slate。
这里修掉：先把 slate 生成好存下来，所有组共用。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
ART = Path(__file__).resolve().parent / "artifacts_v2"
GROUPS = ("random", "price_only", "cat_only", "tab_only", "title_only", "image_only", "full", "LEAK_shop")
SEED = 42


def ndcg_at_k(gains, scores, k):
    order = np.argsort(-scores)[:k]
    disc = np.log2(np.arange(2, len(order) + 2))
    dcg = np.sum(gains[order] / disc)
    ideal = np.sort(gains)[::-1][:k]
    idcg = np.sum(ideal / np.log2(np.arange(2, len(ideal) + 2)))
    return float(dcg / idcg) if idcg > 0 else 0.0


def make_slates(sources, k, repeats, rng):
    """所有对照组共用的 slate。"""
    uniq = [s for s in np.unique(sources) if (sources == s).sum() >= k]
    pools = {s: np.flatnonzero(sources == s) for s in uniq}
    slates = np.empty((repeats, k), dtype=np.int64)
    for i in range(repeats):
        src = uniq[rng.integers(len(uniq))]
        slates[i] = rng.choice(pools[src], size=k, replace=False)
    return slates


def per_slate(sales, slates, pred, rng=None):
    """返回每个 slate 的逐条指标（不聚合），方便做配对 bootstrap。"""
    R, k = slates.shape
    out = {n: np.empty(R) for n in
           ("sales@1", "sales@5", "rand", "oracle@1", "oracle@5", "hit@1", "hit@5", "ndcg@5")}
    for i in range(R):
        idx = slates[i]
        s = sales[idx]
        g = np.log1p(s)
        p = rng.random(k) if pred is None else pred[idx]
        top1 = int(np.argmax(p))
        top5 = np.argsort(-p)[:5]
        true_top5 = set(np.argsort(-s)[:5].tolist())
        out["sales@1"][i] = s[top1]
        out["sales@5"][i] = s[top5].mean()
        out["rand"][i] = s.mean()
        out["oracle@1"][i] = s.max()
        out["oracle@5"][i] = np.sort(s)[-5:].mean()
        out["hit@1"][i] = 1.0 if top1 in true_top5 else 0.0
        out["hit@5"][i] = 1.0 if int(np.argmax(s)) in top5 else 0.0
        out["ndcg@5"][i] = ndcg_at_k(g, p, 5)
    return out


def agg(d):
    m = {kk: float(vv.mean()) for kk, vv in d.items()}
    m["lift@1"] = m["sales@1"] / m["rand"]
    m["lift@5"] = m["sales@5"] / m["rand"]
    m["recovery@1"] = m["sales@1"] / m["oracle@1"]
    m["recovery@5"] = m["sales@5"] / m["oracle@5"]
    return m


def boot_ci(num, den, n_boot=2000, seed=0):
    """对 mean(num)/mean(den) 做 bootstrap CI（按 slate 重采样，保持配对）。"""
    rng = np.random.default_rng(seed)
    R = len(num)
    vals = np.empty(n_boot)
    for b in range(n_boot):
        i = rng.integers(0, R, R)
        vals[b] = num[i].mean() / den[i].mean()
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def main():
    z = np.load(ART / "test_scores.npz", allow_pickle=True)
    sales = z["sales"].astype(float)
    sources = np.array([str(x) for x in z["source"]])
    print(f"test n={len(sales)}  销量>0 {int((sales>0).sum())} ({(sales>0).mean():.3f})  "
          f"max={sales.max():.0f}  p99.5={np.percentile(sales,99.5):.0f}")
    print(f"每文件行数: { {s:int((sources==s).sum()) for s in np.unique(sources)} }\n")

    report = {}
    for k in (20, 50):
        rng = np.random.default_rng(SEED)
        slates = make_slates(sources, k, 3000, rng)
        # 共用 slate 后，rand / oracle 对所有组必然完全相同
        rnd_rng = np.random.default_rng(SEED + 1)
        raw = {}
        for name in GROUPS:
            pred = None if name == "random" else z[f"pred_{name}"]
            raw[name] = per_slate(sales, slates, pred, rng=rnd_rng)
        report[str(k)] = {n: agg(d) for n, d in raw.items()}

        print("=" * 108)
        print(f"K={k}  3000 个 **完全相同** 的 slate")
        print(f"{'组别':<12}{'lift@1':>9}{'lift@5':>9}{'lift@5 95%CI':>22}{'rec@5':>8}{'hit@1':>8}{'hit@5':>8}{'ndcg@5':>9}")
        base = raw["tab_only"]
        for name in GROUPS:
            m = report[str(k)][name]
            lo, hi = boot_ci(raw[name]["sales@5"], raw[name]["rand"])
            print(f"{name:<12}{m['lift@1']:>9.3f}{m['lift@5']:>9.3f}"
                  f"{f'[{lo:.2f}, {hi:.2f}]':>22}{m['recovery@5']:>8.3f}"
                  f"{m['hit@1']:>8.3f}{m['hit@5']:>8.3f}{m['ndcg@5']:>9.3f}")
        print(f"  sanity: rand 对所有组是否一致 -> "
              f"{len({round(report[str(k)][n]['rand'],9) for n in GROUPS})==1}  "
              f"(rand={report[str(k)]['random']['rand']:.4f}, "
              f"oracle@1={report[str(k)]['random']['oracle@1']:.2f})")

        # 配对差值：full vs 各组，sales@5 的均值差
        print(f"\n  配对差值 mean(sales@5) 之差 [95% CI]，正数=full 更好:")
        for name in GROUPS:
            if name == "full":
                continue
            d = raw["full"]["sales@5"] - raw[name]["sales@5"]
            rng_b = np.random.default_rng(7)
            bs = np.array([d[rng_b.integers(0, len(d), len(d))].mean() for _ in range(2000)])
            lo, hi = np.percentile(bs, [2.5, 97.5])
            sig = "显著" if lo > 0 else ("显著更差" if hi < 0 else "**不显著**")
            print(f"    full - {name:<12} {d.mean():+8.3f}  [{lo:+.3f}, {hi:+.3f}]  {sig}")
        print()

    # lift@1 的不稳定性演示：换 10 个不同 slate 种子看 full 的 lift@1 波动
    print("=" * 108)
    print("lift@1 稳定性检验（K=20，full 模型，换 10 个不同 slate 种子）:")
    l1, l5 = [], []
    for sd in range(100, 110):
        rng = np.random.default_rng(sd)
        sl = make_slates(sources, 20, 3000, rng)
        d = per_slate(sales, sl, z["pred_full"])
        m = agg(d)
        l1.append(m["lift@1"])
        l5.append(m["lift@5"])
    print(f"  lift@1: {np.min(l1):.2f} ~ {np.max(l1):.2f}  (均值 {np.mean(l1):.2f}, 标准差 {np.std(l1):.2f})")
    print(f"  lift@5: {np.min(l5):.2f} ~ {np.max(l5):.2f}  (均值 {np.mean(l5):.2f}, 标准差 {np.std(l5):.2f})")

    with open(ART / "metrics_topk_paired.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n已写入 {ART / 'metrics_topk_paired.json'}")


if __name__ == "__main__":
    main()
