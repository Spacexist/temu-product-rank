# -*- coding: utf-8 -*-
"""核对几件事：观察窗口、跨表重复、标题语言、图片可用性。"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent
FILES = ["909.xlsx", "910.csv", "911.csv"]
CJK = re.compile(r"[\u4e00-\u9fff]")


def flatten(df):
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [
            str(b).strip() if not str(b).startswith("Unnamed") else str(a).strip()
            for a, b in df.columns
        ]
    return df


def load(name):
    df = flatten(pd.read_excel(ROOT / name, sheet_name="sheet", header=[0, 1]))
    df["source"] = name
    return df


def main():
    frames = [load(n) for n in FILES]
    for n, df in zip(FILES, frames):
        t = pd.to_datetime(df["上架时间"], errors="coerce")
        print(f"--- {n}: 上架 {t.min()} ~ {t.max()}  跨度 {(t.max()-t.min())}")
        sale = pd.to_numeric(df["总销量"], errors="coerce").fillna(0)
        print(f"    总销量 >0 比例 {(sale>0).mean():.3f}  >=5 {(sale>=5).mean():.3f} "
              f">=20 {(sale>=20).mean():.3f} >=50 {(sale>=50).mean():.3f}")
        # 标题语言
        te = df["商品标题（英文）"].astype(str)
        cjk_frac = te.map(lambda s: len(CJK.findall(s)) / max(len(s), 1))
        print(f"    '英文'标题里含中文的比例 {(cjk_frac>0.05).mean():.3f}")
        print(f"    有中文标题 {df['商品标题（中文）'].notna().mean():.3f}")

    all_df = pd.concat(frames, ignore_index=True)
    print("\n=== 跨表 ===")
    print("总行", len(all_df), "唯一商品ID", all_df["商品ID"].nunique())
    dup = all_df["商品ID"].duplicated(keep=False)
    print("跨表重复商品ID行数", int(dup.sum()))
    if dup.sum():
        d = all_df[dup].sort_values("商品ID")
        print(d.groupby("商品ID")["source"].apply(lambda s: "|".join(sorted(s))).value_counts().head())
    print("唯一店铺ID", all_df["店铺ID"].nunique())
    per_shop = all_df.groupby("店铺ID").size()
    print("每店商品数: mean %.2f median %.0f max %d" % (per_shop.mean(), per_shop.median(), per_shop.max()))
    # 同店多品占比
    print("落在 >=2 品店铺的行占比 %.3f" % (per_shop[per_shop >= 2].sum() / per_shop.sum()))
    # 主图重复
    main_img = all_df["商品主图"].astype(str).str.extract(r"(https?://[^\s\],>]+)")[0]
    print("主图URL唯一", main_img.nunique(), "重复行", int(main_img.duplicated(keep=False).sum()))
    # 标题重复
    t = all_df["商品标题（英文）"].astype(str).str.strip()
    print("标题唯一", t.nunique(), "重复行", int(t.duplicated(keep=False).sum()))
    # 店铺总销量 与 商品销量 相关性（说明为什么会背店铺）
    s = pd.to_numeric(all_df["店铺总销量"], errors="coerce")
    y = pd.to_numeric(all_df["总销量"], errors="coerce").fillna(0)
    m = s.notna()
    print("店铺总销量 vs 商品销量 spearman = %.3f" % s[m].corr(y[m], method="spearman"))


if __name__ == "__main__":
    main()
