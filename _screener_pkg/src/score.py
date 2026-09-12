# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import pickle
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def load_meta(model_dir: Path) -> dict:
    return json.loads((model_dir / "meta.json").read_text(encoding="utf-8"))


def booster_path(model_dir: Path, ascii_fallback: str) -> str:
    fb = Path(ascii_fallback or r"F:\Clip\screener_lgb_export\lgbm_full.txt")
    fb.parent.mkdir(parents=True, exist_ok=True)
    p = model_dir / "lgbm_full.txt"
    if p.is_file():
        if not fb.is_file() or fb.stat().st_mtime < p.stat().st_mtime:
            shutil.copy2(p, fb)
    if not fb.is_file():
        raise SystemExit(f"缺少模型文件 {fb}")
    return str(fb)


def build_matrix(
    tab: pd.DataFrame, img: np.ndarray, txt: np.ndarray, feature_names: list[str]
) -> pd.DataFrame:
    img_df = pd.DataFrame(img, columns=[f"img_{i}" for i in range(img.shape[1])])
    txt_df = pd.DataFrame(txt, columns=[f"txt_{i}" for i in range(txt.shape[1])])
    X = pd.concat([tab.reset_index(drop=True), img_df, txt_df], axis=1)
    missing = [c for c in feature_names if c not in X.columns]
    extra = [c for c in X.columns if c not in feature_names]
    if missing:
        raise SystemExit(f"特征缺列: {missing[:8]}… 共 {len(missing)}")
    if extra:
        X = X.drop(columns=extra)
    X = X[feature_names]
    return X


def predict(
    tab: pd.DataFrame,
    img: np.ndarray,
    txt: np.ndarray,
    model_dir: Path,
    config: dict,
) -> np.ndarray:
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    names = json.loads((model_dir / "feature_names.json").read_text(encoding="utf-8"))
    X = build_matrix(tab, img, txt, names)
    path = booster_path(model_dir, config.get("lgb_model_ascii_fallback", ""))
    if not np.isfinite(X.select_dtypes(include=[np.number]).to_numpy()).all():
        raise SystemExit("特征矩阵含 NaN/Inf")
    return _predict_subprocess_df(X, path)


def _predict_subprocess_df(X: pd.DataFrame, model_path: str) -> np.ndarray:
    """Torch 与 LightGBM 同进程在部分 Windows 上会 access violation；用 pandas 类别在子进程预测。"""
    tmp = Path(r"F:\Clip\screener_predict_tmp")
    tmp.mkdir(parents=True, exist_ok=True)
    x_path = tmp / "X.pkl"
    y_path = tmp / "y.npy"
    with open(x_path, "wb") as f:
        pickle.dump(X, f)
    script = f"""
import pickle, numpy as np, lightgbm as lgb, os
os.environ["OMP_NUM_THREADS"] = "1"
with open(r"{x_path}", "rb") as f:
    X = pickle.load(f)
b = lgb.Booster(model_file=r"{model_path}")
np.save(r"{y_path}", b.predict(X))
"""
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = "1"
    subprocess.run([sys.executable, "-c", script], check=True, env=env)
    return np.load(y_path).astype(np.float64)
