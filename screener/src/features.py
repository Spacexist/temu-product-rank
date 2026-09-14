# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def load_te(model_dir: Path) -> dict:
    return json.loads((model_dir / "cat_l2_te.json").read_text(encoding="utf-8"))


def apply_cat_l2_te(df: pd.DataFrame, te: dict) -> pd.Series:
    global_mean = float(te["_global"])
    m = float(te.get("m", 20))
    mapping = {k: v for k, v in te.items() if k not in ("_global", "m")}
    out = df["cat_l2"].astype(str).map(mapping)
    return out.fillna(global_mean).astype(float)


def apply_inference_source(df: pd.DataFrame, source: str) -> pd.DataFrame:
    out = df.copy()
    out["source"] = source
    return out


def tab_matrix(df: pd.DataFrame, meta: dict) -> pd.DataFrame:
    cols = list(meta["NUM_TAB_COLS"])
    X = df[cols].copy()
    for c in meta["CAT_COLS"]:
        X[c] = df[c]
    return X


def overlay_embedded_tab(df: pd.DataFrame, art_dir: Path, meta: dict) -> pd.DataFrame:
    """与实验场 dataset_embedded 对齐表格列（命中缓存的 SKU）。"""
    emb_path = art_dir / "dataset_embedded.csv"
    if not emb_path.is_file():
        return df
    emb = pd.read_csv(emb_path, encoding="utf-8-sig", dtype={"商品ID": str})
    emb = emb.drop_duplicates("商品ID", keep="first").set_index("商品ID")
    out = df.copy()
    hit = out["商品ID"].isin(emb.index)
    if not hit.any():
        return out
    cols = [c for c in meta["NUM_TAB_COLS"] if c != "cat_l2_te"] + ["cat_l2"]
    for col in cols:
        if col in emb.columns:
            out.loc[hit, col] = out.loc[hit, "商品ID"].map(emb[col])
    return out


def cast_categories(X: pd.DataFrame, meta: dict) -> pd.DataFrame:
    out = X.copy()
    out["cat_l2"] = pd.Categorical(
        out["cat_l2"].astype(str), categories=meta["cat_l2_categories"]
    )
    out["source"] = pd.Categorical(
        out["source"].astype(str), categories=meta["source_categories"]
    )
    return out
