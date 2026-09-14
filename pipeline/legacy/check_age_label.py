# -*- coding: utf-8 -*-
"""测试「按曝光天数归一化 label」这个想法是否成立。"""
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
TODAY = pd.Timestamp("2026-09-12")


def flat(df):
    df = df.copy()
    df.columns = [
        str(b).strip() if not str(b).startswith("Unnamed") else str(a).strip()
        for a, b in df.columns
    ]
    return df


frames = []
for n in ["909.xlsx", "910.csv", "911.csv"]:
    d = flat(pd.read_excel(n, sheet_name="sheet", header=[0, 1]))
    d["source"] = n
    frames.append(d)
df = pd.concat(frames, ignore_index=True)

df["crawl"] = pd.to_datetime(df["上架时间"], errors="coerce")
has = df["收录时间"].notna()
df.loc[has, "listed"] = pd.to_datetime(
    df.loc[has, "收录时间"].astype("int64").astype(str), format="%Y%m%d"
)
df["sales"] = pd.to_numeric(df["总销量"], errors="coerce").fillna(0)
df["age_at_crawl"] = (df["crawl"].dt.normalize() - df["listed"]).dt.days
df["age_to_today"] = (TODAY - df["listed"]).dt.days

sub = df[has].copy()
print("=== 1. 曝光天数(抓取时) 分布 —— 只有 %d 行可算 (%.2f%%) ===" % (len(sub), len(sub) / len(df) * 100))
for src, g in sub.groupby("source"):
    vc = g["age_at_crawl"].value_counts().sort_index()
    print(f"  {src}: n={len(g)}  {dict(vc)}")
print("  全体: 恰好7天占 %.1f%%  <=8天占 %.1f%%  >8天占 %.1f%%  均值 %.1f  p95 %.0f" % (
    (sub.age_at_crawl == 7).mean() * 100,
    (sub.age_at_crawl <= 8).mean() * 100,
    (sub.age_at_crawl > 8).mean() * 100,
    sub.age_at_crawl.mean(),
    sub.age_at_crawl.quantile(0.95),
))

print("\n=== 2. 曝光天数 与 销量 真的相关吗? (若≈0 则归一化无意义) ===")
print("  全体 spearman(age_at_crawl, sales) = %.4f  (n=%d)"
      % (sub.age_at_crawl.corr(sub.sales, method="spearman"), len(sub)))
for src, g in sub.groupby("source"):
    print(f"  {src}: spearman = {g.age_at_crawl.corr(g.sales, method='spearman'):+.4f}  n={len(g)}")
print("  分桶看销量中位数/均值/>0率:")
bins = [6, 7, 8, 10, 14, 1000]
sub["bucket"] = pd.cut(sub.age_at_crawl, bins=bins)
print(sub.groupby("bucket", observed=True).agg(
    n=("sales", "size"), 销量均值=("sales", "mean"),
    销量中位=("sales", "median"), 大于0率=("sales", lambda s: (s > 0).mean())
).round(3).to_string())

print("\n=== 3. 有/无 收录时间 的行 销量是否可比 (决定能否只对2%的行用新label) ===")
for name, g in [("有收录时间", df[has]), ("无收录时间", df[~has])]:
    print("  %s: n=%5d  >0率 %.3f  均值 %.2f  中位 %.0f  p90 %.0f"
          % (name, len(g), (g.sales > 0).mean(), g.sales.mean(), g.sales.median(), g.sales.quantile(0.9)))

print("\n=== 4. 换成 log1p(sales)/(age_to_today+1) 后, 排序变了多少? ===")
sub["y_old"] = np.log1p(sub.sales)
sub["y_new"] = np.log1p(sub.sales) / (sub.age_to_today + 1)
print("  全体 spearman(y_old, y_new) = %.4f" % sub.y_old.corr(sub.y_new, method="spearman"))
for src, g in sub.groupby("source"):
    print("  %s 文件内 spearman(y_old, y_new) = %.4f  (age_to_today 取值 %s)"
          % (src, g.y_old.corr(g.y_new, method="spearman"),
             dict(g.age_to_today.value_counts().sort_index().head(6))))

print("\n=== 5. 若用 crawl-8天 反推 listed (给全部3万行), 分母会是什么 ===")
df["age_imputed"] = (TODAY - (df["crawl"].dt.normalize() - pd.Timedelta(days=8))).dt.days
print(df.groupby("source")["age_imputed"].value_counts().sort_index().to_string())
