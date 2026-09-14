import pandas as pd
from pathlib import Path

p = Path(r"C:\Users\ZFGJ-WCH\Desktop\8天前数据\_screener_pkg\output\912_无收录_去重训练库_无违禁_scored.csv")
df = pd.read_csv(p, encoding="utf-8-sig", dtype={"商品ID": str})
n = len(df)
k = max(1, int(n * 0.05))
top = df.sort_values("排名").head(k)
out = p.with_name("912_纯新品_Top5pct.csv")
top.to_csv(out, index=False, encoding="utf-8-sig")
print("n_total", n, "top5pct_n", k)
print("score", float(top["预测分"].min()), float(top["预测分"].max()))
print("out", out)
for _, r in top.head(15).iterrows():
    print(int(r["排名"]), f"{r['预测分']:.3f}", f"${r.get('美元价格', 0):.2f}", str(r["标题"])[:45])
