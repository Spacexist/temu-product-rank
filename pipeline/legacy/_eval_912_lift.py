# -*- coding: utf-8 -*-
import json
import numpy as np
import pandas as pd
from pathlib import Path
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parent
p = ROOT / "_screener_pkg/output/912_无收录_去重训练库_无违禁_scored.csv"
df = pd.read_csv(p, encoding="utf-8-sig", dtype={"商品ID": str})
y = pd.to_numeric(df["总销量"], errors="coerce").fillna(0).values
pred = df["预测分"].astype(float).values
n = len(df)
k = max(1, int(n * 0.05))

def metrics_at_top(order_idx):
    top = order_idx[:k]
    def prec(th):
        return float((y[top] >= th).mean())
    base = {0: (y > 0).mean(), 5: (y >= 5).mean(), 20: (y >= 20).mean()}
    p0, p5, p20 = prec(1), prec(5), prec(20)
    return {
        "base_gt0": base[0],
        "base_ge5": base[5],
        "base_ge20": base[20],
        "prec_gt0": p0,
        "prec_ge5": p5,
        "prec_ge20": p20,
        "lift_gt0": p0 / base[0] if base[0] else 0,
        "lift_ge5": p5 / base[5] if base[5] else 0,
        "lift_ge20": p20 / base[20] if base[20] else 0,
    }

rng = np.random.default_rng(42)
rand_idx = rng.permutation(n)
model_idx = np.argsort(-pred)
m_rand = metrics_at_top(rand_idx)
m_full = metrics_at_top(model_idx)
sp, _ = spearmanr(pred, y)

ref = json.loads((ROOT / "artifacts_v2/temporal_metrics.json").read_text(encoding="utf-8"))
t911 = next(r for r in ref["main"]["table"] if r["group"] == "full")
shop = ref["reference_shop_split_full"]

print(f"n={n} top_k={k}")
print("---912 纯新品池 基线---")
print(f"  动销>0 {m_full['base_gt0']*100:.1f}%  >=5 {m_full['base_ge5']*100:.1f}%  >=20 {m_full['base_ge20']*100:.2f}%")
print(f"  Spearman(预测分,销量) {sp:.3f}")
print("---Top5% ×基线 (vs 本池随机Top5%)---")
print(f"  随机  P>0× {m_rand['lift_gt0']:.2f}  P>=5× {m_rand['lift_ge5']:.2f}  P>=20× {m_rand['lift_ge20']:.2f}")
print(f"  模型  P>0× {m_full['lift_gt0']:.2f}  P>=5× {m_full['lift_ge5']:.2f}  P>=20× {m_full['lift_ge20']:.2f}")
print("---对照 911 时间外推 full Top5%---")
print(f"  P>0× {t911['lift_gt0']:.2f}  P>=5× {t911['lift_ge5']:.2f}  P>=20× {t911['lift_ge20']:.2f}")
print("---对照 站内 shop 切分 full (乐观)---")
print(f"  P>0× {shop['prec_sale_gt0_lift_vs_base']:.2f}  P>=5× {shop['prec_sale_ge5_lift_vs_base']:.2f}")
ratio = m_full["lift_gt0"] / t911["lift_gt0"] if t911["lift_gt0"] else 0
print(f"---相对911外推: 动销×基线约为 {ratio*100:.0f}%---")
