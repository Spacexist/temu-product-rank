# -*- coding: utf-8 -*-
"""
新品走量试跑：销量>0，不用店铺/时间/销量/GMV 当特征。
三路对照：只标题 / 只图 / 图+标题+类目+价格+视频。
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import time
from pathlib import Path

import aiohttp
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from PIL import Image
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import GroupShuffleSplit
from torch.utils.data import DataLoader, TensorDataset
from torchvision import models, transforms

ROOT = Path(__file__).resolve().parent
CLIP_DIR = Path(r"F:\Clip")
DATA_FILES = [
    ROOT / "909.xlsx",
    ROOT / "910.csv",
    ROOT / "911.csv",
]
CACHE = ROOT / "hit_cache"
IMG_DIR = CACHE / "images"
ART = CACHE / "artifacts"
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
URL_RE = re.compile(r"https?://[^\s\]\],>]+")
SEED = 42


def is_english_title(text) -> bool:
    if pd.isna(text):
        return False
    s = str(text).strip()
    if len(s) < 8:
        return False
    cjk = len(CJK_RE.findall(s))
    letters = len(re.findall(r"[A-Za-z]", s))
    if letters < 12:
        return False
    if cjk >= 8:
        return False
    if cjk > 0 and cjk >= letters * 0.25:
        return False
    return True


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


def load_all() -> pd.DataFrame:
    frames = []
    for path in DATA_FILES:
        df = pd.read_excel(path, sheet_name="sheet", header=[0, 1])
        df = flatten_columns(df)
        df["source"] = path.name
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    need = [
        "店铺ID",
        "商品ID",
        "商品标题（英文）",
        "商品主图",
        "商品轮播图",
        "商品视频",
        "前台分类（中文）",
        "美元价格($)",
        "总销量",
    ]
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise SystemExit(f"缺列: {missing} 实际列={list(df.columns)}")
    df = df[need + ["source"]].copy()
    df["商品ID"] = df["商品ID"].astype(str)
    df["总销量"] = pd.to_numeric(df["总销量"], errors="coerce").fillna(0)
    df["美元价格($)"] = pd.to_numeric(df["美元价格($)"], errors="coerce")
    df["label"] = (df["总销量"] > 0).astype(int)
    df = df.sort_values(["商品ID", "总销量"], ascending=[True, False])
    df = df.drop_duplicates("商品ID", keep="first")
    df["title_en"] = df["商品标题（英文）"].astype(str)
    df = df[df["title_en"].map(is_english_title)].copy()
    df = df[df["美元价格($)"].notna() & (df["美元价格($)"] > 0)].copy()
    df["shop_id"] = df["店铺ID"].apply(
        lambda x: f"shop_{int(x)}" if pd.notna(x) else None
    )
    missing_shop = df["shop_id"].isna()
    df.loc[missing_shop, "shop_id"] = [
        f"row_{i}" for i in df.loc[missing_shop].index
    ]
    df["main_url"] = df["商品主图"].map(lambda x: parse_urls(x)[:1]).map(
        lambda xs: xs[0] if xs else ""
    )
    df = df[df["main_url"] != ""].copy()

    def gallery_extra(row):
        urls = parse_urls(row["商品轮播图"])
        extra = [u for u in urls if u != row["main_url"]][:3]
        return extra

    df["gallery_urls"] = df.apply(gallery_extra, axis=1)
    df["has_video"] = df["商品视频"].apply(
        lambda x: 1 if pd.notna(x) and str(x).strip() and str(x).lower() != "nan" else 0
    )
    df["category"] = df["前台分类（中文）"].fillna("未知").astype(str)
    df["log_price"] = np.log1p(df["美元价格($)"].astype(float))
    df = df.reset_index(drop=True)
    return df


def split_and_sample(df: pd.DataFrame, rng: np.random.RandomState):
    gss = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=SEED)
    train_idx, test_idx = next(gss.split(df, df["label"], groups=df["shop_id"]))
    train_pool = df.iloc[train_idx].copy()
    test_pool = df.iloc[test_idx].copy()

    pos = train_pool[train_pool["label"] == 1]
    neg = train_pool[train_pool["label"] == 0]
    n_pos = min(1500, len(pos))
    n_neg = min(3000, len(neg))
    train_cand = pd.concat(
        [
            pos.sample(n=n_pos, random_state=SEED) if len(pos) else pos,
            neg.sample(n=n_neg, random_state=SEED) if len(neg) else neg,
        ]
    ).sample(frac=1, random_state=SEED)

    n_test = min(2500, len(test_pool))
    test_cand = test_pool.sample(n=n_test, random_state=SEED)
    return train_cand.reset_index(drop=True), test_cand.reset_index(drop=True)


async def _download_one(session, url: str, sem: asyncio.Semaphore) -> bool:
    dest = url_to_path(url)
    if dest.exists() and dest.stat().st_size > 1024:
        return True
    async with sem:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status != 200:
                    return False
                data = await resp.read()
                if len(data) < 1024:
                    return False
                tmp = dest.with_suffix(dest.suffix + ".part")
                tmp.write_bytes(data)
                tmp.replace(dest)
                return True
        except Exception:
            return False


async def download_urls(urls: list[str], concurrency: int = 200) -> dict[str, bool]:
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.temu.com/",
    }
    connector = aiohttp.TCPConnector(limit=concurrency, ssl=False)
    sem = asyncio.Semaphore(concurrency)
    async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
        tasks = [_download_one(session, u, sem) for u in urls]
        flags = await asyncio.gather(*tasks)
    return dict(zip(urls, flags))


def collect_urls(df: pd.DataFrame) -> list[str]:
    urls = []
    for _, row in df.iterrows():
        urls.append(row["main_url"])
        urls.extend(row["gallery_urls"])
    # unique keep order
    seen, out = set(), []
    for u in urls:
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def keep_downloaded(df: pd.DataFrame, ok: dict[str, bool]) -> pd.DataFrame:
    def main_ok(row):
        p = url_to_path(row["main_url"])
        return p.exists() and p.stat().st_size > 1024

    df = df[df.apply(main_ok, axis=1)].copy()

    def filter_gal(row):
        keep = []
        for u in row["gallery_urls"]:
            p = url_to_path(u)
            if p.exists() and p.stat().st_size > 1024:
                keep.append(u)
        return keep[:3]

    df["gallery_urls"] = df.apply(filter_gal, axis=1)
    return df.reset_index(drop=True)


def finalize_splits(train_cand: pd.DataFrame, test_cand: pd.DataFrame, rng: np.random.RandomState):
    pos = train_cand[train_cand["label"] == 1]
    neg = train_cand[train_cand["label"] == 0]
    n_pos = min(1000, len(pos))
    n_neg = min(2000, len(neg))
    if n_pos < 200 or n_neg < 400:
        print(f"[warn] 训练可用偏少 pos={len(pos)} neg={len(neg)}，将就现有样本")
    train = pd.concat(
        [
            pos.sample(n=n_pos, random_state=SEED),
            neg.sample(n=n_neg, random_state=SEED),
        ]
    ).sample(frac=1, random_state=SEED)
    test = test_cand.copy()
    return train.reset_index(drop=True), test.reset_index(drop=True)


def device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def img_batch_size() -> int:
    # 1050 Ti 4GB：ResNet18 用 16 更稳
    return 16 if device().type == "cuda" else 8


def build_resnet():
    weights = models.ResNet18_Weights.IMAGENET1K_V1
    model = models.resnet18(weights=weights)
    model.fc = nn.Identity()
    model.eval()
    tfm = weights.transforms()
    return model, tfm


def load_rgb(path: Path) -> Image.Image:
    im = Image.open(path).convert("RGB")
    return im


@torch.no_grad()
def embed_paths(model, tfm, paths: list[Path], dev: torch.device, batch=16) -> np.ndarray:
    vecs = []
    model = model.to(dev)
    for i in range(0, len(paths), batch):
        chunk = paths[i : i + batch]
        tensors = []
        for p in chunk:
            try:
                tensors.append(tfm(load_rgb(p)))
            except Exception:
                tensors.append(torch.zeros(3, 224, 224))
        x = torch.stack(tensors).to(dev)
        feat = model(x).cpu().numpy()
        vecs.append(feat)
        if i % (batch * 20) == 0:
            print(f"  img {min(i+batch, len(paths))}/{len(paths)}", flush=True)
    return np.concatenate(vecs, axis=0) if vecs else np.zeros((0, 512), dtype=np.float32)


def image_features_for_df(df: pd.DataFrame, model, tfm, dev, cache_name: str) -> np.ndarray:
    ART.mkdir(parents=True, exist_ok=True)
    cache_file = ART / cache_name
    ids = df["商品ID"].tolist()
    if cache_file.exists():
        z = np.load(cache_file, allow_pickle=True)
        if list(z["ids"]) == ids:
            return z["X"]
    all_urls = []
    spans = []
    for _, row in df.iterrows():
        pack = [row["main_url"]] + list(row["gallery_urls"])
        spans.append((len(all_urls), len(all_urls) + len(pack)))
        all_urls.extend(pack)
    paths = [url_to_path(u) for u in all_urls]
    feats = embed_paths(model, tfm, paths, dev, batch=img_batch_size())
    rows = []
    for a, b in spans:
        rows.append(feats[a:b].mean(axis=0))
    X = np.stack(rows).astype(np.float32)
    np.savez_compressed(cache_file, ids=np.array(ids, dtype=object), X=X)
    return X


def text_features_for_df(df: pd.DataFrame, cache_name: str) -> np.ndarray:
    import open_clip

    cache_file = ART / cache_name
    ids = df["商品ID"].tolist()
    if cache_file.exists():
        z = np.load(cache_file, allow_pickle=True)
        if list(z["ids"]) == ids:
            return z["X"]
    # 用 F:\Clip 本地 OpenCLIP 文本塔，避免再下 HuggingFace MiniLM
    model_path = CLIP_DIR / "models" / "open_clip_pytorch_model.bin"
    if not model_path.exists():
        raise FileNotFoundError(f"找不到本地 CLIP: {model_path}")
    dev = device()
    model, _, _ = open_clip.create_model_and_transforms("ViT-B-32", pretrained=str(model_path))
    tokenizer = open_clip.get_tokenizer("ViT-B-32")
    model = model.to(dev)
    model.eval()
    texts = df["title_en"].tolist()
    vecs = []
    bs = 8 if dev.type == "cuda" else 16
    with torch.inference_mode():
        for i in range(0, len(texts), bs):
            chunk = texts[i : i + bs]
            tokens = tokenizer(chunk).to(dev)
            feat = model.encode_text(tokens)
            feat = feat / feat.norm(dim=-1, keepdim=True)
            vecs.append(feat.detach().cpu().numpy().astype(np.float32))
            if i % 128 == 0:
                print(f"  text {min(i+bs, len(texts))}/{len(texts)}", flush=True)
    del model
    if dev.type == "cuda":
        torch.cuda.empty_cache()
    X = np.concatenate(vecs, axis=0)
    np.savez_compressed(cache_file, ids=np.array(ids, dtype=object), X=X)
    return X


def tab_features(train: pd.DataFrame, test: pd.DataFrame):
    cats = sorted(train["category"].unique().tolist())
    cat_index = {c: i for i, c in enumerate(cats)}

    def onehot(frame):
        m = np.zeros((len(frame), len(cats)), dtype=np.float32)
        for i, c in enumerate(frame["category"].tolist()):
            j = cat_index.get(c)
            if j is not None:
                m[i, j] = 1.0
        price = frame["log_price"].to_numpy(dtype=np.float32)[:, None]
        video = frame["has_video"].to_numpy(dtype=np.float32)[:, None]
        return np.concatenate([m, price, video], axis=1)

    return onehot(train), onehot(test), cats


class Head(nn.Module):
    def __init__(self, d_in: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(d_in, 64),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(64, 1),
        )

    def forward(self, x):
        return self.net(x).squeeze(-1)


def train_head(Xtr, ytr, Xte, yte, name: str, epochs=40, lr=1e-3):
    dev = device()
    Xtr_t = torch.tensor(Xtr, dtype=torch.float32)
    ytr_t = torch.tensor(ytr, dtype=torch.float32)
    Xte_t = torch.tensor(Xte, dtype=torch.float32)
    n_pos = float((ytr == 1).sum())
    n_neg = float((ytr == 0).sum())
    pos_weight = torch.tensor([n_neg / max(n_pos, 1.0)], device=dev)
    model = Head(Xtr.shape[1]).to(dev)
    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    loader = DataLoader(TensorDataset(Xtr_t, ytr_t), batch_size=64, shuffle=True)
    best_auc, best_state, wait = -1.0, None, 0
    for ep in range(1, epochs + 1):
        model.train()
        for xb, yb in loader:
            xb, yb = xb.to(dev), yb.to(dev)
            opt.zero_grad()
            loss = loss_fn(model(xb), yb)
            loss.backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            logits = model(Xtr_t.to(dev)).cpu().numpy()
        proba = 1 / (1 + np.exp(-logits))
        auc = roc_auc_score(ytr, proba)
        if auc > best_auc + 1e-4:
            best_auc = auc
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            wait = 0
        else:
            wait += 1
        if wait >= 8:
            break
        print(f"  {name} epoch {ep:02d} train_auc={auc:.4f}")
    model.load_state_dict(best_state)
    model.eval()
    with torch.no_grad():
        te_logits = model(Xte_t.to(dev)).cpu().numpy()
        tr_logits = model(Xtr_t.to(dev)).cpu().numpy()
    te_p = 1 / (1 + np.exp(-te_logits))
    tr_p = 1 / (1 + np.exp(-tr_logits))
    return {
        "name": name,
        "train_auc": float(roc_auc_score(ytr, tr_p)),
        "train_prauc": float(average_precision_score(ytr, tr_p)),
        "test_auc": float(roc_auc_score(yte, te_p)),
        "test_prauc": float(average_precision_score(yte, te_p)),
        "test_pos_rate": float(yte.mean()),
        "train_n": int(len(ytr)),
        "train_pos": int(ytr.sum()),
        "test_n": int(len(yte)),
        "test_pos": int(yte.sum()),
        "epochs_ran": ep,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--concurrency", type=int, default=200)
    parser.add_argument("--skip-download", action="store_true")
    args = parser.parse_args()

    rng = np.random.RandomState(SEED)
    CACHE.mkdir(parents=True, exist_ok=True)
    ART.mkdir(parents=True, exist_ok=True)
    print("device:", device())
    print("[1] 读表并过滤英文标题…")
    df = load_all()
    print(
        f"  英文可用 {len(df)}  pos={int(df['label'].sum())} "
        f"neg={int((df['label']==0).sum())} shops={df['shop_id'].nunique()}"
    )
    train_cand, test_cand = split_and_sample(df, rng)
    print(f"  候选 train={len(train_cand)} test={len(test_cand)}")

    cand = pd.concat([train_cand, test_cand], ignore_index=True)
    urls = collect_urls(cand)
    print(f"[2] 下载图片 {len(urls)} 个 URL，并发 {args.concurrency}")
    t0 = time.time()
    if not args.skip_download:
        ok = asyncio.run(download_urls(urls, args.concurrency))
        n_ok = sum(1 for v in ok.values() if v)
        print(f"  成功 {n_ok}/{len(urls)}  用时 {time.time()-t0:.1f}s")
    else:
        ok = {}

    train_cand = keep_downloaded(train_cand, ok)
    test_cand = keep_downloaded(test_cand, ok)
    train, test = finalize_splits(train_cand, test_cand, rng)
    print(
        f"[3] 最终 train={len(train)} pos={int(train.label.sum())} | "
        f"test={len(test)} pos={int(test.label.sum())} pos_rate={test.label.mean():.3f}"
    )
    train.drop(columns=["gallery_urls"]).to_csv(ART / "train.csv", index=False, encoding="utf-8-sig")
    test.drop(columns=["gallery_urls"]).to_csv(ART / "test.csv", index=False, encoding="utf-8-sig")

    print("[4] ResNet18 抽图特征…")
    resnet, tfm = build_resnet()
    img_tr = image_features_for_df(train, resnet, tfm, device(), "img_train.npz")
    img_te = image_features_for_df(test, resnet, tfm, device(), "img_test.npz")
    del resnet
    if device().type == "cuda":
        torch.cuda.empty_cache()
    print("[5] 本地 OpenCLIP 抽标题特征…")
    txt_tr = text_features_for_df(train, "txt_train.npz")
    txt_te = text_features_for_df(test, "txt_test.npz")
    tab_tr, tab_te, cats = tab_features(train, test)
    print(f"  类目数 {len(cats)}")

    ytr = train["label"].to_numpy()
    yte = test["label"].to_numpy()
    results = []
    print("[6] 训练三路小分类头…")
    results.append(train_head(txt_tr, ytr, txt_te, yte, "title_only"))
    results.append(train_head(img_tr, ytr, img_te, yte, "image_only"))
    joint_tr = np.concatenate([img_tr, txt_tr, tab_tr], axis=1)
    joint_te = np.concatenate([img_te, txt_te, tab_te], axis=1)
    results.append(train_head(joint_tr, ytr, joint_te, yte, "joint"))

    out = {
        "device": str(device()),
        "note": "店铺分组切分；测试集保持自然正例比例；特征不含店铺/时间/销量/GMV",
        "results": results,
    }
    (ART / "metrics.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n==== 测试集结果 ====")
    for r in results:
        print(
            f"{r['name']:12s}  AUC={r['test_auc']:.4f}  PR-AUC={r['test_prauc']:.4f}  "
            f"n={r['test_n']} pos={r['test_pos']}"
        )
    print("已写入", ART / "metrics.json")


if __name__ == "__main__":
    main()
