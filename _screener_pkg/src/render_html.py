# -*- coding: utf-8 -*-
from __future__ import annotations

import html
import json
from pathlib import Path


def abs_https(url: str) -> str:
    u = str(url or "").strip()
    if not u or u.lower() == "nan":
        return ""
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("http://"):
        return "https://" + u[7:]
    return u


def _esc(s: str) -> str:
    return html.escape(str(s), quote=True)


def render(rows: list[dict], title: str, out: Path) -> None:
    data_json = json.dumps(rows, ensure_ascii=False)
    safe_title = (
        title.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")
    )
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{safe_title}</title>
<style>
:root {{
  --bg: #f4f4f5;
  --card: #fff;
  --ink: #222;
  --muted: #777;
  --line: #e8e8e8;
  --price: #fb7701;
  --accent: #fb7701;
  --danger: #e02e24;
  --badge: rgba(0,0,0,.72);
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  background: var(--bg);
  color: var(--ink);
  font-size: 14px;
}}
.top {{
  position: sticky;
  top: 0;
  z-index: 20;
  background: #fff;
  border-bottom: 1px solid var(--line);
  box-shadow: 0 1px 4px rgba(0,0,0,.06);
  padding: .55rem 1rem .65rem;
}}
.top h1 {{
  margin: 0 0 .45rem;
  font-size: .95rem;
  font-weight: 600;
  color: #333;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}}
.bar {{
  display: flex;
  flex-wrap: wrap;
  gap: .45rem .75rem;
  align-items: center;
  font-size: .8rem;
}}
.bar label {{ color: var(--muted); display: inline-flex; align-items: center; gap: .25rem; }}
.bar input, .bar select {{
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: .25rem .4rem;
  font-size: .8rem;
}}
.bar button {{
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: 6px;
  padding: .3rem .65rem;
  font-size: .8rem;
  cursor: pointer;
}}
.stats {{ font-size: .75rem; color: var(--muted); margin-top: .35rem; }}
main {{ padding: .75rem 1rem 2rem; max-width: 1400px; margin: 0 auto; }}
.grid {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(168px, 1fr));
  gap: 10px;
}}
.card {{
  background: var(--card);
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid var(--line);
  cursor: pointer;
  transition: box-shadow .15s, transform .15s;
  display: flex;
  flex-direction: column;
}}
.card:hover {{ box-shadow: 0 4px 14px rgba(0,0,0,.1); transform: translateY(-1px); }}
.card.banned {{ outline: 2px solid var(--danger); }}
.thumb {{
  position: relative;
  aspect-ratio: 1;
  background: #ececec;
  overflow: hidden;
}}
.thumb img {{
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}}
.thumb .ph {{
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #999;
  font-size: .8rem;
}}
.badge {{
  position: absolute;
  top: 6px;
  left: 6px;
  background: var(--badge);
  color: #fff;
  font-size: 10px;
  line-height: 1.2;
  padding: 3px 6px;
  border-radius: 4px;
  max-width: calc(100% - 12px);
}}
.body {{ padding: 8px 8px 10px; flex: 1; display: flex; flex-direction: column; gap: 4px; }}
.price {{
  color: var(--price);
  font-weight: 700;
  font-size: 1.05rem;
}}
.price small {{ font-size: .7rem; font-weight: 500; }}
.title {{
  font-size: .78rem;
  line-height: 1.35;
  color: #333;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 2.1em;
}}
.cate {{ font-size: .68rem; color: var(--muted); }}
.pager {{
  display: flex;
  justify-content: center;
  align-items: center;
  gap: .75rem;
  margin-top: 1.25rem;
  font-size: .85rem;
}}
.pager button {{
  border: 1px solid var(--line);
  background: #fff;
  border-radius: 8px;
  padding: .4rem .9rem;
  cursor: pointer;
}}
.pager button:disabled {{ opacity: .4; cursor: default; }}
</style>
</head>
<body>
<div class="top">
  <h1>{safe_title}</h1>
  <div class="bar">
    <label>$<input type="number" id="pmin" step="0.01" placeholder="低" style="width:4.2rem"/></label>
    <label>– $<input type="number" id="pmax" step="0.01" placeholder="高" style="width:4.2rem"/></label>
    <button type="button" id="applyPrice">价格</button>
    <label>Top <select id="topPct">
      <option value="1">1%</option>
      <option value="5" selected>5%</option>
      <option value="10">10%</option>
      <option value="20">20%</option>
      <option value="100">全部</option>
    </select></label>
    <label><input type="checkbox" id="showBanned"/> 违禁(<span id="banN">0</span>)</label>
  </div>
  <div class="stats" id="stats"></div>
</div>
<main>
  <div class="grid" id="grid"></div>
  <div class="pager">
    <button type="button" id="prev">上一页</button>
    <span id="pageInfo"></span>
    <button type="button" id="next">下一页</button>
  </div>
</main>
<script>
const ALL = {data_json};
const PAGE = 48;
let page = 0;

function rankCut(pct) {{
  const sorted = [...ALL].sort((a, b) => (b.score || 0) - (a.score || 0));
  const n = pct >= 100 ? sorted.length : Math.max(1, Math.ceil(sorted.length * pct / 100));
  const top = new Set(sorted.slice(0, n).map(r => r.id));
  return ALL.filter(r => top.has(r.id));
}}

function filterRows() {{
  const pmin = parseFloat(document.getElementById('pmin').value);
  const pmax = parseFloat(document.getElementById('pmax').value);
  const pct = parseInt(document.getElementById('topPct').value, 10);
  const showBan = document.getElementById('showBanned').checked;
  let rows = rankCut(pct);
  return rows.filter(r => {{
    if (r.banned && !showBan) return false;
    const p = r.price;
    if (!isNaN(pmin) && p < pmin) return false;
    if (!isNaN(pmax) && p > pmax) return false;
    return true;
  }});
}}

function updateStats(rows) {{
  const bannedHidden = ALL.filter(r => r.banned).length;
  const prices = rows.map(r => r.price).filter(p => p > 0);
  const lo = prices.length ? Math.min(...prices).toFixed(2) : '—';
  const hi = prices.length ? Math.max(...prices).toFixed(2) : '—';
  document.getElementById('banN').textContent = bannedHidden;
  document.getElementById('stats').textContent =
    `可见 ${{rows.length}} / 总 ${{ALL.length}} · 违禁默认隐藏 ${{bannedHidden}} 条 · 价格 $${{lo}} – $${{hi}}`;
}}

function escapeHtml(s) {{
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
}}

function openLink(r, e) {{
  if (r.link) window.open(r.link, '_blank', 'noopener');
}}

function renderPage() {{
  const rows = filterRows();
  updateStats(rows);
  const totalPages = Math.max(1, Math.ceil(rows.length / PAGE));
  page = Math.min(page, totalPages - 1);
  const slice = rows.slice(page * PAGE, page * PAGE + PAGE);
  const grid = document.getElementById('grid');
  grid.innerHTML = slice.map(r => {{
    const cls = ['card', r.banned ? 'banned' : ''].filter(Boolean).join(' ');
    const score = r.score != null ? r.score.toFixed(2) : '';
    const badge = `#${{r.rank}} · ${{score}}`;
    const imgPart = r.img_url
      ? `<img loading="lazy" referrerpolicy="no-referrer" src="${{escapeHtml(r.img_url)}}" alt="" onerror="this.replaceWith(Object.assign(document.createElement('div'),{{className:'ph',textContent:'无图'}}))"/>`
      : '<div class="ph">无图</div>';
    const localHint = r.img_missing && r.img_url
      ? '<span class="badge" style="top:auto;bottom:6px;left:6px;background:rgba(120,120,120,.85);font-size:9px">未缓存</span>' : '';
    const ban = r.banned && r.banned_hits
      ? `<div class="cate" style="color:#e02e24">${{escapeHtml(r.banned_hits)}}</div>` : '';
    return `<article class="${{cls}}" data-link="${{escapeHtml(r.link || '')}}">
      <div class="thumb">
        <span class="badge">${{badge}}</span>
        ${{imgPart}}
        ${{localHint}}
      </div>
      <div class="body">
        <div class="price"><small>$</small>${{r.price != null ? r.price.toFixed(2) : ''}}</div>
        <div class="title">${{escapeHtml(r.title || '')}}</div>
        <div class="cate">${{escapeHtml(r.cate || '')}}</div>
        ${{ban}}
      </div>
    </article>`;
  }}).join('');
  grid.querySelectorAll('.card').forEach((el, i) => {{
    el.addEventListener('click', () => {{
      const link = slice[i].link;
      if (link) window.open(link, '_blank', 'noopener');
    }});
  }});
  document.getElementById('pageInfo').textContent = `${{page + 1}} / ${{totalPages}}`;
  document.getElementById('prev').disabled = page <= 0;
  document.getElementById('next').disabled = page >= totalPages - 1;
}}

['applyPrice', 'topPct', 'showBanned'].forEach(id => {{
  const el = document.getElementById(id);
  el.addEventListener('change', () => {{ page = 0; renderPage(); }});
  el.addEventListener('click', () => {{ page = 0; renderPage(); }});
}});
document.getElementById('prev').onclick = () => {{ page = Math.max(0, page - 1); renderPage(); }};
document.getElementById('next').onclick = () => {{ page++; renderPage(); }};
renderPage();
</script>
</body>
</html>"""
    out.write_text(html, encoding="utf-8")


def rows_from_df(df) -> list[dict]:
    rows = []
    for _, r in df.iterrows():
        rows.append(
            {
                "id": str(r["商品ID"]),
                "rank": int(r["排名"]),
                "score": float(r["预测分"]),
                "price": float(r["美元价格"]),
                "title": str(r["标题"]),
                "cate": f"{r.get('一级类目', '')}/{r.get('二级类目', '')}",
                "img_url": abs_https(r.get("主图URL", "")),
                "link": abs_https(r.get("商品链接", "")),
                "banned": bool(r.get("banned", False)),
                "banned_hits": str(r.get("banned_hits", "")),
                "img_missing": bool(r.get("img_missing", False)),
            }
        )
    return rows


def render_share(rows: list[dict], title: str, out: Path, top_pct: float = 5.0) -> None:
    """单文件静态页：主图/链接为完整 https，适合发朋友双击打开（默认仅 Top 5%）。"""
    rows = sorted(rows, key=lambda r: -(r.get("score") or 0))
    if top_pct < 100:
        n = max(1, int(len(rows) * top_pct / 100))
        rows = rows[:n]
    cards = []
    for r in rows:
        img = abs_https(r.get("img_url", ""))
        link = abs_https(r.get("link", ""))
        badge = f"#{r.get('rank', '')} · {float(r.get('score', 0)):.2f}"
        price = float(r.get("price", 0))
        title_s = _esc(r.get("title", ""))
        cate = _esc(r.get("cate", ""))
        if img:
            img_tag = (
                f'<img src="{_esc(img)}" alt="" loading="lazy" '
                f'referrerpolicy="no-referrer" decoding="async" '
                f'onerror="this.outerHTML=\'<div class=ph>无图</div>\'"/>'
            )
        else:
            img_tag = '<div class="ph">无图</div>'
        open_attr = f' href="{_esc(link)}" target="_blank" rel="noopener"' if link else ""
        tag = "a" if link else "div"
        cards.append(
            f"""<{tag} class="card" data-price="{price:.4f}"{open_attr}>
  <div class="thumb"><span class="badge">{_esc(badge)}</span>{img_tag}</div>
  <div class="body">
    <div class="price"><small>$</small>{price:.2f}</div>
    <div class="title">{title_s}</div>
    <div class="cate">{cate}</div>
  </div>
</{tag}>"""
        )
    safe_title = _esc(title)
    body = "\n".join(cards)
    n_total = len(rows)
    page = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{safe_title}</title>
<style>
body {{ margin:0; font-family:"PingFang SC","Microsoft YaHei",sans-serif; background:#f4f4f5; }}
.hdr {{ background:#fff; padding:12px 16px; border-bottom:1px solid #e8e8e8; position:sticky; top:0; z-index:10; box-shadow:0 1px 4px rgba(0,0,0,.06); }}
.hdr h1 {{ margin:0; font-size:15px; }}
.hdr p {{ margin:6px 0 0; font-size:12px; color:#777; }}
.bar {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-top:10px; font-size:13px; }}
.bar input {{ width:4.5rem; padding:4px 6px; border:1px solid #ddd; border-radius:6px; }}
.bar button {{ background:#fb7701; color:#fff; border:none; border-radius:6px; padding:5px 12px; cursor:pointer; }}
#stats {{ margin-top:8px; font-size:12px; color:#666; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(168px,1fr)); gap:10px; padding:12px; max-width:1400px; margin:0 auto; }}
.card {{ background:#fff; border-radius:10px; overflow:hidden; border:1px solid #e8e8e8; text-decoration:none; color:inherit; display:block; }}
.card.is-hidden {{ display:none !important; }}
.card:hover {{ box-shadow:0 4px 14px rgba(0,0,0,.1); }}
.thumb {{ position:relative; aspect-ratio:1; background:#ececec; }}
.thumb img {{ width:100%; height:100%; object-fit:cover; display:block; }}
.ph {{ display:flex; align-items:center; justify-content:center; height:100%; color:#999; font-size:13px; }}
.badge {{ position:absolute; top:6px; left:6px; background:rgba(0,0,0,.72); color:#fff; font-size:10px; padding:3px 6px; border-radius:4px; }}
.body {{ padding:8px; }}
.price {{ color:#fb7701; font-weight:700; font-size:1.05rem; }}
.title {{ font-size:12px; line-height:1.35; margin-top:4px; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; min-height:2.1em; }}
.cate {{ font-size:11px; color:#888; margin-top:4px; }}
</style>
</head>
<body>
<header class="hdr">
  <h1>{safe_title}</h1>
  <p>模型 Top {top_pct:g}% · 本页 {n_total} 条 · 主图 https 直链（需联网）</p>
  <div class="bar">
    <label>最低价 $<input type="number" id="pmin" step="0.01" placeholder="不限"/></label>
    <label>最高价 $<input type="number" id="pmax" step="0.01" placeholder="不限"/></label>
    <button type="button" id="applyPrice">筛选价格</button>
  </div>
  <div id="stats"></div>
</header>
<div class="grid" id="grid">
{body}
</div>
<script>
(function() {{
  const TOTAL = {n_total};
  function apply() {{
    const pmin = parseFloat(document.getElementById('pmin').value);
    const pmax = parseFloat(document.getElementById('pmax').value);
    const cards = document.querySelectorAll('.card');
    let vis = 0, lo = Infinity, hi = -Infinity;
    cards.forEach(el => {{
      const p = parseFloat(el.getAttribute('data-price'));
      let ok = true;
      if (!isNaN(pmin) && p < pmin) ok = false;
      if (!isNaN(pmax) && p > pmax) ok = false;
      el.classList.toggle('is-hidden', !ok);
      if (ok) {{
        vis++;
        if (p < lo) lo = p;
        if (p > hi) hi = p;
      }}
    }});
    const range = vis ? ('$' + lo.toFixed(2) + ' – $' + hi.toFixed(2)) : '—';
    document.getElementById('stats').textContent =
      '可见 ' + vis + ' / ' + TOTAL + ' · 当前价格区间 ' + range;
  }}
  document.getElementById('applyPrice').addEventListener('click', apply);
  document.getElementById('pmin').addEventListener('change', apply);
  document.getElementById('pmax').addEventListener('change', apply);
  apply();
}})();
</script>
</body>
</html>"""
    out.write_text(page, encoding="utf-8")
