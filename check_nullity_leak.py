# -*- coding: utf-8 -*-
"""检查「某列非空」本身是否泄露 label。"""
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")


def flat(df):
    df = df.copy()
    df.columns = [
        str(b).strip() if not str(b).startswith("Unnamed") else str(a).strip()
        for a, b in df.columns
    ]
    return df


fr = []
for n in ["909.xlsx", "910.csv", "911.csv"]:
    d = flat(pd.read_excel(n, sheet_name="sheet", header=[0, 1]))
    d["source"] = n
    fr.append(d)
df = pd.concat(fr, ignore_index=True)
s = pd.to_numeric(df["总销量"], errors="coerce").fillna(0)
base = (s > 0).mean()
print(f"基线: 全体销量>0 占 {base:.4f}  (n={len(df)})\n")
print(f"{'列名':<16} {'非空行数':>8} {'非空->销量>0':>12} {'提升倍数':>8}")
for c in df.columns:
    m = df[c].notna()
    if 0 < m.sum() < len(df):
        p = (s[m] > 0).mean()
        flag = "  <== 非空即泄露" if p > 0.99 else ""
        print(f"{str(c):<16} {int(m.sum()):>8} {p:>12.4f} {p / base:>8.2f}{flag}")
