# -*- coding: utf-8 -*-
"""909/910/911 三天日报 — 可视化 EDA（JSON + 单文件 HTML）。"""
from __future__ import annotations

import ast
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
ART = ROOT / "artifacts_v2"
DATA_FILES = [
    ("909", ROOT / "909.xlsx", "2026-09-09"),
    ("910", ROOT / "910.csv", "2026-09-10"),
    ("911", ROOT / "911.csv", "2026-09-11"),
]
OUT_JSON = ART / "three_day_eda.json"
OUT_HTML = ART / "三天数据可视化分析.html"

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


def title_text(row) -> str:
    cn = row.get("商品标题（中文）")
    if pd.notna(cn) and str(cn).strip():
        return str(cn).strip()
    return str(row.get("商品标题（英文）", "")).strip()


def sale_buckets(s: pd.Series) -> dict:
    s = pd.to_numeric(s, errors="coerce").fillna(0)
    n = len(s)
    return {
        "n": int(n),
        "mean": float(s.mean()),
        "median": float(s.median()),
        "p90": float(s.quantile(0.9)),
        "p99": float(s.quantile(0.99)),
        "max": float(s.max()),
        "gt0": float((s > 0).mean()),
        "ge5": float((s >= 5).mean()),
        "ge20": float((s >= 20).mean()),
        "ge50": float((s >= 50).mean()),
        "ge100": float((s >= 100).mean()),
    }


def hist_log1p_sales(s: pd.Series, bins: int = 40) -> dict:
    s = pd.to_numeric(s, errors="coerce").fillna(0).clip(lower=0)
    v = np.log1p(s.values)
    counts, edges = np.histogram(v, bins=bins)
    return {
        "counts": counts.astype(int).tolist(),
        "edges": [round(float(x), 3) for x in edges],
        "x_label": "log1p(总销量)",
    }


def price_hist(prices: pd.Series, bins: int = 30) -> dict:
    p = pd.to_numeric(prices, errors="coerce")
    p = p[p.notna() & (p > 0)]
    counts, edges = np.histogram(p.values, bins=bins)
    return {
        "counts": counts.astype(int).tolist(),
        "edges": [round(float(x), 2) for x in edges],
    }


def top_categories(df: pd.DataFrame, col: str, n: int = 12) -> list[dict]:
    if col not in df.columns:
        return []
    vc = df[col].fillna("").astype(str).str.strip()
    vc = vc.replace("", "未知").value_counts().head(n)
    return [{"name": k, "count": int(v)} for k, v in vc.items()]


def parse_listing_time(series: pd.Series) -> dict:
    """上架时间字段：解析成功比例与按小时分布。"""
    col = None
    for c in ("上架时间", "收录时间"):
        if c in series.index if isinstance(series, pd.Series) else False:
            col = c
            break
    return {}


def indexed_stats(df: pd.DataFrame) -> dict:
    """收录时间：有值表示已在库/被收录，选品常筛「无收录」新品。"""
    col = "收录时间" if "收录时间" in df.columns else None
    if not col:
        return {"has_col": False}
    raw = df[col]
    has = raw.notna() & (raw.astype(str).str.strip() != "") & (raw.astype(str) != "nan")
    return {
        "has_col": True,
        "indexed_rate": float(has.mean()),
        "not_indexed_rate": float((~has).mean()),
        "n_not_indexed": int((~has).sum()),
    }


def shop_sales_corr(df: pd.DataFrame) -> dict | None:
    if "店铺总销量" not in df.columns:
        return None
    shop = pd.to_numeric(df["店铺总销量"], errors="coerce")
    sale = pd.to_numeric(df["总销量"], errors="coerce")
    m = shop.notna() & sale.notna()
    if m.sum() < 100:
        return None
    from scipy.stats import spearmanr

    rho, _ = spearmanr(shop[m], sale[m])
    return {"spearman_shop_vs_sku_sale": round(float(rho), 4), "n": int(m.sum())}


def listing_stats(df: pd.DataFrame) -> dict:
    out = {"has_col": False, "parsed_rate": 0.0, "hour_counts": [], "range": None}
    col = "上架时间" if "上架时间" in df.columns else None
    if not col:
        return out
    out["has_col"] = True
    raw = df[col]
    listed = raw.notna() & (raw.astype(str).str.strip() != "") & (raw.astype(str) != "nan")
    out["listed_rate"] = float(listed.mean())
    ts = pd.to_datetime(raw[listed], errors="coerce")
    ok = ts.notna()
    out["parsed_rate"] = float(ok.sum() / max(len(df), 1))
    if ok.any():
        out["range"] = {
            "min": ts[ok].min().isoformat(sep=" ", timespec="minutes"),
            "max": ts[ok].max().isoformat(sep=" ", timespec="minutes"),
        }
        hours = ts[ok].dt.hour.value_counts().sort_index()
        out["hour_counts"] = [{"hour": int(h), "count": int(c)} for h, c in hours.items()]
    return out


def load_raw(path: Path, source_name: str) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="sheet", header=[0, 1])
    df = flatten_columns(df)
    df["source_file"] = source_name
    df["商品ID"] = df["商品ID"].astype(str)
    df["总销量"] = pd.to_numeric(df["总销量"], errors="coerce").fillna(0)
    df["美元价格($)"] = pd.to_numeric(df["美元价格($)"], errors="coerce")
    df["标题"] = df.apply(title_text, axis=1)
    cat = df["前台分类（中文）"].fillna("").astype(str)
    parts = cat.str.split("/", n=2, expand=True)
    df["cat_l1"] = parts[0].replace("", "未知")
    df["cat_l2"] = parts[1].fillna("未知").replace("", "未知") if 1 in parts.columns else "未知"
    df["main_url"] = df["商品主图"].map(lambda x: parse_urls(x)[:1]).map(lambda xs: xs[0] if xs else "")
    if "店铺ID" in df.columns:
        df["shop_id"] = df["店铺ID"].apply(
            lambda x: f"shop_{int(float(x))}" if pd.notna(x) else "_missing_shop_id"
        )
    else:
        df["shop_id"] = "unknown"
    return df


def overlap_matrix(frames: dict[str, pd.DataFrame]) -> dict:
    ids = {k: set(f["商品ID"]) for k, f in frames.items()}
    keys = list(ids.keys())
    matrix = []
    for a in keys:
        row = []
        for b in keys:
            inter = len(ids[a] & ids[b])
            row.append(inter)
        matrix.append(row)
    pair_detail = []
    for i, a in enumerate(keys):
        for j, b in enumerate(keys):
            if i >= j:
                continue
            inter = ids[a] & ids[b]
            pair_detail.append({"a": a, "b": b, "overlap_ids": len(inter)})
    return {"labels": keys, "matrix": matrix, "pairs": pair_detail}


def shop_concentration(df: pd.DataFrame) -> dict:
    vc = df.groupby("shop_id").size()
    return {
        "n_shops": int(vc.shape[0]),
        "mean_skus_per_shop": float(vc.mean()),
        "median_skus": float(vc.median()),
        "p75_skus": float(vc.quantile(0.75)),
        "max_skus": int(vc.max()),
        "share_top1_shop": float(vc.max() / len(df)),
        "shops_with_ge2": float((vc >= 2).sum() / max(len(vc), 1)),
        "top_shops": [
            {"shop_id": k, "n": int(v)} for k, v in vc.sort_values(ascending=False).head(8).items()
        ],
    }


def build_payload() -> dict:
    frames: dict[str, pd.DataFrame] = {}
    per_day = []
    for label, path, date_label in DATA_FILES:
        df = load_raw(path, path.name)
        frames[label] = df
        price_ok = df["美元价格($)"].notna() & (df["美元价格($)"] > 0)
        main_ok = df["main_url"] != ""
        per_day.append(
            {
                "label": label,
                "file": path.name,
                "date": date_label,
                "rows_raw": int(len(df)),
                "unique_ids": int(df["商品ID"].nunique()),
                "price_ok": int(price_ok.sum()),
                "main_url_ok": int(main_ok.sum()),
                "sales": sale_buckets(df["总销量"]),
                "price": {
                    "mean": float(df.loc[price_ok, "美元价格($)"].mean()),
                    "median": float(df.loc[price_ok, "美元价格($)"].median()),
                    "p10": float(df.loc[price_ok, "美元价格($)"].quantile(0.1)),
                    "p90": float(df.loc[price_ok, "美元价格($)"].quantile(0.9)),
                },
                "sales_hist": hist_log1p_sales(df["总销量"]),
                "price_hist": price_hist(df.loc[price_ok, "美元价格($)"]),
                "cat_l2_top": top_categories(df, "cat_l2"),
                "listing": listing_stats(df),
                "indexed": indexed_stats(df),
                "shop_sale_corr": shop_sales_corr(df),
                "shop": shop_concentration(df),
                "missing_shop_id": int((df["shop_id"] == "_missing_shop_id").sum()),
                "title_len_mean": float(df["标题"].str.len().mean()),
                "title_cjk_ratio_mean": float(
                    df["标题"].map(lambda s: len(CJK_RE.findall(str(s))) / max(len(str(s)), 1)).mean()
                ),
            }
        )

    all_concat = pd.concat(frames.values(), ignore_index=True)
    dup_id_global = int(all_concat.duplicated("商品ID", keep=False).sum())
    unique_ids_global = int(all_concat["商品ID"].nunique())

    ds_path = ART / "dataset.csv"
    dataset_summary = {}
    if ds_path.is_file():
        ds = pd.read_csv(ds_path, encoding="utf-8-sig", dtype={"商品ID": str})
        by_src = []
        for src, g in ds.groupby("source"):
            by_src.append({"source": src, "n": int(len(g)), "sales": sale_buckets(g["总销量"])})
        dataset_summary = {
            "n_rows": int(len(ds)),
            "by_source": by_src,
            "split_counts": ds["split"].value_counts().to_dict() if "split" in ds.columns else {},
        }

    # 跨天重复：同 ID 在不同文件出现
    id_to_sources: dict[str, set[str]] = {}
    for label, df in frames.items():
        for pid in df["商品ID"].unique():
            id_to_sources.setdefault(pid, set()).add(label)
    multi_day = sum(1 for s in id_to_sources.values() if len(s) > 1)

    # 类目结构三天对比（top12 并集）
    cat_union = Counter()
    for label, df in frames.items():
        for c in df["cat_l2"].value_counts().head(15).index:
            cat_union[c] += 1
    top_cats = [c for c, _ in cat_union.most_common(12)]

    cat_sales_by_day = []
    for label, df in frames.items():
        sub = df[df["cat_l2"].isin(top_cats)]
        rate = sub.groupby("cat_l2")["总销量"].apply(lambda s: (s > 0).mean())
        cat_sales_by_day.append(
            {
                "day": label,
                "rates": [{"cat": c, "gt0_rate": float(rate.get(c, 0))} for c in top_cats],
            }
        )

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "per_day": per_day,
        "global": {
            "rows_concat": int(len(all_concat)),
            "unique_product_ids": unique_ids_global,
            "rows_with_duplicate_id_across_files": dup_id_global,
            "ids_appearing_in_multiple_days": multi_day,
            "overlap": overlap_matrix(frames),
        },
        "dataset_cleaned": dataset_summary,
        "cat_compare": {"categories": top_cats, "gt0_by_day": cat_sales_by_day},
    }


def esc(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def build_html(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    days = data["per_day"]
    day_labels = [d["label"] for d in days]

    def pct(x: float) -> str:
        return f"{100 * x:.1f}%"

    kpi_cards = []
    for d in days:
        s = d["sales"]
        kpi_cards.append(
            f"""<div class="kpi-card">
          <div class="kpi-day">{esc(d['label'])} <span class="muted">{esc(d['date'])}</span></div>
          <div class="kpi-row"><span>原始行数</span><strong>{d['rows_raw']:,}</strong></div>
          <div class="kpi-row"><span>动销 &gt;0</span><strong class="accent">{pct(s['gt0'])}</strong></div>
          <div class="kpi-row"><span>销量 ≥5</span><strong>{pct(s['ge5'])}</strong></div>
          <div class="kpi-row"><span>销量 ≥20</span><strong>{pct(s['ge20'])}</strong></div>
          <div class="kpi-row"><span>中位销量</span><strong>{s['median']:.0f}</strong></div>
          <div class="kpi-row"><span>均价</span><strong>${d['price']['mean']:.2f}</strong></div>
        </div>"""
        )

    overlap = data["global"]["overlap"]
    pair_rows = "".join(
        f"<tr><td>{esc(p['a'])} × {esc(p['b'])}</td><td class='n'>{p['overlap_ids']}</td></tr>"
        for p in overlap["pairs"]
    )

    ds = data.get("dataset_cleaned") or {}
    ds_block = ""
    if ds.get("n_rows"):
        ds_rows = "".join(
            f"<tr><td>{esc(x['source'])}</td><td class='n'>{x['n']:,}</td>"
            f"<td class='n'>{pct(x['sales']['gt0'])}</td><td class='n'>{pct(x['sales']['ge5'])}</td></tr>"
            for x in ds["by_source"]
        )
        ds_block = f"""
    <section>
      <h2>清洗后样本（dataset.csv）</h2>
      <p class="lead">去重商品 ID、去掉无价/无主图后用于建模的 {ds['n_rows']:,} 行。</p>
      <table class="data-table">
        <thead><tr><th>来源</th><th>行数</th><th>动销&gt;0</th><th>≥5</th></tr></thead>
        <tbody>{ds_rows}</tbody>
      </table>
    </section>"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>909–911 三天日报 · 数据可视化分析</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <style>
    :root {{
      --bg: #f4f5f7;
      --card: #fff;
      --ink: #1a1d21;
      --muted: #6b7280;
      --accent: #e85d04;
      --border: #e5e7eb;
      --blue: #2563eb;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", system-ui, sans-serif;
      background: var(--bg);
      color: var(--ink);
      line-height: 1.5;
    }}
    .wrap {{ max-width: 1180px; margin: 0 auto; padding: 24px 20px 48px; }}
    h1 {{ font-size: 1.65rem; margin: 0 0 8px; }}
    h2 {{ font-size: 1.15rem; margin: 32px 0 12px; border-left: 4px solid var(--accent); padding-left: 10px; }}
    .lead {{ color: var(--muted); margin: 0 0 20px; max-width: 72ch; }}
    .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; }}
    .kpi-card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 14px 16px;
    }}
    .kpi-day {{ font-weight: 700; margin-bottom: 10px; }}
    .kpi-row {{ display: flex; justify-content: space-between; font-size: 0.9rem; padding: 3px 0; }}
    .kpi-row .accent {{ color: var(--accent); }}
    .muted {{ color: var(--muted); font-weight: 400; font-size: 0.85rem; }}
    .chart-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
    @media (max-width: 900px) {{ .chart-grid {{ grid-template-columns: 1fr; }} }}
    .chart-card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px 14px 8px;
    }}
    .chart-card h3 {{ margin: 0 0 8px; font-size: 0.95rem; }}
    .chart-card canvas {{ max-height: 280px; }}
    .data-table {{ width: 100%; border-collapse: collapse; background: var(--card); border-radius: 12px; overflow: hidden; font-size: 0.9rem; }}
    .data-table th, .data-table td {{ padding: 10px 12px; border-bottom: 1px solid var(--border); text-align: left; }}
    .data-table th {{ background: #f9fafb; font-weight: 600; }}
    .data-table td.n {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .insight {{
      background: #fff7ed;
      border: 1px solid #fed7aa;
      border-radius: 12px;
      padding: 14px 16px;
      margin-top: 16px;
      font-size: 0.92rem;
    }}
    .insight strong {{ color: #c2410c; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>909 – 911 三天 Temu 日报 · 可视化数据分析</h1>
    <p class="lead">基于云启导出的三份日报（各约 1 万行）。下图对比动销结构、价格、类目与店铺集中度；清洗后样本与建模流水线一致。</p>

    <div class="kpi-grid">{''.join(kpi_cards)}</div>

    <div class="insight">
      <strong>跨天重叠：</strong> 合并后唯一商品 ID {data['global']['unique_product_ids']:,} 个；
      至少出现在两天的 ID 共 <strong>{data['global']['ids_appearing_in_multiple_days']}</strong> 个
      （建模前需去重，否则同款进 train/test 会泄露）。
      {''.join(f" {p['a']}∩{p['b']}={p['overlap_ids']}。" for p in overlap['pairs'])}
    </div>

    <h2>动销与销量分布</h2>
    <div class="chart-grid">
      <div class="chart-card"><h3>动销率对比（总销量 &gt; 0）</h3><canvas id="chartGt0"></canvas></div>
      <div class="chart-card"><h3>分档动销占比（≥5 / ≥20 / ≥50）</h3><canvas id="chartTiers"></canvas></div>
      <div class="chart-card"><h3>log1p(总销量) 分布</h3><canvas id="chartSalesHist"></canvas></div>
      <div class="chart-card"><h3>美元价格分布</h3><canvas id="chartPriceHist"></canvas></div>
    </div>

    <h2>类目结构</h2>
    <div class="chart-grid">
      <div class="chart-card"><h3>二级类目 Top12 商品数（分天）</h3><canvas id="chartCatCount"></canvas></div>
      <div class="chart-card"><h3>Top 类目动销率（&gt;0）分天对比</h3><canvas id="chartCatGt0"></canvas></div>
    </div>

    <h2>收录与店铺</h2>
    <div class="chart-grid">
      <div class="chart-card"><h3>已有收录时间占比（越低越像「纯新品」池）</h3><canvas id="chartIndexed"></canvas></div>
      <div class="chart-card"><h3>店铺总销量 vs 商品总销量（Spearman）</h3><canvas id="chartShopCorr"></canvas></div>
    </div>

    <h2>店铺集中度</h2>
    <div class="chart-grid">
      <div class="chart-card"><h3>店铺数 &amp; 平均每店 SKU</h3><canvas id="chartShop"></canvas></div>
      <div class="chart-card"><h3>上架时间解析（有「上架时间」列的天）</h3><canvas id="chartListingHour"></canvas></div>
    </div>

    <table class="data-table" style="margin-top:16px">
      <thead><tr><th>天</th><th>店铺数</th><th>均 SKU/店</th><th>最大店 SKU</th><th>≥2 SKU 店铺占比</th></tr></thead>
      <tbody id="shopTableBody"></tbody>
    </table>

    {ds_block}

    <p class="muted" style="margin-top:32px;font-size:0.8rem">生成时间 {esc(data['generated_at'])} · 数据文件 909.xlsx / 910.csv / 911.csv</p>
  </div>
  <script>
    const DATA = {payload};
    const DAYS = DATA.per_day;
    const labels = DAYS.map(d => d.label);
    const colors = ['#e85d04', '#2563eb', '#059669'];

    Chart.defaults.font.family = "'Segoe UI', system-ui, sans-serif";
    Chart.defaults.color = '#4b5563';

    new Chart(document.getElementById('chartGt0'), {{
      type: 'bar',
      data: {{
        labels,
        datasets: [{{
          label: '动销率 (>0)',
          data: DAYS.map(d => d.sales.gt0 * 100),
          backgroundColor: colors.map(c => c + 'cc'),
        }}]
      }},
      options: {{
        scales: {{ y: {{ beginAtZero: true, title: {{ display: true, text: '占比 (%)' }} }} }},
        plugins: {{ legend: {{ display: false }} }}
      }}
    }});

    new Chart(document.getElementById('chartTiers'), {{
      type: 'bar',
      data: {{
        labels,
        datasets: [
          {{ label: '≥5', data: DAYS.map(d => d.sales.ge5 * 100), backgroundColor: '#fdba74' }},
          {{ label: '≥20', data: DAYS.map(d => d.sales.ge20 * 100), backgroundColor: '#fb923c' }},
          {{ label: '≥50', data: DAYS.map(d => d.sales.ge50 * 100), backgroundColor: '#ea580c' }},
        ]
      }},
      options: {{
        scales: {{ y: {{ beginAtZero: true, title: {{ display: true, text: '占比 (%)' }} }} }}
      }}
    }});

    function histDataset(day, field) {{
      const h = day[field];
      const labels = [];
      for (let i = 0; i < h.counts.length; i++) {{
        const lo = h.edges[i], hi = h.edges[i+1];
        labels.push(lo.toFixed(1) + '–' + hi.toFixed(1));
      }}
      return {{ labels, data: h.counts }};
    }}

    new Chart(document.getElementById('chartSalesHist'), {{
      type: 'line',
      data: {{
        labels: histDataset(DAYS[0], 'sales_hist').labels,
        datasets: DAYS.map((d, i) => {{
          const h = histDataset(d, 'sales_hist');
          return {{
            label: d.label,
            data: h.data,
            borderColor: colors[i],
            backgroundColor: colors[i] + '33',
            fill: true,
            tension: 0.25,
            pointRadius: 0,
          }};
        }})
      }},
      options: {{
        scales: {{
          x: {{ title: {{ display: true, text: 'log1p(总销量)' }}, ticks: {{ maxTicksLimit: 8 }} }},
          y: {{ beginAtZero: true, title: {{ display: true, text: '商品数' }} }}
        }}
      }}
    }});

    new Chart(document.getElementById('chartPriceHist'), {{
      type: 'line',
      data: {{
        labels: histDataset(DAYS[0], 'price_hist').labels.map((_, i) => {{
          const e = DAYS[0].price_hist.edges;
          return '$' + e[i].toFixed(0);
        }}),
        datasets: DAYS.map((d, i) => ({{
          label: d.label,
          data: d.price_hist.counts,
          borderColor: colors[i],
          tension: 0.25,
          pointRadius: 0,
        }}))
      }},
      options: {{
        scales: {{
          x: {{ title: {{ display: true, text: '美元价格 ($)' }}, ticks: {{ maxTicksLimit: 8 }} }},
          y: {{ beginAtZero: true, title: {{ display: true, text: '商品数' }} }}
        }}
      }}
    }});

    const cats = DATA.cat_compare.categories;
    new Chart(document.getElementById('chartCatCount'), {{
      type: 'bar',
      data: {{
        labels: cats,
        datasets: DAYS.map((d, i) => ({{
          label: d.label,
          data: cats.map(c => {{
            const row = d.cat_l2_top.find(x => x.name === c);
            return row ? row.count : 0;
          }}),
          backgroundColor: colors[i] + 'aa',
        }}))
      }},
      options: {{
        indexAxis: 'y',
        scales: {{ x: {{ beginAtZero: true, title: {{ display: true, text: 'SKU 数' }} }} }}
      }}
    }});

    new Chart(document.getElementById('chartCatGt0'), {{
      type: 'bar',
      data: {{
        labels: cats,
        datasets: DATA.cat_compare.gt0_by_day.map((block, i) => ({{
          label: block.day,
          data: block.rates.map(r => r.gt0_rate * 100),
          backgroundColor: colors[i] + 'aa',
        }}))
      }},
      options: {{
        scales: {{ y: {{ beginAtZero: true, max: 100, title: {{ display: true, text: '动销率 (%)' }} }} }}
      }}
    }});

    const idxDays = DAYS.filter(d => d.indexed && d.indexed.has_col);
    if (idxDays.length) {{
      new Chart(document.getElementById('chartIndexed'), {{
        type: 'bar',
        data: {{
          labels: idxDays.map(d => d.label),
          datasets: [
            {{ label: '无收录（可当新品）', data: idxDays.map(d => d.indexed.not_indexed_rate * 100), backgroundColor: '#34d399' }},
            {{ label: '已有收录', data: idxDays.map(d => d.indexed.indexed_rate * 100), backgroundColor: '#9ca3af' }},
          ]
        }},
        options: {{
          scales: {{ x: {{ stacked: true }}, y: {{ stacked: true, max: 100, title: {{ display: true, text: '占比 (%)' }} }} }}
        }}
      }});
    }}

    const corrDays = DAYS.filter(d => d.shop_sale_corr);
    if (corrDays.length) {{
      new Chart(document.getElementById('chartShopCorr'), {{
        type: 'bar',
        data: {{
          labels: corrDays.map(d => d.label),
          datasets: [{{
            label: 'Spearman ρ',
            data: corrDays.map(d => d.shop_sale_corr.spearman_shop_vs_sku_sale),
            backgroundColor: '#a78bfa',
          }}]
        }},
        options: {{
          scales: {{ y: {{ min: 0, max: 0.25, title: {{ display: true, text: '相关系数' }} }} }},
          plugins: {{ legend: {{ display: false }} }}
        }}
      }});
    }}

    new Chart(document.getElementById('chartShop'), {{
      type: 'bar',
      data: {{
        labels,
        datasets: [
          {{ label: '店铺数', data: DAYS.map(d => d.shop.n_shops), backgroundColor: '#93c5fd', yAxisID: 'y' }},
          {{ label: '均 SKU/店', data: DAYS.map(d => d.shop.mean_skus_per_shop), type: 'line', borderColor: '#1d4ed8', yAxisID: 'y1' }},
        ]
      }},
      options: {{
        scales: {{
          y: {{ position: 'left', beginAtZero: true, title: {{ display: true, text: '店铺数' }} }},
          y1: {{ position: 'right', beginAtZero: true, title: {{ display: true, text: '均 SKU/店' }}, grid: {{ drawOnChartArea: false }} }}
        }}
      }}
    }});

    const hourSets = DAYS.filter(d => d.listing.hour_counts && d.listing.hour_counts.length);
    if (hourSets.length) {{
      const hours = Array.from({{length: 24}}, (_, i) => i);
      new Chart(document.getElementById('chartListingHour'), {{
        type: 'line',
        data: {{
          labels: hours.map(h => h + '时'),
          datasets: hourSets.map((d, i) => {{
            const map = Object.fromEntries(d.listing.hour_counts.map(x => [x.hour, x.count]));
            return {{
              label: d.label,
              data: hours.map(h => map[h] || 0),
              borderColor: colors[DAYS.indexOf(d)],
              tension: 0.3,
            }};
          }})
        }},
        options: {{
          scales: {{ y: {{ beginAtZero: true, title: {{ display: true, text: '上架记录数' }} }} }}
        }}
      }});
    }} else {{
      document.getElementById('chartListingHour').parentElement.innerHTML += '<p class="muted">未解析到上架时间字段。</p>';
    }}

    const tbody = document.getElementById('shopTableBody');
    DAYS.forEach(d => {{
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${{d.label}}</td><td class="n">${{d.shop.n_shops.toLocaleString()}}</td>`
        + `<td class="n">${{d.shop.mean_skus_per_shop.toFixed(2)}}</td>`
        + `<td class="n">${{d.shop.max_skus}}</td>`
        + `<td class="n">${{(100 * d.shop.shops_with_ge2).toFixed(1)}}%</td>`;
      tbody.appendChild(tr);
    }});
  </script>
</body>
</html>"""


def main() -> None:
    ART.mkdir(parents=True, exist_ok=True)
    data = build_payload()
    OUT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HTML.write_text(build_html(data), encoding="utf-8")
    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_HTML}")
    for d in data["per_day"]:
        print(
            f"  {d['label']}: rows={d['rows_raw']} gt0={d['sales']['gt0']:.3f} "
            f"median_sale={d['sales']['median']:.0f}"
        )


if __name__ == "__main__":
    main()
