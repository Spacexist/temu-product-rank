# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

import numpy as np


def norm_id(pid: str) -> str:
    s = str(pid).strip()
    if s.endswith(".0"):
        return s[:-2]
    return s


def load_pair(art_dir: Path) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]] | None:
    img_p = art_dir / "img.npz"
    txt_p = art_dir / "txt.npz"
    if not img_p.is_file() or not txt_p.is_file():
        return None
    z_img = np.load(img_p, allow_pickle=True)
    z_txt = np.load(txt_p, allow_pickle=True)
    img_map = {norm_id(i): v for i, v in zip(z_img["ids"], z_img["X"])}
    txt_map = {norm_id(i): v for i, v in zip(z_txt["ids"], z_txt["X"])}
    return img_map, txt_map


def fill_from_cache(
    ids: list[str],
    img_map: dict[str, np.ndarray],
    txt_map: dict[str, np.ndarray],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = len(ids)
    X_img = np.zeros((n, 512), dtype=np.float32)
    X_txt = np.zeros((n, 512), dtype=np.float32)
    miss = np.ones(n, dtype=bool)
    for i, pid in enumerate(ids):
        pid = norm_id(pid)
        if pid in img_map and pid in txt_map:
            X_img[i] = img_map[pid]
            X_txt[i] = txt_map[pid]
            miss[i] = False
    return X_img, X_txt, miss
