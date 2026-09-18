# -*- coding: utf-8 -*-
"""数分 pipeline：raw → cleaned → scored → Top → 已发布 HTML，输出以图为主的分析页。

日更末步由 daily.py 调用；单独跑：跑分析.bat
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "screener" / "src"))
sys.path.insert(0, str(ROOT / "pipeline"))

from word_filter import apply_banned, load_words  # noqa: E402

OUTPUT = ROOT / "output"
CLEANED = ROOT / "data" / "cleaned"
RAW = ROOT / "data" / "raw"
WORDS = ROOT / "words" / "banned.txt"
WORDS_JSON = ROOT / "words" / "words_normalized.json"

PRICE_BANDS = [
    (0, 3, "<$3"),
    (3, 5, "$3–5"),
    (5, 8, "$5–8"),
    (8, 12, "$8–12"),
    (12, 20, "$12–20"),
    (20, 1e9, "$20+"),
]
SALES_BANDS = [
    (0, 1, "0"),
    (1, 2, "1"),
    (2, 6, "2–5"),
    (6, 21, "6–20"),
    (21, 1e9, "20+"),
]


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").fillna(0)


def _pct(n: float, d: float) -> float:
    return round(100.0 * n / d, 1) if d else 0.0


def _ids_from_html(path: Path) -> set[str]:
    if not path or not path.is_file():
        return set()
    text = path.read_text(encoding="utf-8", errors="ignore")
    return set(re.findall(r'data-id="([^"]+)"', text))


def _latest(folder: Path, pattern: str) -> Path | None:
    hits = sorted(folder.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return hits[0] if hits else None


def _l1_of(df: pd.DataFrame) -> pd.Series:
    if "一级类目" in df.columns:
        return df["一级类目"].fillna("未知").astype(str)
    if "cat_l1" in df.columns:
        return df["cat_l1"].fillna("未知").astype(str)
    if "前台分类（中文）" in df.columns:
        return df["前台分类（中文）"].fillna("未知").astype(str).str.split("/", n=1).str[0]
    return pd.Series(["未知"] * len(df), index=df.index)


def _l2_of(df: pd.DataFrame) -> pd.Series:
    if "二级类目" in df.columns:
        return df["二级类目"].fillna("未知").astype(str)
    if "cat_l2" in df.columns:
        return df["cat_l2"].fillna("未知").astype(str)
    if "前台分类（中文）" in df.columns:
        parts = df["前台分类（中文）"].fillna("").astype(str).str.split("/", n=2, expand=True)
        return parts[1].fillna("未知") if 1 in parts.columns else pd.Series(["未知"] * len(df))
    return pd.Series(["未知"] * len(df), index=df.index)


def _price_of(df: pd.DataFrame) -> pd.Series:
    for c in ("美元价格", "美元价格($)"):
        if c in df.columns:
            return _num(df[c])
    return pd.Series(np.zeros(len(df)))


def _sales_of(df: pd.DataFrame) -> pd.Series:
    if "总销量" in df.columns:
        return _num(df["总销量"])
    return pd.Series(np.zeros(len(df)))


def _band(values: pd.Series, bands: list[tuple]) -> pd.Series:
    out = pd.Series(["?"] * len(values), index=values.index)
    for lo, hi, name in bands:
        out[(values >= lo) & (values < hi)] = name
    return out


def block_stats(df: pd.DataFrame, name: str) -> dict:
    sales = _sales_of(df)
    price = _price_of(df)
    pos = sales > 0
    shops = df["店铺ID"].nunique() if "店铺ID" in df.columns else 0
    return {
        "name": name,
        "n": int(len(df)),
        "shops": int(shops),
        "pos_rate": round(float(pos.mean()) if len(df) else 0, 3),
        "sales_mean": round(float(sales.mean()) if len(df) else 0, 2),
        "sales_median": round(float(sales.median()) if len(df) else 0, 2),
        "sales_p90": round(float(sales.quantile(0.9)) if len(df) else 0, 2),
        "sales_max": round(float(sales.max()) if len(df) else 0, 2),
        "price_mean": round(float(price.mean()) if len(df) else 0, 2),
        "price_median": round(float(price.median()) if len(df) else 0, 2),
        "cn_title": round(float(df["has_cn_title"].mean()) if "has_cn_title" in df.columns and len(df) else 0, 3),
        "l1": str(_l1_of(df).mode().iloc[0]) if len(df) else name,
    }


def mix_rows(df: pd.DataFrame, base_n: dict[str, int]) -> list[dict]:
    l1 = _l1_of(df)
    vc = l1.value_counts()
    rows = []
    for name, n in vc.items():
        base = base_n.get(str(name), 0)
        share = _pct(int(n), len(df))
        base_share = _pct(base, sum(base_n.values()))
        rows.append(
            {
                "name": str(name),
                "n": int(n),
                "share": share,
                "base_share": base_share,
                "index": round(share / base_share, 2) if base_share else 0,
            }
        )
    return rows


def band_table(df: pd.DataFrame, kind: str) -> list[dict]:
    price = _price_of(df)
    sales = _sales_of(df)
    if kind == "price":
        lab = _band(price, PRICE_BANDS)
        order = [x[2] for x in PRICE_BANDS]
    else:
        lab = _band(sales, SALES_BANDS)
        order = [x[2] for x in SALES_BANDS]
    rows = []
    for name in order:
        sub = df[lab == name]
        s = _sales_of(sub)
        rows.append(
            {
                "name": name,
                "n": int(len(sub)),
                "share": _pct(len(sub), len(df)),
                "pos_rate": round(float((s > 0).mean()) if len(sub) else 0, 3),
                "sales_mean": round(float(s.mean()) if len(sub) else 0, 2),
            }
        )
    return rows


def l2_table(df: pd.DataFrame, top_n: int = 12) -> list[dict]:
    l1 = _l1_of(df)
    l2 = _l2_of(df)
    sales = _sales_of(df)
    tmp = pd.DataFrame({"l1": l1, "l2": l2, "sales": sales, "pos": sales > 0})
    g = tmp.groupby(["l1", "l2"], dropna=False)
    rows = []
    for (a, b), sub in g:
        rows.append(
            {
                "l1": str(a),
                "l2": str(b),
                "n": int(len(sub)),
                "pos_rate": round(float(sub["pos"].mean()), 3),
                "sales_mean": round(float(sub["sales"].mean()), 2),
                "sales_median": round(float(sub["sales"].median()), 2),
            }
        )
    rows.sort(key=lambda r: -r["n"])
    return rows[:top_n]


def shop_block(df: pd.DataFrame) -> dict:
    if "店铺ID" not in df.columns:
        return {"n": 0, "top10_sku": 0, "top10_sales": 0, "rows": []}
    sales = _sales_of(df)
    tmp = df.assign(_s=sales, _pos=sales > 0)
    g = tmp.groupby("店铺ID", dropna=False)
    recs = []
    for sid, sub in g:
        recs.append(
            {
                "id": str(sid),
                "name": str(sub["店铺名"].iloc[0]) if "店铺名" in sub.columns else str(sid),
                "n": int(len(sub)),
                "sales": float(sub["_s"].sum()),
                "pos_rate": float(sub["_pos"].mean()),
            }
        )
    recs.sort(key=lambda r: -r["sales"])
    tot_n = len(df)
    tot_s = float(sales.sum()) or 1.0
    top10 = recs[:10]
    return {
        "n": len(recs),
        "top10_sku": _pct(sum(r["n"] for r in top10), tot_n),
        "top10_sales": _pct(sum(r["sales"] for r in top10), tot_s),
        "rows": [
            {
                **r,
                "sales": round(r["sales"], 1),
                "pos_rate": round(r["pos_rate"], 3),
                "sku_share": _pct(r["n"], tot_n),
            }
            for r in recs[:12]
        ],
    }


def score_block(scored: pd.DataFrame) -> dict:
    if "预测分" not in scored.columns:
        return {"spearman": None, "quintiles": []}
    y = _sales_of(scored)
    s = _num(scored["预测分"])
    if y.nunique() < 2 or s.nunique() < 2:
        rho = None
    else:
        rho = round(float(pd.Series(s).corr(y, method="spearman")), 3)
    q = pd.qcut(s, 5, labels=["Q1 低", "Q2", "Q3", "Q4", "Q5 高"], duplicates="drop")
    rows = []
    for name, sub in scored.groupby(q, observed=False):
        ys = _sales_of(sub)
        rows.append(
            {
                "name": str(name),
                "n": int(len(sub)),
                "pos_rate": round(float((ys > 0).mean()), 3),
                "sales_mean": round(float(ys.mean()), 2),
                "score_mean": round(float(_num(sub["预测分"]).mean()), 3),
            }
        )
    return {"spearman": rho, "quintiles": rows}


def banned_by_l1(raw: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    if raw.empty:
        return [], []
    entries = load_words(WORDS, WORDS_JSON)
    marked, counter = apply_banned(raw, entries)
    l1 = _l1_of(marked)
    rows = []
    for name, sub in marked.groupby(l1):
        hit = int(sub["banned"].sum())
        rows.append(
            {
                "name": str(name),
                "n": int(len(sub)),
                "banned": hit,
                "keep": int(len(sub) - hit),
                "drop_pct": _pct(hit, len(sub)),
            }
        )
    top_words = [{"name": w, "n": int(c)} for w, c in counter.most_common(12)]
    return rows, top_words


def notes_from(payload: dict) -> list[str]:
    out = []
    l1 = {r["name"]: r for r in payload.get("l1", [])}
    if l1:
        richest = max(l1.values(), key=lambda r: r["pos_rate"])
        poorest = min(l1.values(), key=lambda r: r["pos_rate"])
        out.append(
            f"清洗后动销率最高是 {richest['name']} {richest['pos_rate']:.1%}，"
            f"最低是 {poorest['name']} {poorest['pos_rate']:.1%}。"
        )
    drops = payload.get("banned_l1") or []
    if drops:
        hard = max(drops, key=lambda r: r["drop_pct"])
        out.append(
            f"词表砍得最狠的是 {hard['name']}，丢掉 {hard['drop_pct']}%（多半是 2D/杯子）。"
        )
    mix = payload.get("top5_mix") or []
    hot = [r for r in mix if r.get("index", 1) >= 1.15]
    cold = [r for r in mix if r.get("index", 1) and r["index"] <= 0.85]
    if hot:
        out.append(
            "Top 5% 相对盘面偏多："
            + "、".join(f"{r['name']} ×{r['index']}" for r in hot)
            + "。当天训练和打分是同一批，偏爱不能直接当外推。"
        )
    if cold:
        out.append("Top 5% 相对盘面偏少：" + "、".join(f"{r['name']} ×{r['index']}" for r in cold) + "。")
    shops = payload.get("shops") or {}
    if shops.get("top10_sales"):
        out.append(
            f"销量集中：前 10 家店吃掉 {shops['top10_sales']}% 销量、{shops['top10_sku']}% SKU。"
        )
    sc = payload.get("score") or {}
    if sc.get("spearman") is not None:
        out.append(
            f"预测分 vs 总销量 Spearman = {sc['spearman']}。"
            "今天是冷启动泄漏日，这条只说明模型有没有记住销量，不说明明天还能排。"
        )
    pub = payload.get("published")
    if pub and pub.get("n"):
        out.append(f"人工留下 {pub['n']} 条（从 Top 5% {payload['funnel']['top5']} 里筛）。")
    med = payload.get("cleaned_all") or {}
    if med.get("sales_median") == 0:
        out.append("销量中位数是 0：大多数货没动销，排序看的是右尾，不是平均店。")
    return out


def build_payload(
    raw: pd.DataFrame,
    cleaned: pd.DataFrame,
    scored: pd.DataFrame,
    top: pd.DataFrame,
    published_ids: set[str],
    iso: str,
) -> dict:
    raw = raw.copy()
    cleaned = cleaned.copy()
    scored = scored.copy()
    top = top.copy()
    for df in (raw, cleaned, scored, top):
        if "商品ID" in df.columns:
            df["商品ID"] = df["商品ID"].astype(str)

    base_n = _l1_of(cleaned).value_counts().to_dict()
    l1_blocks = []
    for name, sub in cleaned.groupby(_l1_of(cleaned)):
        l1_blocks.append(block_stats(sub, str(name)))
    l1_blocks.sort(key=lambda r: -r["n"])

    pub_df = scored[scored["商品ID"].isin(published_ids)].copy() if published_ids else pd.DataFrame()
    banned_l1, banned_words = banned_by_l1(raw)

    pack_col = "_pack" if "_pack" in raw.columns else ("来源文件" if "来源文件" in raw.columns else None)
    packs = []
    if pack_col:
        for name, sub in raw.groupby(raw[pack_col].astype(str)):
            packs.append(block_stats(sub, str(name)))

    funnel = {
        "raw": int(len(raw)),
        "cleaned": int(len(cleaned)),
        "top5": int(len(top)),
        "published": int(len(published_ids)),
        "drop_pct": _pct(len(raw) - len(cleaned), len(raw)) if len(raw) else 0,
    }

    payload = {
        "iso": iso,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "funnel": funnel,
        "packs": packs,
        "cleaned_all": block_stats(cleaned, "清洗后"),
        "l1": l1_blocks,
        "l2": l2_table(cleaned),
        "price_bands": band_table(cleaned, "price"),
        "sales_bands": band_table(cleaned, "sales"),
        "banned_l1": banned_l1,
        "banned_words": banned_words,
        "shops": shop_block(cleaned),
        "score": score_block(scored),
        "top5_mix": mix_rows(top, base_n) if len(top) else [],
        "published_mix": mix_rows(pub_df, base_n) if len(pub_df) else [],
        "published": block_stats(pub_df, "已发布") if len(pub_df) else {"name": "已发布", "n": 0},
    }
    payload["notes"] = notes_from(payload)
    return payload


TEMPLATE = Path(__file__).with_name("analyze_page.html")

def render(payload: dict, dest: Path) -> Path:
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    blob = blob.replace("<", r"\u003c")
    html = TEMPLATE.read_text(encoding="utf-8")
    html = html.replace("__ISO__", payload["iso"]).replace("__PAYLOAD__", blob)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(html, encoding="utf-8")
    dest.with_suffix(".json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return dest


def load_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        try:
            return pd.read_csv(path, encoding="utf-8-sig")
        except Exception:
            from merge_csv import read_table

            return read_table(path)
    from merge_csv import read_table

    return read_table(path)


def run(
    raw_path: Path,
    cleaned_path: Path,
    scored_path: Path,
    top_path: Path | None,
    published_path: Path | None,
    out_path: Path,
    iso: str,
) -> Path:
    raw = load_table(raw_path) if raw_path and raw_path.is_file() else pd.DataFrame()
    cleaned = load_table(cleaned_path)
    scored = load_table(scored_path) if scored_path and scored_path.is_file() else cleaned
    top = load_table(top_path) if top_path and top_path.is_file() else pd.DataFrame()
    pub_ids = _ids_from_html(published_path) if published_path else set()
    payload = build_payload(raw if len(raw) else cleaned, cleaned, scored, top, pub_ids, iso)
    dest = render(payload, out_path)
    print(f"[analyze] {dest}")
    print(f"[analyze] {dest.with_suffix('.json')}")
    for line in payload["notes"]:
        print(f"  - {line}")
    return dest


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="三表 HTML 数分")
    ap.add_argument("--raw", default="", help="合并后的 raw csv")
    ap.add_argument("--cleaned", default="", help="清洗后 csv")
    ap.add_argument("--scored", default="", help="打分 csv")
    ap.add_argument("--top", default="", help="Top csv")
    ap.add_argument("--published", default="", help="人工筛选 HTML")
    ap.add_argument("--out", default="", help="输出 HTML")
    ap.add_argument("--iso", default="", help="日期 YYYY-MM-DD")
    args = ap.parse_args()

    cleaned = Path(args.cleaned) if args.cleaned else _latest(CLEANED, "*merged*.csv") or _latest(CLEANED, "*.csv")
    if cleaned is None:
        raise SystemExit("找不到 cleaned csv")
    stem = cleaned.stem
    iso = args.iso or (
        f"{stem[:4]}-{stem[4:6]}-{stem[6:8]}" if stem[:8].isdigit() else datetime.now().strftime("%Y-%m-%d")
    )
    raw = Path(args.raw) if args.raw else RAW / f"{stem}.csv"
    scored = Path(args.scored) if args.scored else (
        _latest(OUTPUT, f"{stem}_scored.csv") or ROOT / "screener" / "output" / f"{stem}_scored.csv"
    )
    top = Path(args.top) if args.top else _latest(OUTPUT, f"{stem}_Top.csv")
    published = Path(args.published) if args.published else None
    if published is None:
        cand = Path.home() / "Downloads" / "9-19.html"
        published = cand if cand.is_file() else _latest(Path.home() / "Downloads", "*9-19*.html")
    out = Path(args.out) if args.out else OUTPUT / f"{stem}_分析.html"
    run(raw, cleaned, scored, top, published, out, iso)


if __name__ == "__main__":
    main()
