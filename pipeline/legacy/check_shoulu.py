# -*- coding: utf-8 -*-
"""收录时间 的覆盖率与取值分布。"""
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


for n in ["909.xlsx", "910.csv", "911.csv"]:
    d = flat(pd.read_excel(n, sheet_name="sheet", header=[0, 1]))
    c = d["收录时间"]
    up = pd.to_datetime(d["上架时间"], errors="coerce")
    nn = int(c.notna().sum())
    print(f"{n}: 有收录时间 {nn}/{len(d)} = {nn / len(d) * 100:.2f}%")
    v = pd.to_datetime(c.dropna().astype("int64").astype(str), format="%Y%m%d")
    print("   取值分布:", {str(k.date()): int(x) for k, x in v.value_counts().sort_index().items()})
    sub_up = up[c.notna()]
    print("   这些行的上架时间:", sub_up.min(), "~", sub_up.max())
    diff = (sub_up.dt.normalize().values - v.values) / pd.Timedelta(days=1)
    print(f"   上架 - 收录 天数: min={diff.min():.0f} median={pd.Series(diff).median():.0f} max={diff.max():.0f}")
    print(f"   收录早于上架的行: {int((diff > 0).sum())}/{nn}")
