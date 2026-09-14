# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

import pandas as pd
import zhconv

SKIP_HINT = re.compile(r"(那些|类)")


def normalize_match(s: str) -> str:
    s = unicodedata.normalize("NFKC", str(s))
    s = zhconv.convert(s, "zh-cn")
    s = s.lower()
    s = re.sub(r"[\s_\-·.]+", "", s)
    return s


def load_words(words_file: Path, out_json: Path) -> list[dict]:
    raw_lines = words_file.read_text(encoding="utf-8").splitlines()
    seen_norm: set[str] = set()
    entries: list[dict] = []
    suspicious: list[str] = []
    for line in raw_lines:
        w = line.strip()
        if not w:
            continue
        if len(w) > 4 and SKIP_HINT.search(w):
            suspicious.append(w)
            continue
        n = normalize_match(w)
        if not n or n in seen_norm:
            continue
        seen_norm.add(n)
        entries.append({"raw": w, "norm": n})
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(
        json.dumps({"words": entries, "suspicious_skipped": suspicious}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if suspicious:
        print(f"[word_filter] 跳过可疑说明行 {len(suspicious)} 条（见 words_normalized.json）")
    return entries


def product_text(row: pd.Series) -> str:
    parts = []
    for col in (
        "商品标题（中文）",
        "商品标题（英文）",
        "标题",
        "前台分类（中文）",
        "前台分类（英文）",
    ):
        if col in row.index and pd.notna(row[col]):
            parts.append(str(row[col]))
    return " ".join(parts)


def apply_banned(df: pd.DataFrame, entries: list[dict]) -> pd.DataFrame:
    norms = [e["norm"] for e in entries]
    raw_map = {e["norm"]: e["raw"] for e in entries}
    banned = []
    hits_col = []
    hit_counter: Counter = Counter()
    for _, row in df.iterrows():
        text = normalize_match(product_text(row))
        hits = []
        for n in norms:
            if n and n in text:
                hits.append(raw_map.get(n, n))
                hit_counter[n] += 1
        banned.append(bool(hits))
        hits_col.append("|".join(dict.fromkeys(hits)))
    out = df.copy()
    out["banned"] = banned
    out["banned_hits"] = hits_col
    return out, hit_counter


def log_stats(df: pd.DataFrame, n_words: int, hit_counter: Counter) -> None:
    n_hit = int(df["banned"].sum())
    print(f"[word_filter] 词表 {n_words} 条 · 命中商品 {n_hit}/{len(df)}")
    top = hit_counter.most_common(20)
    if top:
        print("[word_filter] 命中 Top20 词:")
        for w, c in top:
            print(f"  {w}: {c}")
