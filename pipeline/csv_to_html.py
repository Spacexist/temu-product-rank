# -*- coding: utf-8 -*-
"""模型打分 CSV → 可筛选卡片 HTML。

用法：
    python csv_to_html.py --input 某天_scored.csv
    python csv_to_html.py --input 某天_scored.csv --out 桌面/选品.html --top-pct 5

只认打分表列（中英别名均可），不跑模型。输出单文件 HTML：价格 / 类目 / 关键词 / Top%。
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd

# CSV 列 → 页面字段。左边是内部名，右边按优先级试。
COL_ALIASES: dict[str, tuple[str, ...]] = {
    "id": ("商品ID", "id", "sku", "product_id"),
    "rank": ("排名", "rank"),
    "score": ("预测分", "score", "pred"),
    "price": ("美元价格", "美元价格($)", "price"),
    "title": ("标题", "title", "商品标题（中文）"),
    "cat_l1": ("一级类目", "cat_l1"),
    "cat_l2": ("二级类目", "cat_l2"),
    "img": ("主图URL", "main_url", "img_url", "商品主图"),
    "link": ("商品链接", "link", "url"),
    "banned": ("banned",),
    "banned_hits": ("banned_hits",),
    "img_missing": ("img_missing",),
    "sales": ("总销量", "销量", "sales"),
}


def pick_col(df: pd.DataFrame, names: tuple[str, ...]) -> str | None:
    lower = {str(c).strip().lower(): c for c in df.columns}
    for n in names:
        if n in df.columns:
            return n
        hit = lower.get(n.lower())
        if hit is not None:
            return hit
    return None


def abs_https(url: object) -> str:
    u = str(url or "").strip()
    if not u or u.lower() in ("nan", "none"):
        return ""
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("http://"):
        return "https://" + u[7:]
    return u


def to_bool(v: object) -> bool:
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    return s in ("1", "true", "yes", "y", "t")


def map_csv(df: pd.DataFrame) -> list[dict]:
    cols = {k: pick_col(df, aliases) for k, aliases in COL_ALIASES.items()}
    missing = [k for k in ("id", "title", "price") if not cols[k]]
    if missing:
        raise SystemExit(
            f"CSV 缺必要列 {missing}。现有列：{list(df.columns)}\n"
            "至少需要：商品ID、标题、美元价格（可用 预测分 / 排名，没有则按行号）"
        )

    rows: list[dict] = []
    for i, r in df.iterrows():
        cat_l1 = str(r[cols["cat_l1"]]).strip() if cols["cat_l1"] else ""
        cat_l2 = str(r[cols["cat_l2"]]).strip() if cols["cat_l2"] else ""
        if cat_l1.lower() == "nan":
            cat_l1 = ""
        if cat_l2.lower() == "nan":
            cat_l2 = ""
        cate = "/".join(x for x in (cat_l1, cat_l2) if x)
        score_raw = r[cols["score"]] if cols["score"] else None
        try:
            score = float(score_raw) if score_raw is not None and str(score_raw) not in ("", "nan") else None
        except (TypeError, ValueError):
            score = None
        rank_raw = r[cols["rank"]] if cols["rank"] else None
        try:
            rank = int(float(rank_raw)) if rank_raw is not None and str(rank_raw) not in ("", "nan") else int(i) + 1
        except (TypeError, ValueError):
            rank = int(i) + 1
        try:
            price = float(r[cols["price"]])
        except (TypeError, ValueError):
            continue
        if not math.isfinite(price) or price <= 0:
            continue
        pid = str(r[cols["id"]]).strip()
        title = str(r[cols["title"]]).strip()
        if title.lower() == "nan":
            title = ""
        sales = None
        if cols["sales"]:
            try:
                sales = float(r[cols["sales"]])
            except (TypeError, ValueError):
                sales = None
        rows.append(
            {
                "id": pid,
                "rank": rank,
                "score": score,
                "price": price,
                "title": title,
                "cat_l1": cat_l1,
                "cat_l2": cat_l2 or "未分类",
                "cate": cate,
                "img_url": abs_https(r[cols["img"]]) if cols["img"] else "",
                "link": abs_https(r[cols["link"]]) if cols["link"] else "",
                "banned": to_bool(r[cols["banned"]]) if cols["banned"] else False,
                "banned_hits": str(r[cols["banned_hits"]] or "") if cols["banned_hits"] else "",
                "img_missing": to_bool(r[cols["img_missing"]]) if cols["img_missing"] else False,
                "sales": sales,
            }
        )
    if cols["score"]:
        rows.sort(key=lambda x: (-(x["score"] or -1e9), x["rank"]))
        for i, row in enumerate(rows, 1):
            row["rank"] = i
    else:
        rows.sort(key=lambda x: x["rank"])
    return rows


def build_html(rows: list[dict], title: str, top_pct: float) -> str:
    cats = sorted({r["cat_l2"] for r in rows if r.get("cat_l2")})
    data = json.dumps(rows, ensure_ascii=False)
    cats_json = json.dumps(cats, ensure_ascii=False)
    safe_title = (
        title.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")
    )
    default_pct = 5 if top_pct == 5 else (int(top_pct) if top_pct in (1, 5, 10, 20, 100) else 5)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{safe_title}</title>
<style>
:root {{
  --bg:#f4f4f5; --card:#fff; --ink:#222; --muted:#777; --line:#e8e8e8;
  --price:#fb7701; --accent:#fb7701; --danger:#e02e24; --badge:rgba(0,0,0,.72);
}}
* {{ box-sizing:border-box; }}
body {{
  margin:0;
  font-family:"PingFang SC","Microsoft YaHei","Segoe UI",sans-serif;
  background:var(--bg); color:var(--ink); font-size:14px;
}}
.hdr {{
  position:sticky; top:0; z-index:10;
  background:#fff; padding:12px 16px;
  border-bottom:1px solid var(--line);
  box-shadow:0 1px 4px rgba(0,0,0,.06);
}}
.hdr h1 {{ margin:0; font-size:15px; font-weight:600; }}
.hdr p {{ margin:6px 0 0; font-size:12px; color:var(--muted); }}
.bar {{
  display:flex; flex-wrap:wrap; gap:8px; align-items:center;
  margin-top:10px; font-size:13px;
}}
.bar label {{ color:#555; display:inline-flex; align-items:center; gap:4px; }}
.bar input[type=number], .bar input[type=search], .bar select {{
  border:1px solid #ddd; border-radius:6px; padding:4px 8px; font-size:13px;
}}
.bar input[type=number] {{ width:4.6rem; }}
.bar input[type=search] {{ width:11rem; }}
.bar select {{ min-width:7rem; max-width:12rem; }}
.bar button {{
  background:var(--accent); color:#fff; border:none; border-radius:6px;
  padding:5px 12px; cursor:pointer; font-size:13px;
}}
#stats {{ margin-top:8px; font-size:12px; color:#666; }}
.grid {{
  display:grid; grid-template-columns:repeat(auto-fill,minmax(168px,1fr));
  gap:10px; padding:12px; max-width:1400px; margin:0 auto;
}}
.card {{
  background:var(--card); border-radius:10px; overflow:hidden;
  border:1px solid var(--line); text-decoration:none; color:inherit;
  display:block; cursor:pointer;
}}
.card:hover {{ box-shadow:0 4px 14px rgba(0,0,0,.1); }}
.card.banned {{ outline:2px solid var(--danger); }}
.thumb {{ position:relative; aspect-ratio:1; background:#ececec; }}
.thumb img {{ width:100%; height:100%; object-fit:cover; display:block; }}
.ph {{ display:flex; align-items:center; justify-content:center; height:100%; color:#999; font-size:13px; }}
.badge {{
  position:absolute; top:6px; left:6px; background:var(--badge); color:#fff;
  font-size:10px; padding:3px 6px; border-radius:4px; max-width:calc(100% - 12px);
}}
.body {{ padding:8px; }}
.price {{ color:var(--price); font-weight:700; font-size:1.05rem; }}
.price small {{ font-size:.7rem; font-weight:500; }}
.title {{
  font-size:12px; line-height:1.35; margin-top:4px;
  display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical;
  overflow:hidden; min-height:2.1em;
}}
.cate {{ font-size:11px; color:#888; margin-top:4px; }}
.pager {{
  display:flex; justify-content:center; align-items:center; gap:.75rem;
  padding:0 12px 24px; font-size:.85rem;
}}
.pager button {{
  border:1px solid var(--line); background:#fff; border-radius:8px;
  padding:.4rem .9rem; cursor:pointer;
}}
.pager button:disabled {{ opacity:.4; cursor:default; }}
</style>
</head>
<body>
<header class="hdr">
  <h1>{safe_title}</h1>
  <p>CSV 映射卡片页 · 主图 https 直链（需联网）· 默认 Top {default_pct}%</p>
  <div class="bar">
    <label>最低价 $<input type="number" id="pmin" step="0.01" placeholder="不限"/></label>
    <label>最高价 $<input type="number" id="pmax" step="0.01" placeholder="不限"/></label>
    <button type="button" id="applyPrice">筛选价格</button>
    <label>类目
      <select id="cat"><option value="">全部</option></select>
    </label>
    <label>搜索 <input type="search" id="q" placeholder="标题 / ID / 类目"/></label>
    <label>Top
      <select id="topPct">
        <option value="1">1%</option>
        <option value="5">5%</option>
        <option value="10">10%</option>
        <option value="20">20%</option>
        <option value="100">全部</option>
      </select>
    </label>
    <label><input type="checkbox" id="showBanned"/> 违禁(<span id="banN">0</span>)</label>
  </div>
  <div id="stats"></div>
</header>
<div class="grid" id="grid"></div>
<div class="pager">
  <button type="button" id="prev">上一页</button>
  <span id="pageInfo"></span>
  <button type="button" id="next">下一页</button>
</div>
<script>
const ALL = {data};
const CATS = {cats_json};
const PAGE = 48;
const DEFAULT_PCT = {default_pct};
let page = 0;

(function fillCats() {{
  const sel = document.getElementById('cat');
  CATS.forEach(c => {{
    const o = document.createElement('option');
    o.value = c; o.textContent = c;
    sel.appendChild(o);
  }});
  document.getElementById('topPct').value = String(DEFAULT_PCT);
}})();

function escapeHtml(s) {{
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;');
}}

function rankCut(pct) {{
  const sorted = [...ALL].sort((a,b) => (b.score||0) - (a.score||0));
  const n = pct >= 100 ? sorted.length : Math.max(1, Math.ceil(sorted.length * pct / 100));
  const top = new Set(sorted.slice(0, n).map(r => r.id));
  return ALL.filter(r => top.has(r.id));
}}

function filterRows() {{
  const pmin = parseFloat(document.getElementById('pmin').value);
  const pmax = parseFloat(document.getElementById('pmax').value);
  const pct = parseInt(document.getElementById('topPct').value, 10);
  const cat = document.getElementById('cat').value;
  const q = document.getElementById('q').value.trim().toLowerCase();
  const showBan = document.getElementById('showBanned').checked;
  return rankCut(pct).filter(r => {{
    if (r.banned && !showBan) return false;
    if (!isNaN(pmin) && r.price < pmin) return false;
    if (!isNaN(pmax) && r.price > pmax) return false;
    if (cat && r.cat_l2 !== cat) return false;
    if (q) {{
      const hay = ((r.title||'') + ' ' + (r.id||'') + ' ' + (r.cate||'') + ' ' + (r.cat_l2||'')).toLowerCase();
      if (!hay.includes(q)) return false;
    }}
    return true;
  }});
}}

function renderPage() {{
  const rows = filterRows();
  const bannedHidden = ALL.filter(r => r.banned).length;
  document.getElementById('banN').textContent = bannedHidden;
  const prices = rows.map(r => r.price).filter(p => p > 0);
  const lo = prices.length ? Math.min(...prices).toFixed(2) : '—';
  const hi = prices.length ? Math.max(...prices).toFixed(2) : '—';
  document.getElementById('stats').textContent =
    '可见 ' + rows.length + ' / ' + ALL.length + ' · 当前价格区间 $' + lo + ' – $' + hi;

  const totalPages = Math.max(1, Math.ceil(rows.length / PAGE));
  page = Math.min(page, totalPages - 1);
  const slice = rows.slice(page * PAGE, page * PAGE + PAGE);
  const grid = document.getElementById('grid');
  grid.innerHTML = slice.map(r => {{
    const cls = ['card', r.banned ? 'banned' : ''].filter(Boolean).join(' ');
    const score = r.score != null ? Number(r.score).toFixed(2) : '';
    const badge = '#' + r.rank + (score ? ' · ' + score : '');
    const imgPart = r.img_url
      ? '<img loading="lazy" referrerpolicy="no-referrer" src="' + escapeHtml(r.img_url) + '" alt="" onerror="this.replaceWith(Object.assign(document.createElement(\\'div\\'),{{className:\\'ph\\',textContent:\\'无图\\'}}))"/>'
      : '<div class="ph">无图</div>';
    const ban = r.banned && r.banned_hits
      ? '<div class="cate" style="color:#e02e24">' + escapeHtml(r.banned_hits) + '</div>' : '';
    return '<article class="' + cls + '">' +
      '<div class="thumb"><span class="badge">' + escapeHtml(badge) + '</span>' + imgPart + '</div>' +
      '<div class="body"><div class="price"><small>$</small>' +
      (r.price != null ? Number(r.price).toFixed(2) : '') + '</div>' +
      '<div class="title">' + escapeHtml(r.title || '') + '</div>' +
      '<div class="cate">' + escapeHtml(r.cate || r.cat_l2 || '') + '</div>' + ban +
      '</div></article>';
  }}).join('');
  grid.querySelectorAll('.card').forEach((el, i) => {{
    el.addEventListener('click', () => {{
      const link = slice[i].link;
      if (link) window.open(link, '_blank', 'noopener');
    }});
  }});
  document.getElementById('pageInfo').textContent = (page + 1) + ' / ' + totalPages;
  document.getElementById('prev').disabled = page <= 0;
  document.getElementById('next').disabled = page >= totalPages - 1;
}}

function resetAndRender() {{ page = 0; renderPage(); }}
['applyPrice','topPct','showBanned','cat'].forEach(id => {{
  const el = document.getElementById(id);
  el.addEventListener('change', resetAndRender);
  el.addEventListener('click', resetAndRender);
}});
let qTimer = null;
document.getElementById('q').addEventListener('input', () => {{
  clearTimeout(qTimer);
  qTimer = setTimeout(resetAndRender, 180);
}});
document.getElementById('pmin').addEventListener('change', resetAndRender);
document.getElementById('pmax').addEventListener('change', resetAndRender);
document.getElementById('prev').onclick = () => {{ page = Math.max(0, page - 1); renderPage(); }};
document.getElementById('next').onclick = () => {{ page++; renderPage(); }};
renderPage();
</script>
</body>
</html>
"""


def main() -> None:
    ap = argparse.ArgumentParser(description="模型打分 CSV → 选品卡片 HTML")
    ap.add_argument("--input", required=True, help="模型输出的 scored.csv")
    ap.add_argument("--out", default="", help="输出 HTML 路径（默认与 CSV 同名）")
    ap.add_argument("--title", default="", help="页面标题")
    ap.add_argument("--top-pct", type=float, default=5.0, help="写入 HTML 的前百分之几，默认 5")
    ap.add_argument(
        "--embed-all",
        action="store_true",
        help="把 CSV 全量写入页面，由浏览器里的 Top%% 下拉再切",
    )
    args = ap.parse_args()

    inp = Path(args.input).resolve()
    if not inp.is_file():
        raise SystemExit(f"找不到 CSV：{inp}")
    df = pd.read_csv(inp, encoding="utf-8-sig", dtype=str)
    rows = map_csv(df)
    if not rows:
        raise SystemExit("映射后 0 行（检查价格列是否有效）")
    n_all = len(rows)
    page_pct = args.top_pct if args.embed_all else 100.0
    if not args.embed_all and args.top_pct < 100:
        k = max(1, int(n_all * args.top_pct / 100))
        rows = rows[:k]
    title = args.title or f"选品 Top{args.top_pct:g}% · {inp.name}"
    out = Path(args.out).resolve() if args.out else inp.with_suffix(".html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_html(rows, title, page_pct), encoding="utf-8")
    print(f"[csv_to_html] CSV {n_all} 行 · 写入页 {len(rows)} 行 → {out}")


if __name__ == "__main__":
    main()
