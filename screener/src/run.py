# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG / "src"))

from embed import (  # noqa: E402
    download_urls,
    embed_images,
    embed_texts,
    image_ok,
    url_to_path,
)
from embed_cache import load_pair, norm_id  # noqa: E402
from features import (  # noqa: E402
    apply_cat_l2_te,
    apply_inference_source,
    cast_categories,
    load_te,
    overlay_embedded_tab,
    tab_matrix,
)
from read_table import read_input  # noqa: E402
from score import load_meta, predict  # noqa: E402
from word_filter import apply_banned, load_words, log_stats  # noqa: E402


def load_config() -> dict:
    return json.loads((PKG / "config.json").read_text(encoding="utf-8"))


def resolve_art_dir(cfg: dict) -> Path | None:
    raw = cfg.get("embed_cache_art_dir")
    if not raw:
        return None
    p = Path(raw)
    if not p.is_absolute():
        p = (PKG / p).resolve()
    return p


def resolve_npz_dir(cfg: dict) -> Path | None:
    raw = cfg.get("npz_dir")
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def resolve_cache_dirs(cfg: dict) -> list[Path]:
    out = []
    for rel in cfg.get("image_cache_dirs", ["cache/images"]):
        p = (PKG / rel).resolve()
        p.mkdir(parents=True, exist_ok=True)
        out.append(p)
    return out


def uncached_image_urls(df: pd.DataFrame, img_map: dict[str, np.ndarray] | None) -> list[str]:
    """只返回没有图片向量缓存的商品主图 URL，避免预测阶段重复下载。"""
    if not img_map:
        urls = df["main_url"].fillna("").astype(str).unique().tolist()
        return [u for u in urls if u]
    work = df.copy()
    work["_pid_norm"] = work["商品ID"].astype(str).map(norm_id)
    miss = work[~work["_pid_norm"].isin(img_map)]
    urls = miss["main_url"].fillna("").astype(str).unique().tolist()
    return [u for u in urls if u]


def fill_partial_from_cache(
    ids: list[str],
    img_map: dict[str, np.ndarray],
    txt_map: dict[str, np.ndarray],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """分别填充图片/文本向量缓存，并分别返回缺失掩码。"""
    n = len(ids)
    X_img = np.zeros((n, 512), dtype=np.float32)
    X_txt = np.zeros((n, 512), dtype=np.float32)
    img_miss = np.ones(n, dtype=bool)
    txt_miss = np.ones(n, dtype=bool)
    for i, raw_pid in enumerate(ids):
        pid = norm_id(raw_pid)
        if pid in img_map:
            X_img[i] = img_map[pid]
            img_miss[i] = False
        if pid in txt_map:
            X_txt[i] = txt_map[pid]
            txt_miss[i] = False
    return X_img, X_txt, img_miss, txt_miss


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="xlsx/csv 日报")
    ap.add_argument("--skip-download", action="store_true")
    ap.add_argument("--self-test", action="store_true", help="与 test_scores.npz 对齐")
    ap.add_argument("--limit", type=int, default=0, help="调试：只处理前 N 行")
    args = ap.parse_args()

    t_all = time.perf_counter()
    cfg = load_config()
    model_dir = PKG / "model"
    meta = load_meta(model_dir)
    inp = Path(args.input).resolve()
    stem = inp.stem

    t0 = time.perf_counter()
    df = read_input(inp, inp.name)
    if args.limit:
        df = df.head(args.limit).copy()
    t_read = time.perf_counter() - t0

    art_dir = resolve_art_dir(cfg)
    npz_dir = resolve_npz_dir(cfg)
    cache_pair = load_pair(art_dir, npz_dir) if art_dir or npz_dir else None
    img_map = cache_pair[0] if cache_pair else None

    cache_dirs = resolve_cache_dirs(cfg)
    urls = uncached_image_urls(df, img_map)
    t0 = time.perf_counter()
    if not args.skip_download:
        ok_map = asyncio.run(download_urls(urls, cache_dirs, cfg.get("download_concurrency", 200)))
        print(f"[run] 下载未缓存主图 成功 {sum(ok_map.values())}/{len(ok_map)}")
    else:
        print("[run] skip-download")
    t_dl = time.perf_counter() - t0

    paths = []
    img_missing = []
    img_cache_ids = set(img_map or {})
    for pid, u in zip(df["商品ID"].astype(str), df["main_url"].fillna("").astype(str)):
        if norm_id(pid) in img_cache_ids:
            paths.append(None)
            img_missing.append(False)
        elif u and image_ok(u, cache_dirs):
            paths.append(url_to_path(u, cache_dirs))
            img_missing.append(False)
        else:
            paths.append(None)
            img_missing.append(True)
    df["img_missing"] = img_missing

    t0 = time.perf_counter()
    if cache_pair:
        img_map, txt_map = cache_pair
        X_img, X_txt, img_miss, txt_miss = fill_partial_from_cache(
            df["商品ID"].astype(str).tolist(), img_map, txt_map
        )
        img_idx = np.flatnonzero(img_miss)
        if len(img_idx):
            sub_paths = [paths[i] for i in img_idx]
            sub_img, sub_miss = embed_images(sub_paths, batch=cfg.get("embed_batch", 32))
            for k, i in enumerate(img_idx):
                X_img[i] = sub_img[k]
                df.iat[i, df.columns.get_loc("img_missing")] = bool(sub_miss[k])
        t_img = time.perf_counter() - t0

        t0 = time.perf_counter()
        txt_idx = np.flatnonzero(txt_miss)
        if len(txt_idx):
            sub_txt = embed_texts(
                df.iloc[txt_idx]["标题"].astype(str).tolist(),
                cfg.get("hf_model", "BAAI/bge-small-zh-v1.5"),
                batch=cfg.get("embed_batch", 32),
            )
            for k, i in enumerate(txt_idx):
                X_txt[i] = sub_txt[k]
        t_txt = time.perf_counter() - t0
    else:
        X_img, miss = embed_images(paths, batch=cfg.get("embed_batch", 32))
        df["img_missing"] = df["img_missing"] | miss
        t_img = time.perf_counter() - t0
        t0 = time.perf_counter()
        X_txt = embed_texts(
            df["标题"].astype(str).tolist(),
            cfg.get("hf_model", "BAAI/bge-small-zh-v1.5"),
            batch=cfg.get("embed_batch", 32),
        )
        t_txt = time.perf_counter() - t0

    te = load_te(model_dir)
    df = apply_inference_source(df, cfg.get("inference_source", meta["inference_source_fixed"]))
    if art_dir and (art_dir / "dataset_embedded.csv").is_file():
        df = overlay_embedded_tab(df, art_dir, meta)
        emb = pd.read_csv(
            art_dir / "dataset_embedded.csv", encoding="utf-8-sig", dtype={"商品ID": str}
        )
        src_map = emb.drop_duplicates("商品ID").set_index("商品ID")["source"]
        hit = df["商品ID"].isin(src_map.index)
        df.loc[hit, "source"] = df.loc[hit, "商品ID"].map(src_map)
    df["cat_l2_te"] = apply_cat_l2_te(df, te)
    tab = cast_categories(tab_matrix(df, meta), meta)

    t0 = time.perf_counter()
    pred = predict(tab, X_img, X_txt, model_dir, cfg)
    t_pred = time.perf_counter() - t0

    df["预测分"] = pred
    df["排名"] = df["预测分"].rank(ascending=False, method="min").astype(int)

    words_file = PKG / "words" / "违禁词与侵权.txt"
    norm_json = PKG / "words" / "words_normalized.json"
    entries = load_words(words_file, norm_json)
    t0 = time.perf_counter()
    df, hit_counter = apply_banned(df, entries)
    log_stats(df, len(entries), hit_counter)
    t_word = time.perf_counter() - t0

    out_cols = {
        "排名": "排名",
        "预测分": "预测分",
        "商品ID": "商品ID",
        "标题": "标题",
        "美元价格($)": "美元价格",
        "cat_l1": "一级类目",
        "cat_l2": "二级类目",
        "main_url": "主图URL",
        "商品链接": "商品链接",
        "来源文件": "来源文件",
        "banned": "banned",
        "banned_hits": "banned_hits",
        "img_missing": "img_missing",
    }
    export = pd.DataFrame({v: df[k] for k, v in out_cols.items()})
    if "总销量" in df.columns:
        export["总销量"] = df["总销量"]

    out_dir = PKG / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"{stem}_scored.csv"
    export.to_csv(csv_path, index=False, encoding="utf-8-sig")

    print(
        f"[run] 耗时 读表{t_read:.1f}s 下载{t_dl:.1f}s 图{t_img:.1f}s 文{t_txt:.1f}s "
        f"预测{t_pred:.1f}s 违禁{t_word:.1f}s 合计{time.perf_counter()-t_all:.1f}s"
    )
    print(f"[run] CSV {csv_path}")
    print("[run] HTML 阶段已拆分：用 generate_html.py 读取 scored CSV 生成页面")

    if args.self_test:
        art = PKG.parent / "artifacts_v2" if (PKG.parent / "artifacts_v2").is_dir() else Path(
            r"C:\Users\ZFGJ-WCH\Desktop\8天前数据\artifacts_v2"
        )
        zpath = art / "test_scores.npz"
        z = np.load(zpath, allow_pickle=True)
        ref_ids = [str(i) for i in z["ids"]]
        ref_pred = z["pred_full"].astype(np.float64)
        ref_map = dict(zip(ref_ids, ref_pred))
        sub = export[export["商品ID"].isin(ref_map)]
        if len(sub) < 100:
            print(f"[self-test] 交集过小 n={len(sub)}")
            return
        p_new = sub.sort_values("商品ID")["预测分"].to_numpy()
        p_old = np.array([ref_map[i] for i in sub.sort_values("商品ID")["商品ID"]])
        sp, _ = spearmanr(p_new, p_old)
        print(f"[self-test] Spearman vs test_scores n={len(sub)} -> {sp:.4f}")
        if sp < 0.95:
            raise SystemExit("自测未通过 Spearman < 0.95")


if __name__ == "__main__":
    main()
