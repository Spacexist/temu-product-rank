# -*- coding: utf-8 -*-
"""去重（含对照训练样本库）→ 无收录时间 → 剔除违禁词。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
ART = ROOT / "artifacts_v2"
PKG = ROOT / "_screener_pkg"
sys.path.insert(0, str(PKG / "src"))
from read_table import parse_urls, title_text  # noqa: E402
from word_filter import apply_banned, load_words  # noqa: E402


def flat(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [
            str(b).strip()
            if not str(b).startswith("Unnamed")
            else str(a).strip()
            for a, b in df.columns
        ]
    return df


def no_shoulu(series: pd.Series) -> pd.Series:
    return series.isna() | (series.astype(str).str.strip() == "") | (
        series.astype(str).str.lower() == "nan"
    )


def load_train_keys() -> tuple[set[str], set[str], set[str]]:
    """与 rank_products 训练折一致：dataset.csv split=train + embedded 的 url/标题。"""
    ds = pd.read_csv(ART / "dataset.csv", encoding="utf-8-sig", dtype={"商品ID": str})
    train_ids = set(ds.loc[ds["split"] == "train", "商品ID"].astype(str))
    emb = pd.read_csv(ART / "dataset_embedded.csv", encoding="utf-8-sig", dtype={"商品ID": str})
    train_emb = emb[emb["商品ID"].isin(train_ids)]
    train_urls = set(train_emb["main_url"].dropna().astype(str)) - {""}
    train_titles = set(train_emb["标题"].astype(str).str.strip()) - {""}
    return train_ids, train_urls, train_titles


def drop_vs_train(df: pd.DataFrame, train_ids: set[str], train_urls: set[str], train_titles: set[str]):
    df = df.copy()
    df["main_url"] = df["商品主图"].map(lambda x: parse_urls(x)[:1]).map(lambda xs: xs[0] if xs else "")
    df["标题"] = df.apply(title_text, axis=1)
    m_id = df["商品ID"].astype(str).isin(train_ids)
    m_url = df["main_url"].astype(str).isin(train_urls)
    m_title = df["标题"].astype(str).str.strip().isin(train_titles)
    stats = {
        "商品ID": int(m_id.sum()),
        "main_url": int((~m_id & m_url).sum()),
        "title": int((~m_id & ~m_url & m_title).sum()),
    }
    keep = ~(m_id | m_url | m_title)
    return df[keep].copy(), stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--input",
        default=r"c:\Users\ZFGJ-WCH\Downloads\2098682172555476993.csv",
    )
    args = ap.parse_args()
    inp = Path(args.input)
    out = inp.with_name(inp.stem + "_无收录_去重训练库_无违禁.csv")
    words = PKG / "words" / "违禁词与侵权.txt"
    norm = PKG / "words" / "words_normalized.json"

    train_ids, train_urls, train_titles = load_train_keys()
    print(
        f"[train] 对照训练折: ID {len(train_ids)} · 主图URL {len(train_urls)} · 标题 {len(train_titles)}"
    )

    df = flat(pd.read_excel(inp, sheet_name="sheet", header=[0, 1]))
    n0 = len(df)
    df["商品ID"] = df["商品ID"].astype(str)
    if "总销量" in df.columns:
        df["总销量"] = pd.to_numeric(df["总销量"], errors="coerce").fillna(0)
        df = df.sort_values(["商品ID", "总销量"], ascending=[True, False])
    df = df.drop_duplicates("商品ID", keep="first")
    n1 = len(df)

    df, tstats = drop_vs_train(df, train_ids, train_urls, train_titles)
    n1b = len(df)

    if "收录时间" not in df.columns:
        raise SystemExit("缺少列：收录时间")
    df = df[no_shoulu(df["收录时间"])].copy()
    n2 = len(df)

    entries = load_words(words, norm)
    df, hit_counter = apply_banned(df, entries)
    n_ban = int(df["banned"].sum())
    df = df[~df["banned"]].copy()
    n3 = len(df)

    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(
        f"原始 {n0} → 本表去重 {n1} → 剔除训练库重合 {n1 - n1b} "
        f"(ID {tstats['商品ID']} / URL {tstats['main_url']} / 标题 {tstats['title']}) "
        f"→ 无收录 {n2} → 剔除违禁 {n_ban} → 输出 {n3}"
    )
    if hit_counter:
        print("违禁 Top10:", hit_counter.most_common(10))
    print(f"写入 {out}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
