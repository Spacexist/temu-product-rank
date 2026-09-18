# -*- coding: utf-8 -*-
from __future__ import annotations

import html
import json
import re
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


FLAT_PRODUCT_RE = re.compile(
    r"(?i)(2\s*d|二维|二維|平面|flat\s*print|flat\s*printing|flat\s*product|"
    r"flat\s*products|unframed|frameless|无框|無框)"
)


def is_flat_print_product(row: dict) -> bool:
    """判断商品是否是 2D/平面印刷/无框画一类，分享 Top500 默认剔除。"""
    text = f"{row.get('title', '')} {row.get('cate', '')}"
    return bool(FLAT_PRODUCT_RE.search(text))


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
      ? `<img referrerpolicy="no-referrer" decoding="async" src="${{escapeHtml(r.img_url)}}" alt="" onerror="if(!this.dataset.r){{this.dataset.r=1;this.src=this.src.split('?')[0]+'?imageView2/2/w/400/q/70';return;}}this.replaceWith(Object.assign(document.createElement('div'),{{className:'ph',textContent:'无图'}}))"/>`
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
    """单文件静态页：主图/链接为完整 https，支持人工删品后另存分享版。"""
    rows = sorted(rows, key=lambda r: -(r.get("score") or 0))
    top_n = len(rows)
    n_all = len(rows)
    blocked_n = sum(1 for r in rows if r.get("banned"))
    rows = [r for r in rows if not r.get("banned")]
    rows = sorted(rows, key=lambda r: -(r.get("score") or 0))
    top_n = n_all
    cards = []
    for i, r in enumerate(rows, start=1):
        img = abs_https(r.get("img_url", ""))
        link = abs_https(r.get("link", ""))
        badge = f"#{r.get('rank', '')} · {float(r.get('score', 0)):.2f}"
        price = float(r.get("price", 0))
        title_s = _esc(r.get("title", ""))
        cate = _esc(r.get("cate", ""))
        if img:
            img_tag = (
                f'<img data-src="{_esc(img)}" alt="" decoding="async" '
                f'referrerpolicy="no-referrer"/>'
            )
        else:
            img_tag = '<div class="ph">无图</div>'
        link_btn = (
            f'<a class="open" href="{_esc(link)}" target="_blank" rel="noopener">打开</a>'
            if link
            else '<span class="open disabled">无链接</span>'
        )
        cards.append(
            f"""<article class="card" data-id="{_esc(r.get('id', ''))}" data-ord="{i}" data-price="{price:.4f}" data-cate="{cate}" data-title="{title_s}">
  <div class="thumb"><span class="badge">{_esc(badge)}</span>{img_tag}</div>
  <div class="body">
    <div class="price"><small>$</small>{price:.2f}</div>
    <div class="title">{title_s}</div>
    <div class="cate">{cate}</div>
    <div class="ops">{link_btn}<button type="button" class="drop">删除</button><button type="button" class="keep">保留</button></div>
  </div>
</article>"""
        )
    safe_title = _esc(title)
    body = "\n".join(cards)
    n_total = len(rows)
    cats = sorted({str(r.get("cate", "")).strip() for r in rows if str(r.get("cate", "")).strip()})
    cat_options = "\n".join(f'<option value="{_esc(c)}">{_esc(c)}</option>' for c in cats)
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
.bar input.search {{ width:14rem; max-width:54vw; }}
.bar select {{ max-width:18rem; padding:4px 6px; border:1px solid #ddd; border-radius:6px; background:#fff; }}
.bar button {{ background:#fb7701; color:#fff; border:none; border-radius:6px; padding:5px 12px; cursor:pointer; }}
.bar button.secondary {{ background:#333; }}
#stats {{ margin-top:8px; font-size:12px; color:#666; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(168px,1fr)); gap:10px; padding:12px; max-width:1400px; margin:0 auto; }}
.card {{ background:#fff; border-radius:10px; overflow:hidden; border:1px solid #e8e8e8; text-decoration:none; color:inherit; display:block; }}
.card.is-hidden {{ display:none !important; }}
.card.is-dropped {{ opacity:.35; filter:grayscale(.85); }}
.card.is-dropped .thumb::after {{ content:"已删除"; position:absolute; inset:0; display:flex; align-items:center; justify-content:center; background:rgba(0,0,0,.48); color:#fff; font-weight:700; font-size:18px; }}
.card:hover {{ box-shadow:0 4px 14px rgba(0,0,0,.1); }}
.thumb {{ position:relative; aspect-ratio:1; background:#ececec; }}
.thumb img {{ width:100%; height:100%; object-fit:cover; display:block; }}
.ph {{ display:flex; align-items:center; justify-content:center; height:100%; color:#999; font-size:13px; }}
.badge {{ position:absolute; top:6px; left:6px; background:rgba(0,0,0,.72); color:#fff; font-size:10px; padding:3px 6px; border-radius:4px; }}
.body {{ padding:8px; }}
.price {{ color:#fb7701; font-weight:700; font-size:1.05rem; }}
.title {{ font-size:12px; line-height:1.35; margin-top:4px; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; min-height:2.1em; }}
.cate {{ font-size:11px; color:#888; margin-top:4px; }}
.ops {{ display:flex; gap:6px; margin-top:8px; }}
.ops a,.ops button,.ops span {{ flex:1; text-align:center; border:1px solid #ddd; border-radius:6px; padding:4px 0; font-size:12px; text-decoration:none; background:#fff; color:#333; cursor:pointer; }}
.ops .drop {{ border-color:#f2b8b5; color:#c5221f; }}
.ops .keep {{ border-color:#b7dfc4; color:#137333; }}
.ops .disabled {{ color:#aaa; cursor:default; }}
</style>
</head>
<body>
<header class="hdr">
  <h1>{safe_title}</h1>
  <p>已按过滤词剔除 {blocked_n} 条 · 本页 {n_total} 条，预览默认 Top {top_pct:g}% · 主图仅加载可见卡片</p>
  <div class="bar">
    <label>Top <select id="topPct">
      <option value="5" {"selected" if abs(top_pct - 5) < 1e-6 else ""}>5%</option>
      <option value="10" {"selected" if abs(top_pct - 10) < 1e-6 else ""}>10%</option>
      <option value="20">20%</option>
      <option value="100">全部</option>
    </select></label>
    <label>最低价 $<input type="number" id="pmin" step="0.01" placeholder="不限"/></label>
    <label>最高价 $<input type="number" id="pmax" step="0.01" placeholder="不限"/></label>
    <label>关键词 <input class="search" type="search" id="kw" placeholder="标题关键词"/></label>
    <label>分类 <select id="cate"><option value="">全部分类</option>{cat_options}</select></label>
    <button type="button" id="applyPrice">筛选价格</button>
    <button type="button" id="toggleDropped" class="secondary">显示已删除</button>
    <button type="button" id="resetKeep" class="secondary">全部保留</button>
    <button type="button" id="saveHtml">保存筛选后HTML</button>
  </div>
  <div id="stats"></div>
</header>
<div class="grid" id="grid">
{body}
</div>
<script>
(function() {{
  const TOTAL = {n_total};
  const STORAGE_KEY = 'datta-share-dropped:' + document.title;
  let showDropped = false;
  function loadDropped() {{
    try {{
      return new Set(JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]'));
    }} catch (err) {{
      return new Set();
    }}
  }}
  function saveDropped() {{
    const ids = Array.from(document.querySelectorAll('.card.is-dropped'))
      .map(el => el.getAttribute('data-id'))
      .filter(Boolean);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(ids));
  }}
  function restoreDropped() {{
    const dropped = loadDropped();
    document.querySelectorAll('.card').forEach(el => {{
      if (dropped.has(el.getAttribute('data-id'))) el.classList.add('is-dropped');
    }});
  }}
  function apply() {{
    const pmin = parseFloat(document.getElementById('pmin').value);
    const pmax = parseFloat(document.getElementById('pmax').value);
    const kw = document.getElementById('kw').value.trim().toLowerCase();
    const cate = document.getElementById('cate').value;
    const pct = parseInt(document.getElementById('topPct').value, 10);
    const cut = (pct >= 100) ? TOTAL : Math.max(1, Math.ceil(TOTAL * pct / 100));
    const cards = document.querySelectorAll('.card');
    let vis = 0, kept = 0, dropped = 0, lo = Infinity, hi = -Infinity;
    cards.forEach(el => {{
      const p = parseFloat(el.getAttribute('data-price'));
      const isDropped = el.classList.contains('is-dropped');
      const title = (el.getAttribute('data-title') || '').toLowerCase();
      const cat = el.getAttribute('data-cate') || '';
      const ord = parseInt(el.getAttribute('data-ord') || '999999', 10);
      let ok = true;
      if (ord > cut) ok = false;
      if (isDropped && !showDropped) ok = false;
      if (!isNaN(pmin) && p < pmin) ok = false;
      if (!isNaN(pmax) && p > pmax) ok = false;
      if (kw && title.indexOf(kw) < 0) ok = false;
      if (cate && cat !== cate) ok = false;
      el.classList.toggle('is-hidden', !ok);
      if (isDropped) dropped++;
      else kept++;
      if (ok) {{
        vis++;
        if (p < lo) lo = p;
        if (p > hi) hi = p;
      }}
    }});
    hydrateVisibleImages();
    const range = vis ? ('$' + lo.toFixed(2) + ' – $' + hi.toFixed(2)) : '—';
    document.getElementById('stats').textContent =
      '可见 ' + vis + ' / ' + TOTAL + ' · 保留 ' + kept + ' · 已删除 ' + dropped + ' · 当前价格区间 ' + range;
  }}
  function hydrateVisibleImages() {{
    document.querySelectorAll('.card:not(.is-hidden) img[data-src]').forEach(img => {{
      if (img.getAttribute('src')) return;
      const url = img.getAttribute('data-src');
      img.addEventListener('error', function () {{
        if (this.dataset.retried) {{
          this.replaceWith(Object.assign(document.createElement('div'), {{className: 'ph', textContent: '无图'}}));
          return;
        }}
        this.dataset.retried = '1';
        this.src = url + (url.indexOf('?') >= 0 ? '&' : '?') + 'imageView2/2/w/400/q/70';
      }});
      img.src = url;
    }});
  }}
  function bindManualActions() {{
    document.querySelectorAll('.drop').forEach(btn => btn.addEventListener('click', e => {{
      e.preventDefault();
      e.stopPropagation();
      btn.closest('.card').classList.add('is-dropped');
      saveDropped();
      apply();
    }}));
    document.querySelectorAll('.keep').forEach(btn => btn.addEventListener('click', e => {{
      e.preventDefault();
      e.stopPropagation();
      btn.closest('.card').classList.remove('is-dropped');
      saveDropped();
      apply();
    }}));
  }}
  async function saveFilteredHtml() {{
    const keptEls = Array.from(document.querySelectorAll('.card'))
      .filter(el => !el.classList.contains('is-dropped') && !el.classList.contains('is-hidden'));
    const savedCatOptions = Array.from(new Set(keptEls.map(el => el.getAttribute('data-cate') || '').filter(Boolean)))
      .sort()
      .map(c => '<option value="' + c.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;') + '">' + c.replace(/&/g, '&amp;').replace(/</g, '&lt;') + '</option>')
      .join('');
    const keptCards = keptEls
      .map(el => {{
        const clone = el.cloneNode(true);
        clone.classList.remove('is-hidden', 'is-dropped');
        clone.querySelectorAll('.drop,.keep').forEach(btn => btn.remove());
        return clone.outerHTML;
      }});
    const doc = '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/><title>选品</title><style>' +
      'body{{margin:0;font-family:"PingFang SC","Microsoft YaHei",sans-serif;background:#f4f4f5;}}.hdr{{background:#fff;padding:12px 16px;border-bottom:1px solid #e8e8e8;position:sticky;top:0;z-index:10;box-shadow:0 1px 4px rgba(0,0,0,.06);}}.bar{{display:flex;flex-wrap:wrap;gap:8px;align-items:center;font-size:13px;}}.bar input{{width:4.5rem;padding:4px 6px;border:1px solid #ddd;border-radius:6px;}}.bar input.search{{width:14rem;max-width:54vw;}}.bar select{{max-width:18rem;padding:4px 6px;border:1px solid #ddd;border-radius:6px;background:#fff;}}.bar button{{background:#fb7701;color:#fff;border:none;border-radius:6px;padding:5px 12px;cursor:pointer;}}#stats{{margin-top:8px;font-size:12px;color:#666;}}.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(168px,1fr));gap:10px;padding:12px;max-width:1400px;margin:0 auto;}}.card{{background:#fff;border-radius:10px;overflow:hidden;border:1px solid #e8e8e8;text-decoration:none;color:inherit;display:block;}}.card.is-hidden{{display:none!important;}}.thumb{{position:relative;aspect-ratio:1;background:#ececec;}}.thumb img{{width:100%;height:100%;object-fit:cover;display:block;}}.ph{{display:flex;align-items:center;justify-content:center;height:100%;color:#999;font-size:13px;}}.badge{{position:absolute;top:6px;left:6px;background:rgba(0,0,0,.72);color:#fff;font-size:10px;padding:3px 6px;border-radius:4px;}}.body{{padding:8px;}}.price{{color:#fb7701;font-weight:700;font-size:1.05rem;}}.title{{font-size:12px;line-height:1.35;margin-top:4px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;min-height:2.1em;}}.cate{{font-size:11px;color:#888;margin-top:4px;}}.ops{{display:flex;gap:6px;margin-top:8px;}}.ops a{{flex:1;text-align:center;border:1px solid #ddd;border-radius:6px;padding:4px 0;font-size:12px;text-decoration:none;background:#fff;color:#333;}}' +
      '</style></head><body><header class="hdr"><div class="bar"><label>最低价 $<input type="number" id="pmin" step="0.01" placeholder="不限"/></label><label>最高价 $<input type="number" id="pmax" step="0.01" placeholder="不限"/></label><label>关键词 <input class="search" type="search" id="kw" placeholder="标题关键词"/></label><label>分类 <select id="cate"><option value="">全部分类</option>' + savedCatOptions + '</select></label><button type="button" id="applyPrice">筛选价格</button></div><div id="stats"></div></header><div class="grid">' +
      keptCards.join('\\n') + '</div><script>(function(){{const TOTAL=' + keptCards.length + ';function apply(){{const pmin=parseFloat(document.getElementById(\"pmin\").value);const pmax=parseFloat(document.getElementById(\"pmax\").value);const kw=document.getElementById(\"kw\").value.trim().toLowerCase();const cate=document.getElementById(\"cate\").value;let vis=0,lo=Infinity,hi=-Infinity;document.querySelectorAll(\".card\").forEach(el=>{{const p=parseFloat(el.getAttribute(\"data-price\"));const title=(el.getAttribute(\"data-title\")||\"\").toLowerCase();const cat=el.getAttribute(\"data-cate\")||\"\";let ok=true;if(!isNaN(pmin)&&p<pmin)ok=false;if(!isNaN(pmax)&&p>pmax)ok=false;if(kw&&title.indexOf(kw)<0)ok=false;if(cate&&cat!==cate)ok=false;el.classList.toggle(\"is-hidden\",!ok);if(ok){{vis++;if(p<lo)lo=p;if(p>hi)hi=p;}}}});const range=vis?(\"$\"+lo.toFixed(2)+\" – $\"+hi.toFixed(2)):\"—\";document.getElementById(\"stats\").textContent=\"可见 \"+vis+\" / \"+TOTAL+\" · 当前价格区间 \"+range;}}document.getElementById(\"applyPrice\").addEventListener(\"click\",apply);document.getElementById(\"pmin\").addEventListener(\"change\",apply);document.getElementById(\"pmax\").addEventListener(\"change\",apply);document.getElementById(\"kw\").addEventListener(\"input\",apply);document.getElementById(\"cate\").addEventListener(\"change\",apply);apply();}})();<\\/script></body></html>';
    const blob = new Blob([doc], {{ type: 'text/html;charset=utf-8' }});
    const filename = '选品.html';
    if (window.showSaveFilePicker) {{
      const handle = await window.showSaveFilePicker({{
        suggestedName: filename,
        types: [{{ description: 'HTML 文件', accept: {{ 'text/html': ['.html'] }} }}]
      }});
      const writable = await handle.createWritable();
      await writable.write(blob);
      await writable.close();
      return;
    }}
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(a.href);
  }}
  document.getElementById('applyPrice').addEventListener('click', apply);
  document.getElementById('pmin').addEventListener('change', apply);
  document.getElementById('pmax').addEventListener('change', apply);
  document.getElementById('kw').addEventListener('input', apply);
  document.getElementById('cate').addEventListener('change', apply);
  document.getElementById('topPct').addEventListener('change', apply);
  document.getElementById('toggleDropped').addEventListener('click', () => {{
    showDropped = !showDropped;
    document.getElementById('toggleDropped').textContent = showDropped ? '隐藏已删除' : '显示已删除';
    apply();
  }});
  document.getElementById('resetKeep').addEventListener('click', () => {{
    document.querySelectorAll('.card.is-dropped').forEach(el => el.classList.remove('is-dropped'));
    saveDropped();
    apply();
  }});
  document.getElementById('saveHtml').addEventListener('click', saveFilteredHtml);
  bindManualActions();
  restoreDropped();
  apply();
}})();
</script>
</body>
</html>"""
    out.write_text(page, encoding="utf-8")
