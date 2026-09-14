# -*- coding: utf-8 -*-
"""用已训 full 模型在外部单文件上打分，并算 top-5% precision/recall。"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

import rank_products as rp

ROOT = Path(__file__).resolve().parent
ART = ROOT / "artifacts_v2"


def prepare_one_file(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="sheet", header=[0, 1])
    df = rp.flatten_columns(df)
    df["source"] = path.name
    frames = [df]
    full = pd.concat(frames, ignore_index=True)

    full["商品ID"] = full["商品ID"].astype(str)
    full["总销量"] = pd.to_numeric(full["总销量"], errors="coerce").fillna(0)
    full["美元价格($)"] = pd.to_numeric(full["美元价格($)"], errors="coerce")
    full = full.sort_values(["商品ID", "总销量"], ascending=[True, False])
    full = full.drop_duplicates("商品ID", keep="first")
    full = full[full["美元价格($)"].notna() & (full["美元价格($)"] > 0)].copy()

    full["main_url"] = full["商品主图"].map(lambda x: rp.parse_urls(x)[:1]).map(
        lambda xs: xs[0] if xs else ""
    )
    full = full[full["main_url"] != ""].copy()

    full["y_raw"] = full["总销量"]
    full["y"] = np.log1p(full["y_raw"].astype(float))

    cat = full["前台分类（中文）"].fillna("").astype(str)
    parts = cat.str.split("/", n=2, expand=True)
    full["cat_l1"] = parts[0].replace("", "未知")
    full["cat_l2"] = (
        parts[1].fillna("未知").replace("", "未知") if 1 in parts.columns else "未知"
    )
    full["标题"] = full.apply(rp.title_text, axis=1)
    tlen = full["标题"].str.len().clip(lower=1)
    full["title_len"] = tlen.astype(int)
    full["title_cjk_ratio"] = full["标题"].map(
        lambda s: len(rp.CJK_RE.findall(str(s))) / max(len(str(s)), 1)
    )
    full["has_cn_title"] = full["商品标题（中文）"].notna().astype(int)
    full["log_price"] = np.log1p(full["美元价格($)"].astype(float))
    full["has_video"] = full["商品视频"].apply(
        lambda x: 1 if pd.notna(x) and str(x).strip() and str(x).lower() != "nan" else 0
    )
    full["n_gallery"] = full["商品轮播图"].map(lambda x: len(rp.parse_urls(x)))
    full["n_tags"] = full["标签"].map(rp.count_tags) if "标签" in full.columns else 0
    full["has_backend_cat"] = (
        full["后台分类"].notna().astype(int) if "后台分类" in full.columns else 0
    )
    full["shop_group"] = rp.shop_group_series(full)
    return full.reset_index(drop=True)


def align_categories(frame: pd.DataFrame, ref: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for c in rp.CAT_COLS:
        out[c] = out[c].astype(str)
        cats = list(ref[c].astype(str).unique()) + ["未知"]
        out[c] = pd.Categorical(out[c], categories=pd.Index(cats).unique())
    return out


def embed_frame(df: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    mask = df["main_url"].map(rp.image_ok)
    df = df[mask].reset_index(drop=True)
    paths = [rp.url_to_path(u) for u in df["main_url"]]
    model, tfm = rp.build_resnet()
    dev = rp.device()
    raw, ok_idx = rp.embed_image_paths(model, tfm, paths, dev, rp.img_batch_size())
    if len(ok_idx) < len(df):
        keep = np.zeros(len(df), dtype=bool)
        keep[ok_idx] = True
        df = df[keep].reset_index(drop=True)
        raw = raw
    X_img = rp.l2_normalize(raw)
    texts = df["标题"].astype(str).tolist()
    X_txt = rp.embed_texts(texts, batch=32)
    return df, X_img, X_txt


def top5pct_metrics(sales: np.ndarray, pred: np.ndarray) -> dict:
    n = len(sales)
    k = max(1, int(np.ceil(n * 0.05)))
    top = np.argsort(-pred)[:k]
    out = {}
    for name, mask_fn in (
        ("sale_gt0", lambda s: s > 0),
        ("sale_ge5", lambda s: s >= 5),
        ("sale_ge20", lambda s: s >= 20),
    ):
        mask = mask_fn(sales)
        tp = mask[top].sum()
        out[f"prec_{name}"] = float(tp / k)
        out[f"rec_{name}"] = float(tp / max(mask.sum(), 1))
        out[f"base_{name}"] = float(mask.mean())
    out["top_k"] = k
    out["n"] = n
    return out


def subset_by_label_pos_pct(
    df: pd.DataFrame, pos_pct: int, sample_cap: int = 0
) -> pd.DataFrame:
    """pos_pct：子集里「总销量>0」占比。0=全零销量压力测试。"""
    pos = df[df["总销量"] > 0]
    neg = df[df["总销量"] == 0]
    if pos_pct == 0:
        pool = neg
        print(
            f"[ext] 压力测试 label正例率=0%：仅零销量 {len(pool)} 条 "
            f"(全文件正例 {(df['总销量']>0).mean():.1%})"
        )
    elif pos_pct == 100:
        pool = pos
        print(f"[ext] label正例率=100%：仅有销量 {len(pool)} 条")
    else:
        if pos_pct <= 0 or not len(pos):
            pool = neg
        else:
            cap = sample_cap if sample_cap and sample_cap > 0 else min(len(df), 5000)
            cap = min(cap, len(pos) + len(neg))
            n_pos = min(len(pos), max(0, int(round(cap * pos_pct / 100))))
            n_neg = min(len(neg), cap - n_pos)
            if n_pos + n_neg < cap and len(pos) > n_pos:
                n_pos = min(len(pos), cap - n_neg)
            parts = []
            if n_pos:
                parts.append(pos.sample(n=n_pos, random_state=rp.SEED))
            if n_neg:
                parts.append(neg.sample(n=n_neg, random_state=rp.SEED))
            pool = (
                pd.concat(parts, ignore_index=True).sample(frac=1, random_state=rp.SEED)
                if parts
                else df.iloc[:0]
            )
            actual = (pool["总销量"] > 0).mean() if len(pool) else 0.0
            print(
                f"[ext] 分层抽样 目标正例率={pos_pct}% => {len(pool)} 条 "
                f"(实际正例率 {actual:.1%})"
            )
    if sample_cap and len(pool) > sample_cap:
        pool = pool.sample(n=sample_cap, random_state=rp.SEED)
        print(f"[ext] 再限制样本量 cap={sample_cap}")
    return pool.reset_index(drop=True)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--file",
        type=Path,
        default=Path(r"C:\Users\ZFGJ-WCH\Desktop\831-910\2097858114920054785.csv"),
    )
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--sample", type=int, default=0, help="随机抽样条数，0=全量（与 --sample-pct 二选一）")
    parser.add_argument(
        "--sample-pct",
        type=int,
        default=None,
        choices=[0, 10, 30, 50, 80, 100],
        help="（行数比例）清洗后随机抽多少%，0=全量行",
    )
    parser.add_argument(
        "--pos-pct",
        type=int,
        default=None,
        choices=[0, 10, 30, 50, 80, 100],
        help="子集内总销量>0占比；0=全零销量压力测试",
    )
    parser.add_argument("--download", action="store_true", help="下载缺失主图")
    parser.add_argument("--concurrency", type=int, default=200)
    args = parser.parse_args()

    stem = args.file.stem[:24]
    if args.out is None:
        if args.pos_pct is not None:
            args.out = ART / f"external_{stem}_labelp{args.pos_pct}.json"
        elif args.sample_pct is not None:
            args.out = ART / f"external_{stem}_rows_p{args.sample_pct}.json"
        else:
            args.out = ART / f"external_{stem}.json"

    t0 = time.perf_counter()
    print(f"[ext] 文件: {args.file.name}")
    raw = prepare_one_file(args.file)
    if args.pos_pct is not None:
        raw = subset_by_label_pos_pct(raw, args.pos_pct, sample_cap=args.sample or 0)
    sample_pct = args.sample_pct
    if sample_pct is not None and args.pos_pct is None:
        if sample_pct > 0:
            n = max(1, int(round(len(raw) * sample_pct / 100)))
            n = min(n, len(raw))
            raw = raw.sample(n=n, random_state=rp.SEED).reset_index(drop=True)
            print(f"[ext] 随机抽样 {sample_pct}% => {len(raw)} 条 (seed={rp.SEED})")
        else:
            print(f"[ext] sample-pct=0 全量 {len(raw)} 条")
    elif args.sample and args.pos_pct is None and len(raw) > args.sample:
        raw = raw.sample(n=args.sample, random_state=rp.SEED).reset_index(drop=True)
        print(f"[ext] 随机抽样 {args.sample} 条 (seed={rp.SEED})")

    cached = int(raw["main_url"].map(rp.image_ok).sum())
    print(f"[ext] 清洗后 {len(raw)} 行，主图已缓存 {cached} ({cached/len(raw):.1%})")

    if args.download:
        urls = raw["main_url"].dropna().astype(str).unique().tolist()
        need = [u for u in urls if u and not rp.image_ok(u)]
        print(f"[ext] 下载主图 {len(need)} 个（唯一 URL）…")
        if need:
            ok_map = asyncio.run(rp.download_urls(need, concurrency=args.concurrency))
            ok = sum(1 for v in ok_map.values() if v)
            print(f"[ext] 下载成功 {ok}/{len(need)}")
        cached = int(raw["main_url"].map(rp.image_ok).sum())
        print(f"[ext] 下载后主图可用 {cached}/{len(raw)} ({cached/len(raw):.1%})")

    print("[ext] 拟合 full 模型（与主实验一致，用于打分）…")
    bundle = rp.make_split_bundle()
    train, valid = bundle["train"], bundle["valid"]
    X_tr, X_va, _ = rp.group_feature_mats(bundle, "full")
    for part in (X_tr, X_va):
        for c in rp.CAT_COLS:
            if c in part.columns:
                part[c] = part[c].astype(str).astype("category")
    sk_model = rp.fit_lgbm(X_tr, train["y"], X_va, valid["y"])
    booster = sk_model.booster_
    ref_names = booster.feature_name()

    df, X_img, X_txt = embed_frame(raw)
    print(f"[ext] 可打分样本 {len(df)}（需主图可解码）")

    df["cat_l2_te"] = rp.cat_l2_target_encode(train, df)
    df = align_categories(df, train)
    tab = rp.build_tab_matrix(df)
    X = rp.concat_features(tab, X_img, X_txt, None)
    for col in ref_names:
        if col not in X.columns:
            X[col] = 0.0
    X = X[ref_names]
    for c in rp.CAT_COLS:
        if c in X.columns and c in X_tr.columns:
            X[c] = pd.Categorical(
                X[c].astype(str), categories=X_tr[c].cat.categories
            )
    pred = booster.predict(X)
    sales = df["总销量"].to_numpy(dtype=float)
    sp = float("nan")
    if np.std(sales) > 0 and np.std(pred) > 0:
        sp, _ = spearmanr(pred, sales)

    m = top5pct_metrics(sales, pred)
    m["pred_mean"] = float(pred.mean())
    m["pred_std"] = float(pred.std())
    m["pred_top5pct_mean"] = float(pred[np.argsort(-pred)[: m["top_k"]]].mean())
    m["file"] = args.file.name
    m["spearman"] = float(sp)
    m["img_cache_before"] = int(cached)
    m["rows_prepared"] = int(len(raw))
    m["rows_scored"] = int(len(df))
    m["sample_n"] = args.sample if sample_pct is None else None
    m["sample_pct"] = sample_pct
    m["label_pos_pct"] = args.pos_pct
    m["stress_zero_label"] = args.pos_pct == 0
    m["actual_pos_rate"] = float((sales > 0).mean())
    m["elapsed_sec"] = round(time.perf_counter() - t0, 1)

    top_idx = np.argsort(-pred)[:200]
    picks = df.iloc[top_idx][
        ["商品ID", "标题", "美元价格($)", "cat_l1", "cat_l2", "main_url", "总销量"]
    ].copy()
    picks.insert(0, "预测分", pred[top_idx])
    picks.insert(0, "排名", range(1, len(picks) + 1))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    picks.to_csv(args.out.with_suffix(".top200.csv"), index=False, encoding="utf-8-sig")

    print(f"[ext] top5% k={m['top_k']}  prec>0={m['prec_sale_gt0']:.3f}  rec>0={m['rec_sale_gt0']:.3f}")
    print(f"[ext] prec>=5={m['prec_sale_ge5']:.3f}  rec>=5={m['rec_sale_ge5']:.3f}")
    print(f"[ext] Spearman={m['spearman']:.4f}  耗时 {m['elapsed_sec']}s")
    print(f"[ext] 写入 {args.out}")


if __name__ == "__main__":
    main()
