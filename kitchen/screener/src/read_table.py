# -*- coding: utf-8 -*-
from __future__ import annotations

import ast
import re
from pathlib import Path

import numpy as np
import pandas as pd

URL_RE = re.compile(r"https?://[^\s\],>]+")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")


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


def title_text(row) -> str:
    cn = row.get("商品标题（中文）")
    if pd.notna(cn) and str(cn).strip():
        return str(cn).strip()
    return str(row.get("商品标题（英文）", "")).strip()


def norm_id(val) -> str:
    s = str(val).strip()
    if s.endswith(".0"):
        return s[:-2]
    return s


def read_input(path: Path, source_label: str) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        try:
            df = pd.read_excel(path, sheet_name="sheet", header=[0, 1])
            df = flatten_columns(df)
        except Exception:
            df = pd.read_csv(path, encoding="utf-8-sig")
            for drop in ("banned", "banned_hits", "main_url"):
                if drop in df.columns:
                    df = df.drop(columns=[drop])
    else:
        df = pd.read_excel(path, sheet_name="sheet", header=[0, 1])
        df = flatten_columns(df)
    df["来源文件"] = source_label
    df["商品ID"] = df["商品ID"].map(norm_id)
    df["美元价格($)"] = pd.to_numeric(df["美元价格($)"], errors="coerce")
    if "总销量" in df.columns:
        df["总销量"] = pd.to_numeric(df["总销量"], errors="coerce").fillna(0)
        df = df.sort_values(["商品ID", "总销量"], ascending=[True, False])
    else:
        df = df.sort_values("商品ID")
    df = df.drop_duplicates("商品ID", keep="first")
    df = df[df["美元价格($)"].notna() & (df["美元价格($)"] > 0)].copy()

    df["main_url"] = df["商品主图"].map(lambda x: parse_urls(x)[:1]).map(
        lambda xs: xs[0] if xs else ""
    )
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
    link_col = "商品链接" if "商品链接" in df.columns else None
    df["商品链接"] = df[link_col].astype(str) if link_col else ""
    return df.reset_index(drop=True)
