# -*- coding: utf-8 -*-
"""把 top5% 的「精确率基线」和「召回率基线」摆在一起，说明 22% 和 5% 各是什么。"""
import sys

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
z = np.load("artifacts_v2/test_scores.npz", allow_pickle=True)
sales = z["sales"].astype(float)
pred = z["pred_full"]

n = len(sales)
k = int(round(n * 0.05))
sellers = int((sales > 0).sum())
base = sellers / n

top = np.argsort(-pred)[:k]
hit_model = int((sales[top] > 0).sum())
hit_random = base * k  # 随机挑 k 个的期望命中数

print(f"测试集总品数          n = {n}")
print(f"其中「卖出过」的       = {sellers}  占 {base:.1%}   <-- 这就是 22%")
print(f"允许挑的数量 top5%    k = {k}")
print()
print(f"{'':<22}{'挑中的好品数':>14}{'精确率(好品/挑出)':>20}{'召回率(好品/全部好品)':>24}")
print(f"{'随机挑 344 个':<22}{hit_random:>14.0f}{hit_random / k:>20.1%}{hit_random / sellers:>24.1%}")
print(f"{'模型挑 344 个':<22}{hit_model:>14d}{hit_model / k:>20.1%}{hit_model / sellers:>24.1%}")
print(f"{'倍数':<22}{'':>14}{hit_model / hit_random:>20.2f}x{hit_model / hit_random:>23.2f}x")
print()
print("看右下角：随机的召回率 = 344/6879 = %.1f%%  <-- 这就是你想的那个 5%%" % (k / n * 100))
print("因为随机抽走全部品的 5%%，自然只能网住全部好品的 5%%。")
