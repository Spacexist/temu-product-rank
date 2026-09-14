# -*- coding: utf-8 -*-
"""只看表：列名、时间跨度、销量分布。不建模。"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent
FILES = ["909.xlsx", "910.csv", "911.csv"]


def flatten(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [
            str(b).strip() if not str(b).startswith("Unnamed") else str(a).strip()
            for a, b in df.columns
        ]
    return df


def main():
    for name in FILES:
        xl = pd.ExcelFile(ROOT / name)
        print("=" * 100)
        print(name, "sheets:", xl.sheet_names)
        df = flatten(pd.read_excel(ROOT / name, sheet_name=xl.sheet_names[0], header=[0, 1]))
        print("shape:", df.shape)
        print("列:")
        for i, c in enumerate(df.columns):
            nn = df[c].notna().sum()
            sample = df[c].dropna().head(1).tolist()
            s = str(sample[0])[:60] if sample else ""
            print(f"  [{i:2d}] {c!r:34s} nonnull={nn:6d}  e.g. {s}")
        # 时间相关列
        time_cols = [c for c in df.columns if any(k in str(c) for k in ("时间", "日期", "上架", "天"))]
        print("时间类列:", time_cols)
        for c in time_cols:
            v = df[c].dropna()
            print(f"  {c}: n={len(v)} min={v.min()} max={v.max()} nunique={v.nunique()}")
            print("   top:", v.value_counts().head(5).to_dict())
        for c in df.columns:
            if "销量" in str(c) or "GMV" in str(c) or "销售额" in str(c):
                v = pd.to_numeric(df[c], errors="coerce").dropna()
                if len(v):
                    print(
                        f"  {c}: n={len(v)} zero={int((v==0).sum())} >0={int((v>0).sum())} "
                        f"max={v.max()} q50={v.quantile(.5)} q90={v.quantile(.9)} q99={v.quantile(.99)}"
                    )


if __name__ == "__main__":
    main()
