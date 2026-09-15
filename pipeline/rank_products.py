# -*- coding: utf-8 -*-
"""选品排序流水线（见 PLAN_rank_products.md）。分阶段可缓存复用。"""
from __future__ import annotations

import argparse
import ast
import asyncio
import hashlib
import json
import pickle
import re
import shutil
import sys
import time
from pathlib import Path

import aiohttp
import lightgbm as lgb
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from lightgbm import LGBMRegressor
from PIL import Image
from scipy.stats import spearmanr
from sentence_transformers import SentenceTransformer
from sklearn.model_selection import GroupShuffleSplit
from torchvision import models

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent

from temu_region import temu_aiohttp_headers
ART = PROJECT_ROOT / "artifacts" / "current"
NPZ_DIR = Path(r"D:\temu_rank_npz")
IMG_DIR = PROJECT_ROOT / "hit_cache" / "images"


def npz_paths() -> tuple[Path, Path]:
    NPZ_DIR.mkdir(parents=True, exist_ok=True)
    return NPZ_DIR / "img.npz", NPZ_DIR / "txt.npz"


def save_npz_atomic(path: Path, **arrays) -> None:
    import os

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.stem}.{int(time.time() * 1000)}.npz"
    np.savez_compressed(tmp, **arrays)
    try:
        os.replace(tmp, path)
    except OSError:
        bak = path.with_suffix(path.suffix + ".bak")
        if path.exists():
            try:
                path.replace(bak)
            except OSError:
                pass
        os.replace(tmp, path)
        if bak.exists():
            bak.unlink(missing_ok=True)
DATA_FILES = [
    PROJECT_ROOT / "data" / "raw" / "909.xlsx",
    PROJECT_ROOT / "data" / "raw" / "910.csv",
    PROJECT_ROOT / "data" / "raw" / "911.csv",
    PROJECT_ROOT / "data" / "raw" / "912.csv",
    PROJECT_ROOT / "data" / "raw" / "913.csv",
]
URL_RE = re.compile(r"https?://[^\s\],>]+")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
SEED = 42
# cat_l1 在全表为常量「家居厨房用品」，不作为特征
CAT_COLS = ("cat_l2", "source")
NUM_TAB_COLS = (
    "log_price",
    "has_video",
    "n_gallery",
    "title_len",
    "title_cjk_ratio",
    "has_cn_title",
    "n_tags",
    "has_backend_cat",
    "cat_l2_te",
)
LEAK_COLS = ("店铺总销量", "粉丝数", "店铺评分", "在售商品数")
LGB_PARAMS = dict(
    n_estimators=1200,
    learning_rate=0.03,
    num_leaves=63,
    min_child_samples=40,
    subsample=0.8,
    subsample_freq=1,
    colsample_bytree=0.5,
    reg_lambda=5.0,
    random_state=SEED,
    verbose=-1,
)
EVAL_GROUPS = (
    "random",
    "price_only",
    "cat_only",
    "tab_only",
    "title_only",
    "image_only",
    "full",
    "LEAK_shop",
)


def flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [
            str(b).strip()
            if not str(b).startswith("Unnamed")
            else str(a).strip()
            for a, b in df.columns
        ]
    return df


def parse_urls(value) -> list[str]:
    if pd.isna(value):
        return []
    found = URL_RE.findall(str(value))
    out, seen = [], set()
    for u in found:
        u = u.rstrip(").,;'\"")
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def count_tags(value) -> int:
    if pd.isna(value):
        return 0
    s = str(value).strip()
    if not s or s in ("[]", "nan"):
        return 0
    try:
        v = ast.literal_eval(s)
        if isinstance(v, list):
            return len(v)
    except (ValueError, SyntaxError):
        pass
    return 0


def url_to_path(url: str) -> Path:
    h = hashlib.md5(url.encode("utf-8")).hexdigest()
    ext = ".jpg"
    low = url.lower()
    if ".png" in low:
        ext = ".png"
    elif ".webp" in low:
        ext = ".webp"
    elif ".jpeg" in low:
        ext = ".jpeg"
    return IMG_DIR / f"{h}{ext}"


def image_ok(url: str) -> bool:
    p = url_to_path(url)
    return p.exists() and p.stat().st_size > 1024


def title_text(row) -> str:
    cn = row.get("商品标题（中文）")
    if pd.notna(cn) and str(cn).strip():
        return str(cn).strip()
    return str(row.get("商品标题（英文）", "")).strip()


def shop_group_series(df: pd.DataFrame) -> pd.Series:
    def one(row):
        sid = row["店铺ID"]
        if pd.notna(sid):
            return f"shop_{int(float(sid))}"
        return f"row_{row.name}"

    return df.apply(one, axis=1)


def build_prepared_df() -> pd.DataFrame:
    frames = []
    for path in DATA_FILES:
        df = pd.read_excel(path, sheet_name="sheet", header=[0, 1])
        df = flatten_columns(df)
        df["source"] = path.name
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)

    df["商品ID"] = df["商品ID"].astype(str)
    df["总销量"] = pd.to_numeric(df["总销量"], errors="coerce").fillna(0)
    df["美元价格($)"] = pd.to_numeric(df["美元价格($)"], errors="coerce")
    df = df.sort_values(["商品ID", "总销量"], ascending=[True, False])
    df = df.drop_duplicates("商品ID", keep="first")
    df = df[df["美元价格($)"].notna() & (df["美元价格($)"] > 0)].copy()

    df["main_url"] = df["商品主图"].map(lambda x: parse_urls(x)[:1]).map(
        lambda xs: xs[0] if xs else ""
    )
    df = df[df["main_url"] != ""].copy()

    df["y_raw"] = df["总销量"].astype(float)
    df["y"] = np.log1p(df["y_raw"])  # 训练前在 make_split_bundle 内按 train p99.5 再 winsorize

    cat = df["前台分类（中文）"].fillna("").astype(str)
    parts = cat.str.split("/", n=2, expand=True)
    df["cat_l1"] = parts[0].replace("", "未知")
    df["cat_l2"] = (
        parts[1].fillna("未知").replace("", "未知") if 1 in parts.columns else "未知"
    )

    df["标题"] = df.apply(title_text, axis=1)
    tlen = df["标题"].str.len().clip(lower=1)
    df["title_len"] = tlen.astype(int)
    df["title_cjk_ratio"] = df["标题"].map(
        lambda s: len(CJK_RE.findall(str(s))) / max(len(str(s)), 1)
    )
    df["has_cn_title"] = df["商品标题（中文）"].notna().astype(int)
    df["log_price"] = np.log1p(df["美元价格($)"].astype(float))
    df["has_video"] = df["商品视频"].apply(
        lambda x: 1 if pd.notna(x) and str(x).strip() and str(x).lower() != "nan" else 0
    )
    df["n_gallery"] = df["商品轮播图"].map(lambda x: len(parse_urls(x)))
    df["n_tags"] = df["标签"].map(count_tags) if "标签" in df.columns else 0
    df["has_backend_cat"] = (
        df["后台分类"].notna().astype(int) if "后台分类" in df.columns else 0
    )
    df["shop_group"] = shop_group_series(df)

    for c in LEAK_COLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
        else:
            df[c] = 0.0

    link_col = "商品链接" if "商品链接" in df.columns else None
    df["商品链接"] = df[link_col].astype(str) if link_col else ""

    df["split"] = ""
    out_cols = [
        "商品ID",
        "标题",
        "main_url",
        "商品链接",
        "美元价格($)",
        "cat_l1",
        "cat_l2",
        "source",
        "总销量",
        "y_raw",
        "y",
        "split",
        "shop_group",
        "log_price",
        "has_video",
        "n_gallery",
        "title_len",
        "title_cjk_ratio",
        "has_cn_title",
        "n_tags",
        "has_backend_cat",
    ] + list(LEAK_COLS)
    return df[out_cols].reset_index(drop=True)


def stage_prep() -> Path:
    t0 = time.perf_counter()
    ART.mkdir(parents=True, exist_ok=True)
    df = build_prepared_df()
    path = ART / "dataset.csv"
    df.to_csv(path, index=False, encoding="utf-8-sig")
    pos = (df["总销量"] > 0).mean()
    elapsed = time.perf_counter() - t0
    print(f"[prep] 行数={len(df)}  总销量>0占比={pos:.3f}  唯一主图URL={df['main_url'].nunique()}")
    print(f"[prep] 写入 {path}  耗时 {elapsed:.1f}s")
    return path


def load_dataset() -> pd.DataFrame:
    path = ART / "dataset.csv"
    if not path.exists():
        stage_prep()
    return pd.read_csv(path, encoding="utf-8-sig", dtype={"商品ID": str})


async def _download_one(session, url: str, sem: asyncio.Semaphore) -> tuple[str, bool, str]:
    dest = url_to_path(url)
    if dest.exists() and dest.stat().st_size > 1024:
        return url, True, "cached"
    async with sem:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status != 200:
                    return url, False, f"http_{resp.status}"
                data = await resp.read()
                if len(data) < 1024:
                    return url, False, "too_small"
                tmp = dest.with_suffix(dest.suffix + ".part")
                tmp.write_bytes(data)
                tmp.replace(dest)
                return url, True, "ok"
        except Exception as exc:
            return url, False, type(exc).__name__


async def download_urls(urls: list[str], concurrency: int = 200) -> dict[str, bool]:
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    headers = temu_aiohttp_headers()
    connector = aiohttp.TCPConnector(limit=concurrency, ssl=False)
    sem = asyncio.Semaphore(concurrency)
    async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
        tasks = [_download_one(session, u, sem) for u in urls]
        results = await asyncio.gather(*tasks)
    return {url: ok for url, ok, _ in results}


def stage_download(concurrency: int = 200, skip_download: bool = False) -> None:
    t0 = time.perf_counter()
    df = load_dataset()
    urls = df["main_url"].dropna().astype(str).unique().tolist()
    urls = [u for u in urls if u]
    already = sum(1 for u in urls if image_ok(u))
    print(f"[download] 待处理唯一主图 URL: {len(urls)}  本地已有(>1KB): {already}")
    if skip_download:
        print("[download] --skip-download，跳过网络请求")
        return
    ok_map = asyncio.run(download_urls(urls, concurrency=concurrency))
    ok = sum(1 for v in ok_map.values() if v)
    failed = len(urls) - ok
    rate = ok / max(len(urls), 1)
    elapsed = time.perf_counter() - t0
    print(f"[download] 成功={ok}  失败={failed}  成功率={rate:.3f}  耗时 {elapsed:.1f}s")
    fail_urls = [u for u, v in ok_map.items() if not v]
    if fail_urls[:5]:
        print(f"[download] 失败样例（最多5个）: {fail_urls[:5]}")


def device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def img_batch_size() -> int:
    return 32 if device().type == "cuda" else 16


def build_resnet():
    weights = models.ResNet18_Weights.IMAGENET1K_V1
    model = models.resnet18(weights=weights)
    model.fc = nn.Identity()
    model.eval()
    return model, weights.transforms()


def l2_normalize(x: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(x, axis=1, keepdims=True)
    n = np.maximum(n, 1e-12)
    return (x / n).astype(np.float32)


@torch.no_grad()
def embed_image_paths(
    model, tfm, paths: list[Path], dev: torch.device, batch: int
) -> tuple[np.ndarray, list[int]]:
    vecs, ok_idx = [], []
    model = model.to(dev)
    for i in range(0, len(paths), batch):
        chunk_paths = paths[i : i + batch]
        tensors, idx_map = [], []
        for j, p in enumerate(chunk_paths):
            try:
                im = Image.open(p).convert("RGB")
                tensors.append(tfm(im))
                idx_map.append(i + j)
            except Exception:
                continue
        if not tensors:
            continue
        x = torch.stack(tensors).to(dev)
        feat = model(x).cpu().numpy()
        vecs.append(feat)
        ok_idx.extend(idx_map)
        if i % (batch * 10) == 0:
            print(f"  img {min(i + batch, len(paths))}/{len(paths)}", flush=True)
    if not vecs:
        return np.zeros((0, 512), dtype=np.float32), []
    return np.concatenate(vecs, axis=0), ok_idx


def embed_texts(texts: list[str], batch: int = 32) -> np.ndarray:
    model = SentenceTransformer("BAAI/bge-small-zh-v1.5")
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model = model.to(dev)
    vecs = model.encode(
        texts,
        batch_size=batch,
        show_progress_bar=True,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    return vecs.astype(np.float32)


def load_npz_cache(path: Path) -> dict[str, np.ndarray]:
    """按商品 ID 读取向量缓存，避免训练阶段重新依赖图片文件。"""
    cache: dict[str, np.ndarray] = {}
    if path.exists():
        with np.load(path, allow_pickle=True) as z:
            cache = {str(i): v.copy() for i, v in zip(z["ids"], z["X"])}
    return cache


def add_local_image_vectors(df: pd.DataFrame, img_cache: dict[str, np.ndarray]) -> int:
    """只给已有本地图片文件但尚无缓存向量的商品补 ResNet 向量。"""
    miss = df[~df["商品ID"].astype(str).isin(img_cache)].copy()
    if miss.empty:
        return 0
    local = miss[miss["main_url"].map(image_ok)].copy()
    skipped = len(miss) - len(local)
    if local.empty:
        print(f"[embed] 图片向量缺失 {len(miss)} 条；本地无图，跳过下载")
        return 0
    paths = [url_to_path(u) for u in local["main_url"]]
    model, tfm = build_resnet()
    dev = device()
    print(f"[embed] 新增 ResNet18 {len(local)} 条 device={dev}；本地无图跳过 {skipped} 条")
    raw, ok_idx = embed_image_paths(model, tfm, paths, dev, img_batch_size())
    raw_n = l2_normalize(raw) if len(raw) else raw
    for k, pos in enumerate(ok_idx):
        img_cache[str(local.iloc[pos]["商品ID"])] = raw_n[k]
    print(f"[embed] 新增图像向量 {len(ok_idx)}/{len(local)}")
    return len(ok_idx)


def stage_embed() -> None:
    """生成训练用对齐表；优先使用 NPZ 向量缓存，不主动下载训练图片。"""
    t0 = time.perf_counter()
    df = load_dataset()
    img_path, txt_path = npz_paths()

    img_cache = load_npz_cache(img_path)
    if img_path.exists():
        print(f"[embed] 图像缓存 {len(img_cache)} 条")

    add_local_image_vectors(df, img_cache)

    keep = df["商品ID"].astype(str).isin(img_cache)
    dropped = int((~keep).sum())
    df = df[keep].reset_index(drop=True)
    print(f"[embed] 图片向量缺失丢弃 {dropped} 行，保留 {len(df)}")
    ids = df["商品ID"].astype(str).tolist()
    X_img = np.stack([img_cache[i] for i in ids]).astype(np.float32)
    save_npz_atomic(img_path, ids=np.array(ids, dtype=object), X=X_img)
    print(f"[embed] 写入 {img_path} shape={X_img.shape}")

    txt_cache = load_npz_cache(txt_path)
    if txt_path.exists():
        print(f"[embed] 文本缓存 {len(txt_cache)} 条")

    miss_t = df[~df["商品ID"].astype(str).isin(txt_cache)]
    if len(miss_t):
        print(f"[embed] 新增 BGE {len(miss_t)} 条…")
        new_txt = embed_texts(miss_t["标题"].astype(str).tolist(), batch=32)
        for pid, vec in zip(miss_t["商品ID"].astype(str), new_txt):
            txt_cache[pid] = vec

    X_txt = np.stack([txt_cache[i] for i in ids]).astype(np.float32)
    save_npz_atomic(txt_path, ids=np.array(ids, dtype=object), X=X_txt)
    print(f"[embed] 写入 {txt_path} shape={X_txt.shape}")

    df.to_csv(ART / "dataset_embedded.csv", index=False, encoding="utf-8-sig")
    elapsed = time.perf_counter() - t0
    print(f"[embed] 完成 耗时 {elapsed:.1f}s")


def cat_l2_target_encode(
    train: pd.DataFrame, frame: pd.DataFrame, m: float = 20.0
) -> pd.Series:
    global_mean = float(train["y"].mean())
    agg = train.groupby("cat_l2", observed=True)["y"].agg(["mean", "count"])
    mapping = {}
    for cat, row in agg.iterrows():
        n = row["count"]
        mapping[cat] = (n * row["mean"] + m * global_mean) / (n + m)
    return frame["cat_l2"].map(mapping).fillna(global_mean).astype(float)


def as_categories(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for c in CAT_COLS:
        out[c] = out[c].astype(str).astype("category")
    return out


def remove_test_near_duplicates(
    train: pd.DataFrame,
    test: pd.DataFrame,
    X_img_train: np.ndarray,
    X_img_test: np.ndarray,
    X_txt_test: np.ndarray,
) -> tuple[pd.DataFrame, np.ndarray, np.ndarray, dict]:
    stats = {}
    keep = np.ones(len(test), dtype=bool)

    t_urls = set(train["main_url"].astype(str))
    m1 = test["main_url"].astype(str).isin(t_urls).to_numpy()
    stats["main_url"] = int(m1.sum())
    keep &= ~m1

    t_titles = set(train["标题"].astype(str).str.strip())
    m2 = test["标题"].astype(str).str.strip().isin(t_titles).to_numpy()
    stats["title"] = int((keep & m2).sum())
    keep &= ~m2

    if len(test) and len(train):
        block = 256
        drop = np.zeros(len(test), dtype=bool)
        for i in range(0, len(test), block):
            sim = X_img_test[i : i + block] @ X_img_train.T
            drop[i : i + block] = sim.max(axis=1) > 0.98
        stats["image_cosine"] = int((keep & drop).sum())
        keep &= ~drop
    else:
        stats["image_cosine"] = 0

    test = test[keep].copy().reset_index(drop=True)
    return test, X_img_test[keep], X_txt_test[keep], stats


def load_embed_tables() -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    emb_path = ART / "dataset_embedded.csv"
    if not emb_path.exists():
        stage_embed()
    df = pd.read_csv(emb_path, encoding="utf-8-sig", dtype={"商品ID": str})
    img_p, txt_p = npz_paths()
    with np.load(img_p, allow_pickle=True) as z_img:
        img_map = {str(i): v for i, v in zip(z_img["ids"], z_img["X"])}
    with np.load(txt_p, allow_pickle=True) as z_txt:
        txt_map = {str(i): v for i, v in zip(z_txt["ids"], z_txt["X"])}
    df = df[df["商品ID"].isin(img_map) & df["商品ID"].isin(txt_map)].reset_index(drop=True)
    X_img = np.stack([img_map[i] for i in df["商品ID"]])
    X_txt = np.stack([txt_map[i] for i in df["商品ID"]])
    return df, X_img, X_txt


def make_split_bundle() -> dict:
    df, X_img, X_txt = load_embed_tables()

    gss = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=SEED)
    tr_idx, te_idx = next(gss.split(df, groups=df["shop_group"]))
    train = df.iloc[tr_idx].copy().reset_index(drop=True)
    test = df.iloc[te_idx].copy().reset_index(drop=True)
    X_img_tr, X_img_te = X_img[tr_idx], X_img[te_idx]
    X_txt_tr, X_txt_te = X_txt[tr_idx], X_txt[te_idx]

    test, X_img_te, X_txt_te, dedupe_stats = remove_test_near_duplicates(
        train, test, X_img_tr, X_img_te, X_txt_te
    )

    y_cap = float(np.percentile(train["y_raw"].astype(float), 99.5))

    def winsor_y(frame: pd.DataFrame) -> pd.DataFrame:
        out = frame.copy()
        clipped = np.clip(out["y_raw"].astype(float), 0, y_cap)
        out["y"] = np.log1p(clipped)
        return out

    train = winsor_y(train)
    test = winsor_y(test)

    split_map = {r["商品ID"]: "train" for _, r in train.iterrows()}
    split_map.update({r["商品ID"]: "test" for _, r in test.iterrows()})
    full = load_dataset()
    full["split"] = full["商品ID"].map(split_map).fillna("")
    full.to_csv(ART / "dataset.csv", index=False, encoding="utf-8-sig")

    gss2 = GroupShuffleSplit(n_splits=1, test_size=0.1, random_state=SEED)
    tr2, va2 = next(gss2.split(train, groups=train["shop_group"]))
    train_fit = train.iloc[tr2].reset_index(drop=True)
    valid = train.iloc[va2].reset_index(drop=True)
    train_fit["cat_l2_te"] = cat_l2_target_encode(train_fit, train_fit)
    valid["cat_l2_te"] = cat_l2_target_encode(train_fit, valid)
    test["cat_l2_te"] = cat_l2_target_encode(train_fit, test)

    train_fit = as_categories(train_fit)
    valid = as_categories(valid)
    test = as_categories(test)

    return {
        "train": train_fit,
        "valid": valid,
        "test": test,
        "X_img_tr": X_img_tr[tr2],
        "X_txt_tr": X_txt_tr[tr2],
        "X_img_va": X_img_tr[va2],
        "X_txt_va": X_txt_tr[va2],
        "X_img_te": X_img_te,
        "X_txt_te": X_txt_te,
        "dedupe_stats": dedupe_stats,
        "y_cap_p995": y_cap,
        "n_train": len(train_fit),
        "n_valid": len(valid),
        "n_test": len(test),
    }


def build_tab_matrix(frame: pd.DataFrame, cols_cat: bool = True) -> pd.DataFrame:
    cols = list(NUM_TAB_COLS)
    X = frame[cols].copy()
    if cols_cat:
        for c in CAT_COLS:
            X[c] = frame[c]
    return X


def concat_features(
    tab: pd.DataFrame, img: np.ndarray | None, txt: np.ndarray | None, leak: np.ndarray | None
) -> pd.DataFrame:
    parts = [tab.reset_index(drop=True)]
    if img is not None:
        img_df = pd.DataFrame(img, columns=[f"img_{i}" for i in range(img.shape[1])])
        parts.append(img_df)
    if txt is not None:
        txt_df = pd.DataFrame(txt, columns=[f"txt_{i}" for i in range(txt.shape[1])])
        parts.append(txt_df)
    if leak is not None:
        leak_df = pd.DataFrame(leak, columns=[f"leak_{i}" for i in range(leak.shape[1])])
        parts.append(leak_df)
    return pd.concat(parts, axis=1)


def fit_lgbm(X_tr: pd.DataFrame, y_tr, X_va: pd.DataFrame, y_va) -> LGBMRegressor:
    cat_features = [c for c in X_tr.columns if c in CAT_COLS]
    model = LGBMRegressor(**LGB_PARAMS)
    model.fit(
        X_tr,
        y_tr,
        eval_set=[(X_va, y_va)],
        categorical_feature=cat_features if cat_features else "auto",
        callbacks=[lgb.early_stopping(100, verbose=False)],
    )
    return model


def group_feature_mats(bundle: dict, name: str):
    tr, va, te = bundle["train"], bundle["valid"], bundle["test"]
    leak_tr = tr[list(LEAK_COLS)].to_numpy(dtype=np.float32)
    leak_va = va[list(LEAK_COLS)].to_numpy(dtype=np.float32)
    leak_te = te[list(LEAK_COLS)].to_numpy(dtype=np.float32)

    if name == "price_only":
        tab_tr = tr[["log_price"]]
        tab_va = va[["log_price"]]
        tab_te = te[["log_price"]]
        return tab_tr, tab_va, tab_te
    if name == "cat_only":
        tab_tr = tr[["cat_l2_te"] + list(CAT_COLS)]
        tab_va = va[["cat_l2_te"] + list(CAT_COLS)]
        tab_te = te[["cat_l2_te"] + list(CAT_COLS)]
        return tab_tr, tab_va, tab_te
    if name == "tab_only":
        return build_tab_matrix(tr), build_tab_matrix(va), build_tab_matrix(te)
    if name == "title_only":
        return (
            pd.DataFrame(bundle["X_txt_tr"]),
            pd.DataFrame(bundle["X_txt_va"]),
            pd.DataFrame(bundle["X_txt_te"]),
        )
    if name == "image_only":
        return (
            pd.DataFrame(bundle["X_img_tr"]),
            pd.DataFrame(bundle["X_img_va"]),
            pd.DataFrame(bundle["X_img_te"]),
        )
    if name == "full":
        return (
            concat_features(build_tab_matrix(tr), bundle["X_img_tr"], bundle["X_txt_tr"], None),
            concat_features(build_tab_matrix(va), bundle["X_img_va"], bundle["X_txt_va"], None),
            concat_features(build_tab_matrix(te), bundle["X_img_te"], bundle["X_txt_te"], None),
        )
    if name == "LEAK_shop":
        return (
            concat_features(build_tab_matrix(tr), bundle["X_img_tr"], bundle["X_txt_tr"], leak_tr),
            concat_features(build_tab_matrix(va), bundle["X_img_va"], bundle["X_txt_va"], leak_va),
            concat_features(build_tab_matrix(te), bundle["X_img_te"], bundle["X_txt_te"], leak_te),
        )
    raise ValueError(name)


def stage_train() -> None:
    t0 = time.perf_counter()
    backup_round1()
    bundle = make_split_bundle()
    split_info = {
        "n_train_fit": bundle["n_train"],
        "n_valid": bundle["n_valid"],
        "n_test": bundle["n_test"],
        "dedupe_removed_from_test": bundle["dedupe_stats"],
        "y_cap_p995_train": bundle["y_cap_p995"],
    }
    with open(ART / "split.json", "w", encoding="utf-8") as f:
        json.dump(split_info, f, ensure_ascii=False, indent=2)
    print(f"[train] train={bundle['n_train']} valid={bundle['n_valid']} test={bundle['n_test']}")
    print(f"[train] y winsorize cap (train p99.5) = {bundle['y_cap_p995']:.0f}")
    print(f"[train] test 去重: {bundle['dedupe_stats']}")

    scores = {}
    models_meta = {}
    y_tr = bundle["train"]["y"]
    y_va = bundle["valid"]["y"]
    for name in EVAL_GROUPS:
        if name == "random":
            continue
        X_tr, X_va, X_te = group_feature_mats(bundle, name)
        cat_cols = [c for c in X_tr.columns if c in CAT_COLS]
        for part in (X_tr, X_va, X_te):
            for c in cat_cols:
                part[c] = part[c].astype(str).astype("category")
        print(f"[train] 拟合 {name} …")
        model = fit_lgbm(X_tr, y_tr, X_va, y_va)
        pred_te = model.predict(X_te)
        scores[name] = pred_te.astype(np.float64)
        models_meta[name] = {"best_iteration": int(getattr(model, "best_iteration_", 0) or 0)}
        if name == "full":
            with open(ART / "lgbm_full.pkl", "wb") as f:
                pickle.dump(model, f)
            ascii_txt = ART / "lgb_export_ascii" / "lgbm_full.txt"
            ascii_txt.parent.mkdir(parents=True, exist_ok=True)
            model.booster_.save_model(str(ascii_txt))

    test = bundle["test"]
    np.savez_compressed(
        ART / "test_scores.npz",
        ids=test["商品ID"].to_numpy(),
        sales=test["总销量"].to_numpy(),
        source=test["source"].to_numpy(),
        y=test["y"].to_numpy(),
        shop_total_sales=test["店铺总销量"].to_numpy(dtype=np.float64),
        **{f"pred_{k}": v for k, v in scores.items()},
    )
    with open(ART / "models_meta.json", "w", encoding="utf-8") as f:
        json.dump(models_meta, f, ensure_ascii=False, indent=2)
    elapsed = time.perf_counter() - t0
    print(f"[train] 完成 耗时 {elapsed:.1f}s")


def ndcg_at_k(gains: np.ndarray, scores: np.ndarray, k: int = 5) -> float:
    order = np.argsort(-scores)[:k]
    disc = np.log2(np.arange(2, len(order) + 2))
    dcg = np.sum(gains[order] / disc)
    ideal = np.sort(gains)[::-1][:k]
    idcg = np.sum(ideal / disc)
    return float(dcg / idcg) if idcg > 0 else 0.0


def make_slates(sources: np.ndarray, k: int, repeats: int, rng: np.random.Generator) -> np.ndarray:
    uniq = [s for s in np.unique(sources) if (sources == s).sum() >= k]
    pools = {s: np.flatnonzero(sources == s) for s in uniq}
    slates = np.empty((repeats, k), dtype=np.int64)
    for i in range(repeats):
        src = uniq[rng.integers(len(uniq))]
        slates[i] = rng.choice(pools[src], size=k, replace=False)
    return slates


def per_slate_metrics(
    sales: np.ndarray, slates: np.ndarray, pred: np.ndarray | None, rnd_rng: np.random.Generator
) -> dict[str, np.ndarray]:
    repeats, k = slates.shape
    out = {
        n: np.empty(repeats, dtype=np.float64)
        for n in (
            "sales@1",
            "sales@5",
            "rand",
            "oracle@1",
            "oracle@5",
            "hit@1",
            "hit@5",
            "ndcg@5",
        )
    }
    for i in range(repeats):
        idx = slates[i]
        s = sales[idx]
        g = np.log1p(s)
        p = rnd_rng.random(k) if pred is None else pred[idx]
        top1 = int(np.argmax(p))
        top5 = np.argsort(-p)[:5]
        true_top5 = set(np.argsort(-s)[:5].tolist())
        out["sales@1"][i] = s[top1]
        out["sales@5"][i] = s[top5].mean()
        out["rand"][i] = s.mean()
        out["oracle@1"][i] = s.max()
        out["oracle@5"][i] = np.sort(s)[-5:].mean()
        out["hit@1"][i] = 1.0 if top1 in true_top5 else 0.0
        out["hit@5"][i] = 1.0 if int(np.argmax(s)) in top5 else 0.0
        out["ndcg@5"][i] = ndcg_at_k(g, p, 5)
    return out


def aggregate_slate_metrics(raw: dict[str, np.ndarray]) -> dict[str, float]:
    m = {k: float(v.mean()) for k, v in raw.items()}
    m["lift@1"] = m["sales@1"] / max(m["rand"], 1e-9)
    m["lift@5"] = m["sales@5"] / max(m["rand"], 1e-9)
    m["recovery@1"] = m["sales@1"] / max(m["oracle@1"], 1e-9)
    m["recovery@5"] = m["sales@5"] / max(m["oracle@5"], 1e-9)
    return m


def top5pct_row(sales: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    n = len(sales)
    k = max(1, int(np.ceil(n * 0.05)))
    top = np.argsort(-pred)[:k]
    row: dict[str, float] = {"top_k": k, "n": n}
    for key, fn in (
        ("sale_gt0", lambda s: s > 0),
        ("sale_ge5", lambda s: s >= 5),
        ("sale_ge20", lambda s: s >= 20),
    ):
        mask = fn(sales)
        tp = int(mask[top].sum())
        prec = tp / k
        rec = tp / max(int(mask.sum()), 1)
        base = float(mask.mean())
        row[f"prec_{key}"] = prec
        row[f"rec_{key}"] = rec
        row[f"base_{key}"] = base
        row[f"prec_{key}_lift_vs_base"] = prec / max(base, 1e-9)
    return row


def backup_round1() -> None:
    dst = ART / "_round1"
    dst.mkdir(parents=True, exist_ok=True)
    for name in (
        "metrics_topk.json",
        "metrics_top5pct.json",
        "report.md",
        "top_picks.csv",
        "test_scores.npz",
        "split.json",
        "top5pct_metrics.json",
    ):
        src = ART / name
        if src.exists():
            shutil.copy2(src, dst / name)
    print(f"[backup] 已备份到 {dst}")


def shop_scale_diagnostic(sales: np.ndarray, pred_full: np.ndarray, shop_sales: np.ndarray) -> dict:
    sp_shop, _ = spearmanr(pred_full, shop_sales)
    tert = np.percentile(shop_sales, [33.33, 66.67])
    tiers = {
        "low": shop_sales <= tert[0],
        "mid": (shop_sales > tert[0]) & (shop_sales <= tert[1]),
        "high": shop_sales > tert[1],
    }
    by_tier = {}
    for name, mask in tiers.items():
        if mask.sum() < 10:
            continue
        by_tier[name] = top5pct_row(sales[mask], pred_full[mask])
    return {
        "spearman_pred_full_vs_shop_total_sales": float(sp_shop),
        "shop_sales_tertiles": [float(tert[0]), float(tert[1])],
        "top5pct_by_shop_tier": by_tier,
    }


def stage_eval(repeats: int = 3000, slate_k: int | None = None) -> None:
    t0 = time.perf_counter()
    z = np.load(ART / "test_scores.npz", allow_pickle=True)
    sales = z["sales"].astype(np.float64)
    sources = np.array([str(x) for x in z["source"]])
    full_pred = z["pred_full"].astype(np.float64)
    shop_sales = (
        z["shop_total_sales"].astype(np.float64)
        if "shop_total_sales" in z.files
        else np.zeros(len(sales))
    )

    ks = [20, 50] if slate_k is None else [slate_k]
    results: dict = {}
    rnd_score_rng = np.random.default_rng(SEED + 1)

    for k in ks:
        slates = make_slates(sources, k, repeats, np.random.default_rng(SEED + int(k)))
        results[str(k)] = {}
        for name in EVAL_GROUPS:
            pred = None if name == "random" else z[f"pred_{name}"].astype(np.float64)
            raw = per_slate_metrics(sales, slates, pred, rnd_score_rng)
            results[str(k)][name] = aggregate_slate_metrics(raw)

        rands = {round(results[str(k)][n]["rand"], 9) for n in EVAL_GROUPS}
        oracles = {round(results[str(k)][n]["oracle@1"], 9) for n in EVAL_GROUPS}
        assert len(rands) == 1 and len(oracles) == 1, (
            f"slate 未共用: rand={rands} oracle={oracles}"
        )
        print(f"[eval] K={k} sanity rand={rands.pop():.4f} oracle@1={oracles.pop():.2f}")

        rl5 = results[str(k)]["random"]["lift@5"]
        if not (0.85 <= rl5 <= 1.15):
            print(f"[eval] warn: random lift@5={rl5:.3f} 不在 [0.85,1.15]")

        sp, _ = spearmanr(full_pred, sales)
        results[str(k)]["_spearman_full_vs_sales"] = float(sp)

    with open(ART / "metrics_topk.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    rand_pred = np.random.default_rng(SEED + 99).random(len(sales))
    top5 = {
        name: top5pct_row(
            sales,
            rand_pred if name == "random" else z[f"pred_{name}"].astype(np.float64),
        )
        for name in EVAL_GROUPS
    }
    with open(ART / "metrics_top5pct.json", "w", encoding="utf-8") as f:
        json.dump(top5, f, ensure_ascii=False, indent=2)

    diag = shop_scale_diagnostic(sales, full_pred, shop_sales)
    with open(ART / "shop_scale_diagnostic.json", "w", encoding="utf-8") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2)
    print(
        f"[eval] spearman(pred_full, 店铺总销量)={diag['spearman_pred_full_vs_shop_total_sales']:.4f}"
    )

    test_ids = np.array([str(x) for x in z["ids"]])
    df_emb = pd.read_csv(ART / "dataset_embedded.csv", encoding="utf-8-sig", dtype={"商品ID": str})
    te_ids = set(test_ids)
    sub = df_emb[df_emb["商品ID"].isin(te_ids)].copy()
    pred_map = dict(zip(test_ids, full_pred))
    sub["预测分"] = sub["商品ID"].map(pred_map)
    sub = sub.sort_values("预测分", ascending=False).head(200)
    sub = sub.rename(
        columns={
            "美元价格($)": "美元价格",
            "main_url": "主图URL",
            "cat_l1": "一级类目",
            "cat_l2": "二级类目",
            "总销量": "真实总销量",
        }
    )
    sub.insert(0, "排名", range(1, len(sub) + 1))
    cols = [
        "排名",
        "预测分",
        "商品ID",
        "标题",
        "美元价格",
        "一级类目",
        "二级类目",
        "主图URL",
        "商品链接",
        "source",
        "真实总销量",
    ]
    sub[cols].to_csv(ART / "top_picks.csv", index=False, encoding="utf-8-sig")

    write_report(results, top5, diag)
    elapsed = time.perf_counter() - t0
    print(f"[eval] 完成 耗时 {elapsed:.1f}s")
    m20 = results["20"]["full"]
    m50 = results["50"]["full"] if "50" in results else m20
    print(
        f"[eval] full K=20 lift@5={m20['lift@5']:.3f}  LEAK={results['20']['LEAK_shop']['lift@5']:.3f}"
    )
    print(f"[eval] full K=50 lift@5={m50['lift@5']:.3f}")


def write_report(results: dict, top5: dict, diag: dict) -> None:
    m20 = results["20"]
    full = m20["full"]
    leak = m20["LEAK_shop"]
    tab = m20["tab_only"]
    f5 = top5["full"]
    leak5 = top5["LEAK_shop"]

    round1_path = ART / "_round1" / "metrics_top5pct.json"
    winsor_note = ""
    if round1_path.exists():
        old = json.loads(round1_path.read_text(encoding="utf-8"))
        o, n = old.get("full", {}), f5
        winsor_note = (
            f"\n### Winsorize 前后（full top-5% prec≥5）\n\n"
            f"- 修前（round1）: {o.get('prec_sale_ge5', 0):.3f}\n"
            f"- 修后: {n.get('prec_sale_ge5', 0):.3f}\n"
        )

    leak_pct = (leak["lift@5"] / max(full["lift@5"], 1e-9) - 1) * 100

    lines = [
        "# 选品排序报告（第 2 轮 / REWORK）",
        "",
        "> **适用范围**：本批数据一级类目全部为「家居厨房用品」，模型结论**仅限该大类**，不可当作全站选品。",
        "",
        "## 数据事实（PLAN 第 3 节）",
        "",
        "- 三文件各约 10000 行，去重后约 29871 商品；跨表重复约 258。",
        "- 总销量>0 约 21%~29%；唯一店铺约 10275。",
        "- `店铺总销量` 与商品销量 Spearman≈0.12（店铺列未进 full）。",
        "",
        "### 观察窗口（收录时间口径）",
        "",
        "- 导出条件为 `收录时间` 至少 8 天前；在 676 行有收录时间的样本上，上架−收录**下界恰为 7 天（含首尾 8 天）**。",
        "- **名为 `上架时间` 的列实为抓取时刻**（每文件铺满一整天），不是真实上架时刻。",
        "- 窗口**非常数**：恰好 7 天 55.2%，≤8 天 74.9%，>8 天 25.1%，均值 8.5 天，最长 67 天。",
        "- 评测 slate **仅在同一 source 文件内**抽样。",
        "",
        "## 表 1 — 全量 test Top 5%（主指标，无抽样）",
        "",
        "| 组别 | P(>0) | ×基线 | P(≥5) | ×基线 | P(≥20) | Rec(≥5) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name in EVAL_GROUPS:
        r = top5[name]
        lines.append(
            f"| {name} | {r['prec_sale_gt0']:.3f} | {r['prec_sale_gt0_lift_vs_base']:.2f} | "
            f"{r['prec_sale_ge5']:.3f} | {r['prec_sale_ge5_lift_vs_base']:.2f} | "
            f"{r['prec_sale_ge20']:.3f} | {r['rec_sale_ge5']:.3f} |"
        )
    lines += [
        winsor_note,
        "",
        "## 表 2 — Slate 对照（共用 3000 slates，K=20）",
        "",
        "| 组别 | lift@5 | recovery@5 | hit@1 | hit@5 | ndcg@5 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name in EVAL_GROUPS:
        r = m20[name]
        lines.append(
            f"| {name} | {r['lift@5']:.3f} | {r['recovery@5']:.3f} | "
            f"{r['hit@1']:.3f} | {r['hit@5']:.3f} | {r['ndcg@5']:.3f} |"
        )
    lines += [
        "",
        f"- 全 test Spearman(full 预测分, 总销量) = {results['20'].get('_spearman_full_vs_sales', 0):.4f}",
        "",
        "## LEAK_shop vs full（配对 slate）",
        "",
        f"- `full` lift@5 = **{full['lift@5']:.3f}**；`LEAK_shop` = **{leak['lift@5']:.3f}**（约高 {leak_pct:+.1f}%）。",
        "- 这不是分组泄露作弊（已按店铺隔离 test）。LEAK 用的是店铺规模代理「大店流量」，**搬到自己店不可复现**。",
        f"- 因此 **full 低于 LEAK_shop 是预期且正确的**；差距约 {leak_pct:.1f}% 可视为「大店红利」的量化。",
        f"- Top-5% 上同样：LEAK prec(≥5)={leak5['prec_sale_ge5']:.3f} vs full={f5['prec_sale_ge5']:.3f}。",
        "",
        "## 店铺规模诊断（full）",
        "",
        f"- Spearman(预测分, 店铺总销量) = **{diag['spearman_pred_full_vs_shop_total_sales']:.4f}**",
        "",
    ]
    for tier, row in diag.get("top5pct_by_shop_tier", {}).items():
        lines.append(f"- 店铺规模 **{tier}** 档：top-5% P(≥5) = {row.get('prec_sale_ge5', 0):.3f}")
    lines += [
        "",
        "## 结论",
        "",
        f"- `full` slate lift@5 = {full['lift@5']:.3f}，相对 `tab_only` {tab['lift@5']:.3f} "
        f"（{full['lift@5'] - tab['lift@5']:+.3f}）。",
        f"- 全量 top-5%：有动销 precision {f5['prec_sale_gt0']:.1%}（基线 {f5['base_sale_gt0']:.1%}）。",
        "",
        "## 泄露检查清单",
        "",
        "- [x] 店铺特征未进入 full（仅 LEAK_shop 对照）",
        "- [x] GroupShuffleSplit 按 shop_group",
        "- [x] test 近重复清理",
        "- [x] cat_l2_te 仅用 train；**cat_l1 已剔除（常量列）**",
        "- [x] label 派生列未作特征",
        "- [x] `收录时间` 未使用",
        "- [x] `美区评分` 未使用",
        "- [x] y = log1p(clip(销量, 0, train p99.5))",
        "",
        "## K=50 slate",
        "",
    ]
    if "50" in results:
        for name in ("full", "tab_only", "random", "LEAK_shop"):
            lines.append(f"- {name}: lift@5={results['50'][name]['lift@5']:.3f}")
    (ART / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="rank_products pipeline")
    parser.add_argument(
        "--stage",
        choices=["prep", "download", "embed", "train", "eval", "all"],
        default="all",
    )
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--concurrency", type=int, default=200)
    parser.add_argument("--slate-k", type=int, default=None)
    parser.add_argument("--repeats", type=int, default=3000)
    args = parser.parse_args()

    if args.stage == "prep":
        stage_prep()
    elif args.stage == "download":
        stage_download(concurrency=args.concurrency, skip_download=args.skip_download)
    elif args.stage == "embed":
        stage_embed()
    elif args.stage == "train":
        stage_train()
    elif args.stage == "eval":
        stage_eval(repeats=args.repeats, slate_k=args.slate_k)
    elif args.stage == "all":
        stage_prep()
        stage_download(concurrency=args.concurrency, skip_download=args.skip_download)
        stage_embed()
        stage_train()
        stage_eval(repeats=args.repeats, slate_k=args.slate_k)


if __name__ == "__main__":
    main()
