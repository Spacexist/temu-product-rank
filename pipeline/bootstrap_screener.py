# -*- coding: utf-8 -*-
"""把 _screener_pkg 同步到桌面「选品筛子」并复制 model / 违禁词。"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PKG = ROOT / "_screener_pkg"
DESKTOP = Path(r"C:\Users\ZFGJ-WCH\Desktop") / "\u9009\u54c1\u7b5b\u5b50"
BANNED_SRC = Path(
    r"c:\Users\ZFGJ-WCH\xwechat_files\wxid_bz7neadi4p6t12_8f47\business\favorite\temp\新建文件夹\查价格与违规\违禁词与侵权.txt"
)


def main() -> None:
    if not PKG.is_dir():
        raise SystemExit(f"缺少 {PKG}")
    DESKTOP.mkdir(parents=True, exist_ok=True)
    for name in ("src", "words", "cache", "output", "model"):
        dst = DESKTOP / name
        src = PKG / name if (PKG / name).exists() else None
        if name == "model":
            src = ROOT / "_screener_bundle" / "model"
        if name in ("cache", "output"):
            (DESKTOP / name / ("images" if name == "cache" else "")).mkdir(
                parents=True, exist_ok=True
            )
            continue
        if src and src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
    for f in ("README.md", "requirements.txt"):
        shutil.copy2(PKG / f, DESKTOP / f)
    cfg = json.loads((PKG / "config.json").read_text(encoding="utf-8"))
    cfg["embed_cache_art_dir"] = "../8天前数据/artifacts_v2"
    cfg["image_cache_dirs"] = [
        "../8天前数据/hit_cache/images",
        "cache/images",
    ]
    (DESKTOP / "config.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    words = DESKTOP / "words" / "违禁词与侵权.txt"
    if BANNED_SRC.is_file() and not words.is_file():
        words.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(BANNED_SRC, words)
    print(f"[bootstrap] OK -> {DESKTOP}")


if __name__ == "__main__":
    main()
