# -*- coding: utf-8 -*-
"""榜单主图余弦去重：同款换色/换印花只保留预测分最高的一条。"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from embed import download_urls, embed_images, image_ok, url_to_path
from embed_cache import norm_id

_URL_KEY_RE = re.compile(r"[?#]")


def _resolve_cache_dirs(cfg: dict) -> list[Path]:
    out = []
    for rel in cfg.get("image_cache_dirs", [r"D:\temu_images"]):
        p = Path(rel)
        if not p.is_absolute():
            p = (Path(__file__).resolve().parents[1] / rel).resolve()
        out.append(p)
    return out


def load_config(pkg: Path) -> dict:
    return json.loads((pkg / "config.json").read_text(encoding="utf-8"))


def _url_key(url: str) -> str:
    u = str(url or "").strip()
    if not u:
        return ""
    return _URL_KEY_RE.split(u, 1)[0]


def image_vectors_for_df(
    df: pd.DataFrame,
    cfg: dict,
    npz_path: Path | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """返回与 df 等长的 L2 归一化主图向量；无效行为 NaN。优先读 run.py 写出的 npz。"""
    n = len(df)
    X = np.full((n, 512), np.nan, dtype=np.float32)
    url_col = "主图URL" if "主图URL" in df.columns else "main_url"
    id_col = "商品ID" if "商品ID" in df.columns else "id"
    ids = df[id_col].astype(str).map(norm_id).tolist()

    if npz_path and npz_path.is_file():
        z = np.load(npz_path, allow_pickle=True)
        zids = [norm_id(str(i)) for i in z["ids"]]
        zmap = {i: v.astype(np.float32) for i, v in zip(zids, z["X"])}
        for i, pid in enumerate(ids):
            if pid in zmap:
                X[i] = zmap[pid]

    cache_dirs = _resolve_cache_dirs(cfg)
    urls_series = df[url_col].fillna("").astype(str)
    need_dl = [
        u
        for i, u in enumerate(urls_series)
        if not np.isnan(X[i]).any() and u and not image_ok(u, cache_dirs)
    ]
    need_dl = list(dict.fromkeys(need_dl))
    if need_dl:
        conc = int(cfg.get("dedupe_download_concurrency", 30))
        print(f"[dedupe] 本地无缓存，补下图 {len(need_dl)} 张 (并发 {conc}) …")
        asyncio.run(download_urls(need_dl, cache_dirs, conc))

    need_paths: list[tuple[int, Path | None]] = []
    for i, url in enumerate(urls_series):
        if not np.isnan(X[i]).any():
            continue
        if url and image_ok(url, cache_dirs):
            need_paths.append((i, url_to_path(url, cache_dirs)))
        else:
            need_paths.append((i, None))

    if need_paths:
        paths = [p for _, p in need_paths]
        vecs, _miss = embed_images(paths, batch=cfg.get("embed_batch", 32))
        for (i, _p), v in zip(need_paths, vecs):
            if np.linalg.norm(v) > 1e-8:
                X[i] = v

    ok = ~np.isnan(X[:, 0])
    if ok.any():
        nrm = np.linalg.norm(X[ok], axis=1, keepdims=True)
        X[ok] = X[ok] / np.maximum(nrm, 1e-12)
    return X, ok


def greedy_drop_indices(
    order: list[int],
    X: np.ndarray,
    ok: np.ndarray,
    threshold: float,
    url_keys: list[str] | None = None,
) -> set[int]:
    """按 order 顺序保留；与已保留向量 cos>=threshold 的丢弃。"""
    kept: list[np.ndarray] = []
    seen_urls: set[str] = set()
    dropped: set[int] = set()
    for i in order:
        ukey = url_keys[i] if url_keys else ""
        if ukey and ukey in seen_urls:
            dropped.add(i)
            continue
        if not ok[i]:
            if ukey:
                seen_urls.add(ukey)
            continue
        v = X[i]
        if not kept:
            kept.append(v)
            if ukey:
                seen_urls.add(ukey)
            continue
        sims = np.array([float(v @ u) for u in kept], dtype=np.float32)
        if sims.size and sims.max() >= threshold:
            dropped.add(i)
        else:
            kept.append(v)
            if ukey:
                seen_urls.add(ukey)
    return dropped


def visual_dup_row_indices(
    df: pd.DataFrame,
    cfg: dict,
    *,
    threshold: float = 0.92,
    scope_l1: str | None = None,
    npz_path: Path | None = None,
) -> tuple[set[int], dict]:
    """按一级+二级类目分别做主图去重（scope_l1 指定则只跑该大类下各二级）。"""
    l1_col = "一级类目" if "一级类目" in df.columns else "cat_l1"
    l2_col = "二级类目" if "二级类目" in df.columns else "cat_l2"
    base = df.copy()
    base["_score"] = pd.to_numeric(base["预测分"], errors="coerce").fillna(-1e9)
    base = base.reset_index(drop=False).rename(columns={"index": "_orig_idx"})

    if scope_l1:
        base = base[base[l1_col].astype(str) == str(scope_l1)].copy()

    X, ok = image_vectors_for_df(base, cfg, npz_path=npz_path)
    url_col = "主图URL" if "主图URL" in base.columns else "main_url"
    url_keys = [_url_key(u) for u in base[url_col].fillna("").astype(str)]

    dropped_orig: set[int] = set()
    by_group: dict[str, dict] = {}
    total_candidates = 0

    group_cols = [l1_col, l2_col]
    for key, sub in base.groupby(group_cols, sort=False):
        l1, l2 = (key if isinstance(key, tuple) else (key, ""))
        label = f"{l1}/{l2}"
        pos_order = sub.sort_values("_score", ascending=False).index.tolist()
        dropped_pos = greedy_drop_indices(
            pos_order,
            X,
            ok,
            threshold,
            url_keys=url_keys,
        )
        for p in dropped_pos:
            dropped_orig.add(int(base.at[p, "_orig_idx"]))
        by_group[label] = {
            "candidates": int(len(sub)),
            "embed_ok": int(ok[sub.index].sum()),
            "dropped": len(dropped_pos),
        }
        total_candidates += len(sub)

    stats = {
        "scope": scope_l1 or "all_l1_l2",
        "threshold": threshold,
        "candidates": total_candidates,
        "embed_ok": int(ok.sum()),
        "dropped": len(dropped_orig),
        "by_l1": by_group,
    }
    return dropped_orig, stats


def demote_rows(rows: list[dict], df: pd.DataFrame, dropped_idx: set[int]) -> set[str]:
    """把去重命中的 id 分数打到底，便于 Top5% / 分享页默认沉底。"""
    dup_ids: set[str] = set()
    for idx in dropped_idx:
        if idx not in df.index:
            continue
        dup_ids.add(str(df.at[idx, "商品ID"]))
    for r in rows:
        if str(r.get("id", "")) in dup_ids:
            r["visual_dup"] = True
            r["score"] = -1e9
    return dup_ids
