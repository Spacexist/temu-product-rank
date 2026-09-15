# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import aiohttp
import numpy as np
import torch
import torch.nn as nn
from PIL import Image
from sentence_transformers import SentenceTransformer
from torchvision import models


def url_to_path(url: str, cache_dirs: list[Path]) -> Path:
    h = hashlib.md5(url.encode("utf-8")).hexdigest()
    ext = ".jpg"
    low = url.lower()
    if ".png" in low:
        ext = ".png"
    elif ".webp" in low:
        ext = ".webp"
    elif ".jpeg" in low:
        ext = ".jpeg"
    for d in cache_dirs:
        p = d / f"{h}{ext}"
        if p.exists() and p.stat().st_size > 1024:
            return p
    return cache_dirs[-1] / f"{h}{ext}"


def image_ok(url: str, cache_dirs: list[Path]) -> bool:
    if not url:
        return False
    p = url_to_path(url, cache_dirs)
    return p.exists() and p.stat().st_size > 1024


async def _download_one(session, url: str, dest: Path, sem: asyncio.Semaphore):
    if dest.exists() and dest.stat().st_size > 1024:
        return url, True
    async with sem:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status != 200:
                    return url, False
                data = await resp.read()
                if len(data) < 1024:
                    return url, False
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_suffix(dest.suffix + ".part")
                tmp.write_bytes(data)
                tmp.replace(dest)
                return url, True
        except Exception:
            return url, False


async def download_urls(urls: list[str], cache_dirs: list[Path], concurrency: int):
    """下载当前预测文件缺失的主图，供没有图片向量缓存的 SKU 生成 embedding。"""
    import sys
    from pathlib import Path

    _root = Path(__file__).resolve().parents[2]
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    try:
        from temu_region import temu_aiohttp_headers
    except ModuleNotFoundError:
        sys.path.insert(0, str(_root / "pipeline"))
        from temu_region import temu_aiohttp_headers

    headers = temu_aiohttp_headers()
    sem = asyncio.Semaphore(concurrency)
    connector = aiohttp.TCPConnector(limit=concurrency, ssl=False)
    async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
        tasks = []
        for u in urls:
            if u:
                tasks.append(_download_one(session, u, url_to_path(u, cache_dirs), sem))
        if not tasks:
            return {}
        results = await asyncio.gather(*tasks)
    return {url: ok for url, ok in results}


def device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


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
def embed_images(paths: list[Path | None], batch: int = 32) -> tuple[np.ndarray, np.ndarray]:
    n = len(paths)
    out = np.zeros((n, 512), dtype=np.float32)
    missing = np.ones(n, dtype=bool)
    model, tfm = build_resnet()
    dev = device()
    model = model.to(dev)
    batch_idx: list[int] = []
    batch_tensors: list = []

    def flush():
        nonlocal batch_idx, batch_tensors
        if not batch_tensors:
            return
        x = torch.stack(batch_tensors).to(dev)
        feat = l2_normalize(model(x).cpu().numpy())
        for j, i in enumerate(batch_idx):
            out[i] = feat[j]
            missing[i] = False
        batch_idx = []
        batch_tensors = []

    for i, p in enumerate(paths):
        if not p or not p.exists():
            continue
        try:
            im = Image.open(p).convert("RGB")
            batch_tensors.append(tfm(im))
            batch_idx.append(i)
            if len(batch_tensors) >= batch:
                flush()
        except Exception:
            continue
    flush()
    return out, missing


def embed_texts(texts: list[str], model_name: str, batch: int = 32) -> np.ndarray:
    model = SentenceTransformer(model_name)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model = model.to(dev)
    return model.encode(
        texts,
        batch_size=batch,
        show_progress_bar=len(texts) > 200,
        normalize_embeddings=True,
        convert_to_numpy=True,
    ).astype(np.float32)
