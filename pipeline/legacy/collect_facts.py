# -*- coding: utf-8 -*-
"""收集写报告需要的全部精确数字与环境信息。"""
from __future__ import annotations

import json
import platform
import sys
from pathlib import Path

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent
ART = ROOT / "artifacts_v2"

print("=" * 90)
print("[环境]")
print("  python:", sys.version.split()[0], "|", sys.executable)
print("  platform:", platform.platform())
import torch
print("  torch:", torch.__version__, "cuda_available:", torch.cuda.is_available())
if torch.cuda.is_available():
    p = torch.cuda.get_device_properties(0)
    print(f"  gpu: {p.name}  {p.total_memory/1024**3:.2f} GiB  cc{p.major}.{p.minor}")
for m in ["torchvision", "transformers", "sentence_transformers", "lightgbm", "sklearn",
          "pandas", "numpy", "scipy", "openpyxl", "aiohttp", "PIL"]:
    try:
        mod = __import__(m)
        print(f"  {m}: {getattr(mod,'__version__','?')}")
    except Exception as e:
        print(f"  {m}: MISS")

print("=" * 90)
print("[特征矩阵形状]")
for f in ["img.npz", "txt.npz"]:
    z = np.load(ART / f, allow_pickle=True)
    print(f"  {f}: X={z['X'].shape} dtype={z['X'].dtype} ids={z['ids'].shape}")
    x = z["X"]
    print(f"      L2范数 均值={np.linalg.norm(x,axis=1).mean():.4f}  值域[{x.min():.3f}, {x.max():.3f}]")

print("=" * 90)
for f in ["split.json", "models_meta.json", "metrics_top5pct.json",
          "shop_scale_diagnostic.json", "train_pos_rate.json"]:
    p = ART / f
    if p.exists():
        print(f"[{f}]")
        print(json.dumps(json.loads(p.read_text(encoding="utf-8")), ensure_ascii=False, indent=2))
        print("-" * 90)

print("=" * 90)
print("[temporal_metrics.json 完整]")
print(json.dumps(json.loads((ART / "temporal_metrics.json").read_text(encoding="utf-8")),
                 ensure_ascii=False, indent=2))
