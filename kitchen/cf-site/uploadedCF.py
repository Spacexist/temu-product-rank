# -*- coding: utf-8 -*-
"""选品 CSV/HTML 标准化后上传 Cloudflare。

双击 uploadedCF.bat 打开界面：导入 CSV -> 生成标准页 -> 预览 / 上传。
命令行仍支持：python uploadedCF.py 文件.csv|.html
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

SITE_ROOT = Path(__file__).resolve().parent
PUBLIC = SITE_ROOT / "public"
DAYS_JSON = PUBLIC / "days.json"
NAV_JS = PUBLIC / "date-nav.js"
PREVIEW_DIR = SITE_ROOT / "preview"
SCREENER_SRC = SITE_ROOT.parent / "screener" / "src"
WORKER_URL = "https://datta-picks.changkaishen7788.workers.dev"

NAV_CSS = """
.date-nav{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:10px;padding-top:10px;border-top:1px solid #eee;font-size:13px}
.date-nav label{display:flex;align-items:center;gap:6px}
.date-nav input,.date-nav select{padding:4px 6px;border:1px solid #ddd;border-radius:6px;background:#fff}
.date-nav a.latest{color:#fb7701;text-decoration:none;font-weight:600}
"""

if str(SCREENER_SRC) not in sys.path:
    sys.path.insert(0, str(SCREENER_SRC))

from render_html import _esc, abs_https, is_flat_print_product, rows_from_df  # noqa: E402


def parse_day(path: Path, now: datetime | None = None) -> tuple[str, str, str]:
    """从文件名解析 ISO 日期、短码、展示名。"""
    now = now or datetime.now()
    stem = path.stem
    stem = re.sub(r"(_scored|_分享|_screener|_Top5pct.*)$", "", stem, flags=re.I)
    m = re.match(r"^(\d{3,8})(.*)$", stem)
    digits = m.group(1) if m else ""
    rest = (m.group(2) if m else stem).strip()
    rest = re.sub(r"^(参考选品[-_]?|分享|_分享)", "", rest).strip("-_ ")
    year = now.year
    if len(digits) == 8:
        iso = f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"
        short = str(int(digits[4:6])) + digits[6:]
    elif len(digits) == 4:
        iso = f"{year}-{digits[:2]}-{digits[2:]}"
        short = str(int(digits[:2])) + digits[2:]
    elif len(digits) == 3:
        iso = f"{year}-{int(digits[0]):02d}-{int(digits[1:]):02d}"
        short = digits
    else:
        iso = now.strftime("%Y-%m-%d")
        short = f"{now.month}{now.day:02d}"
    label = f"{iso} {rest}" if rest else iso
    return iso, short, label


def strip_public_banner(html: str) -> str:
    """线上页不要「人工筛选版 / 人工保留 N 条」这类工作台文案。"""
    html = re.sub(r"<title>[^<]*人工筛选版</title>", "<title>选品</title>", html, count=1)
    html = re.sub(r"<h1>[^<]*人工筛选版</h1>", "", html, count=1)
    html = re.sub(r"<h1>选品[^<]*</h1>", "", html, count=1)
    html = re.sub(
        r"<p>人工保留 \d+ 条 · 主图[^<]*</p>",
        "",
        html,
        count=1,
    )
    html = re.sub(
        r"<p>标准化选品 \d+ 条 · 主图[^<]*</p>",
        "",
        html,
        count=1,
    )
    return html


def inject_nav(html: str, day_id: str) -> str:
    """写入日期标记，并挂上线上日期导航。"""
    html = strip_public_banner(html)
    html = re.sub(r'\sdata-picks-date="[^"]*"', "", html, count=1)
    html = html.replace('<html lang="zh-CN">', f'<html lang="zh-CN" data-picks-date="{day_id}">', 1)
    if "data-picks-date=" not in html:
        html = html.replace("<html", f'<html data-picks-date="{day_id}"', 1)
    if ".date-nav{" not in html and "</style>" in html:
        html = html.replace("</style>", NAV_CSS + "</style>", 1)
    if "/date-nav.js" not in html:
        if "</body>" in html:
            html = html.replace("</body>", '<script src="/date-nav.js"></script></body>', 1)
        else:
            html += '<script src="/date-nav.js"></script>'
    return html


def upsert_days(iso: str, short: str, label: str) -> dict:
    """把当天写入 days.json，并设为 latest。"""
    PUBLIC.mkdir(parents=True, exist_ok=True)
    data = {"latest": iso, "days": []}
    if DAYS_JSON.exists():
        try:
            data = json.loads(DAYS_JSON.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    days = [d for d in data.get("days", []) if d.get("id") != iso]
    days.append({"id": iso, "short": short, "label": label, "path": f"/days/{iso}/"})
    days.sort(key=lambda d: str(d.get("id", "")), reverse=True)
    payload = {"latest": iso, "days": days}
    DAYS_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def write_pages(html: str, iso: str, short: str) -> None:
    """写成当天归档、短码别名、以及首页最新版。"""
    for folder in (PUBLIC / "days" / iso, PUBLIC / "days" / short):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "index.html").write_text(html, encoding="utf-8")
    (PUBLIC / "index.html").write_text(html, encoding="utf-8")
    if not NAV_JS.exists():
        raise SystemExit(f"缺少 {NAV_JS}，无法发布日期导航")


def deploy() -> str:
    """在本目录调用 wrangler，返回线上地址。"""
    cmd = "npx --yes wrangler deploy"
    proc = subprocess.run(cmd, cwd=str(SITE_ROOT), shell=True)
    if proc.returncode != 0:
        raise SystemExit(f"wrangler 失败 exit={proc.returncode}")
    return WORKER_URL


def _pick_col(df, names: list[str]) -> str | None:
    """在表头里找第一个存在的列名。"""
    lower = {str(c).strip().lower(): c for c in df.columns}
    for name in names:
        if name in df.columns:
            return name
        hit = lower.get(name.lower())
        if hit is not None:
            return hit
    return None


def load_table(path: Path):
    """读 CSV；失败则按 Excel 再读一遍。"""
    import pandas as pd

    last_err = None
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return pd.read_csv(path, encoding=enc, dtype=str, keep_default_na=False)
        except Exception as exc:
            last_err = exc
    try:
        return pd.read_excel(path, sheet_name="sheet", header=[0, 1], dtype=str)
    except Exception:
        pass
    try:
        return pd.read_excel(path, dtype=str)
    except Exception as exc:
        last_err = exc
    raise SystemExit(f"无法读取表格: {path}\n{last_err}")


def normalize_df(df):
    """把各种导出表头收成 render_html 需要的标准列。"""
    import pandas as pd

    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [
            str(b).strip() if not str(b).startswith("Unnamed") else str(a).strip()
            for a, b in df.columns
        ]
    mapping = {
        "商品ID": _pick_col(df, ["商品ID", "id", "ID"]),
        "标题": _pick_col(df, ["标题", "商品标题（中文）", "商品标题", "title"]),
        "美元价格": _pick_col(df, ["美元价格", "美元价格($)", "价格", "price"]),
        "主图URL": _pick_col(df, ["主图URL", "商品主图", "main_url", "img"]),
        "商品链接": _pick_col(df, ["商品链接", "链接", "link"]),
        "排名": _pick_col(df, ["排名", "rank"]),
        "预测分": _pick_col(df, ["预测分", "score"]),
        "一级类目": _pick_col(df, ["一级类目", "cat_l1"]),
        "二级类目": _pick_col(df, ["二级类目", "cat_l2"]),
        "banned": _pick_col(df, ["banned"]),
        "banned_hits": _pick_col(df, ["banned_hits"]),
        "img_missing": _pick_col(df, ["img_missing"]),
    }
    missing = [k for k in ("商品ID", "标题", "美元价格") if mapping[k] is None]
    if missing:
        raise SystemExit("CSV 缺少必要列: " + ", ".join(missing))
    out = pd.DataFrame()
    out["商品ID"] = df[mapping["商品ID"]].astype(str)
    out["标题"] = df[mapping["标题"]].astype(str)
    out["美元价格"] = pd.to_numeric(df[mapping["美元价格"]], errors="coerce").fillna(0)
    out["主图URL"] = df[mapping["主图URL"]].astype(str) if mapping["主图URL"] else ""
    out["商品链接"] = df[mapping["商品链接"]].astype(str) if mapping["商品链接"] else ""
    if mapping["排名"]:
        out["排名"] = pd.to_numeric(df[mapping["排名"]], errors="coerce").fillna(0).astype(int)
    else:
        out["排名"] = range(1, len(df) + 1)
    if mapping["预测分"]:
        out["预测分"] = pd.to_numeric(df[mapping["预测分"]], errors="coerce").fillna(0)
    else:
        out["预测分"] = 0.0
    if mapping["一级类目"] and mapping["二级类目"]:
        out["一级类目"] = df[mapping["一级类目"]].astype(str)
        out["二级类目"] = df[mapping["二级类目"]].astype(str)
    else:
        cate = _pick_col(df, ["前台分类（中文）", "分类", "cate"])
        if cate:
            parts = df[cate].fillna("").astype(str).str.split("/", n=1, expand=True)
            out["一级类目"] = parts[0]
            out["二级类目"] = parts[1] if 1 in parts.columns else ""
        else:
            out["一级类目"] = ""
            out["二级类目"] = ""
    if mapping["banned"]:
        out["banned"] = df[mapping["banned"]].astype(str).str.lower().isin(("1", "true", "yes", "是"))
    else:
        out["banned"] = False
    out["banned_hits"] = df[mapping["banned_hits"]].astype(str) if mapping["banned_hits"] else ""
    if mapping["img_missing"]:
        out["img_missing"] = df[mapping["img_missing"]].astype(str).str.lower().isin(("1", "true", "yes"))
    else:
        out["img_missing"] = False
    return out


def filter_rows(rows: list[dict], top_pct: float, drop_banned: bool, drop_flat: bool) -> tuple[list[dict], dict]:
    """按分享页同一口径过滤，返回保留行和计数。"""
    ranked = sorted(rows, key=lambda r: -(r.get("score") or 0))
    raw_n = len(ranked)
    if 0 < top_pct < 100:
        ranked = ranked[: max(1, int(len(ranked) * top_pct / 100))]
    top_n = len(ranked)
    blocked = 0
    kept = []
    for r in ranked:
        bad = (drop_banned and r.get("banned")) or (drop_flat and is_flat_print_product(r))
        if bad:
            blocked += 1
            continue
        kept.append(r)
    stats = {"raw": raw_n, "top": top_n, "blocked": blocked, "kept": len(kept)}
    return kept, stats


def build_public_html(rows: list[dict], title: str) -> str:
    """生成线上标准页：价格/关键词/分类筛选，无删除按钮。"""
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
                f"onerror=\"this.outerHTML='<div class=ph>无图</div>'\">"
            )
        else:
            img_tag = '<div class="ph">无图</div>'
        link_btn = (
            f'<a class="open" href="{_esc(link)}" target="_blank" rel="noopener">打开</a>'
            if link
            else '<span class="open disabled">无链接</span>'
        )
        cards.append(
            f'<article class="card" data-id="{_esc(r.get("id", ""))}" data-price="{price:.4f}" '
            f'data-cate="{cate}" data-title="{title_s}">'
            f'<div class="thumb"><span class="badge">{_esc(badge)}</span>{img_tag}</div>'
            f'<div class="body"><div class="price"><small>$</small>{price:.2f}</div>'
            f'<div class="title">{title_s}</div><div class="cate">{cate}</div>'
            f'<div class="ops">{link_btn}</div></div></article>'
        )
    cats = sorted({str(r.get("cate", "")).strip() for r in rows if str(r.get("cate", "")).strip()})
    cat_options = "".join(f'<option value="{_esc(c)}">{_esc(c)}</option>' for c in cats)
    safe_title = _esc(title)
    n_total = len(rows)
    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{safe_title}</title>
<style>
body{{margin:0;font-family:"PingFang SC","Microsoft YaHei",sans-serif;background:#f4f4f5;}}
.hdr{{background:#fff;padding:12px 16px;border-bottom:1px solid #e8e8e8;position:sticky;top:0;z-index:10;box-shadow:0 1px 4px rgba(0,0,0,.06);}}
.hdr h1{{margin:0;font-size:15px;}}.hdr p{{margin:6px 0 0;font-size:12px;color:#777;}}
.bar{{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:10px;font-size:13px;}}
.bar input{{width:4.5rem;padding:4px 6px;border:1px solid #ddd;border-radius:6px;}}
.bar input.search{{width:14rem;max-width:54vw;}}
.bar select{{max-width:18rem;padding:4px 6px;border:1px solid #ddd;border-radius:6px;background:#fff;}}
.bar button{{background:#fb7701;color:#fff;border:none;border-radius:6px;padding:5px 12px;cursor:pointer;}}
#stats{{margin-top:8px;font-size:12px;color:#666;}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(168px,1fr));gap:10px;padding:12px;max-width:1400px;margin:0 auto;}}
.card{{background:#fff;border-radius:10px;overflow:hidden;border:1px solid #e8e8e8;text-decoration:none;color:inherit;display:block;}}
.card.is-hidden{{display:none!important;}}
.thumb{{position:relative;aspect-ratio:1;background:#ececec;}}
.thumb img{{width:100%;height:100%;object-fit:cover;display:block;}}
.ph{{display:flex;align-items:center;justify-content:center;height:100%;color:#999;font-size:13px;}}
.badge{{position:absolute;top:6px;left:6px;background:rgba(0,0,0,.72);color:#fff;font-size:10px;padding:3px 6px;border-radius:4px;}}
.body{{padding:8px;}}.price{{color:#fb7701;font-weight:700;font-size:1.05rem;}}
.title{{font-size:12px;line-height:1.35;margin-top:4px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;min-height:2.1em;}}
.cate{{font-size:11px;color:#888;margin-top:4px;}}
.ops{{display:flex;gap:6px;margin-top:8px;}}
.ops a,.ops span{{flex:1;text-align:center;border:1px solid #ddd;border-radius:6px;padding:4px 0;font-size:12px;text-decoration:none;background:#fff;color:#333;}}
</style></head><body>
<header class="hdr">
<div class="bar">
<label>最低价 $<input type="number" id="pmin" step="0.01" placeholder="不限"/></label>
<label>最高价 $<input type="number" id="pmax" step="0.01" placeholder="不限"/></label>
<label>关键词 <input class="search" type="search" id="kw" placeholder="标题关键词"/></label>
<label>分类 <select id="cate"><option value="">全部分类</option>{cat_options}</select></label>
<button type="button" id="applyPrice">筛选价格</button>
</div><div id="stats"></div></header>
<div class="grid">{"".join(cards)}</div>
<script>(function(){{const TOTAL={n_total};function apply(){{const pmin=parseFloat(document.getElementById("pmin").value);const pmax=parseFloat(document.getElementById("pmax").value);const kw=document.getElementById("kw").value.trim().toLowerCase();const cate=document.getElementById("cate").value;let vis=0,lo=Infinity,hi=-Infinity;document.querySelectorAll(".card").forEach(el=>{{const p=parseFloat(el.getAttribute("data-price"));const title=(el.getAttribute("data-title")||"").toLowerCase();const cat=el.getAttribute("data-cate")||"";let ok=true;if(!isNaN(pmin)&&p<pmin)ok=false;if(!isNaN(pmax)&&p>pmax)ok=false;if(kw&&title.indexOf(kw)<0)ok=false;if(cate&&cat!==cate)ok=false;el.classList.toggle("is-hidden",!ok);if(ok){{vis++;if(p<lo)lo=p;if(p>hi)hi=p;}}}});const range=vis?("$"+lo.toFixed(2)+" – $"+hi.toFixed(2)):"—";document.getElementById("stats").textContent="可见 "+vis+" / "+TOTAL+" · 当前价格区间 "+range;}}document.getElementById("applyPrice").addEventListener("click",apply);document.getElementById("pmin").addEventListener("change",apply);document.getElementById("pmax").addEventListener("change",apply);document.getElementById("kw").addEventListener("input",apply);document.getElementById("cate").addEventListener("change",apply);apply();}})();</script>
</body></html>"""


def looks_prefiltered(path: Path, n_rows: int) -> bool:
    """已经是 Top5/去违禁导出时，不再二次截 Top5%。"""
    name = path.name.lower()
    if "top5" in name or "去违禁" in path.name or "人工" in path.name:
        return True
    return n_rows <= 800


def html_from_csv(path: Path, title: str, top_pct: float, drop_banned: bool, drop_flat: bool) -> tuple[str, dict]:
    """CSV -> 标准线上 HTML。"""
    df = normalize_df(load_table(path))
    rows = rows_from_df(df)
    kept, stats = filter_rows(rows, top_pct, drop_banned, drop_flat)
    if not kept:
        raise SystemExit("过滤后没有商品，检查 CSV 或关掉 Top5%/违禁/2D 选项")
    return build_public_html(kept, title), stats


class UploaderApp:
    """本机上传窗口：导入 CSV，生成标准 HTML，再发到 Cloudflare。"""

    def __init__(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.src: Path | None = None
        self.html = ""
        self.stats: dict = {}
        root = tk.Tk()
        self.root = root
        root.title("选品上传 Cloudflare")
        root.geometry("660x560")
        root.configure(bg="#f4f4f5")
        root.minsize(580, 500)

        pad = {"padx": 14, "pady": 6}
        ttk.Label(root, text="导入今天的 CSV，生成标准选品页后上传。", background="#f4f4f5").pack(anchor="w", **pad)

        row = ttk.Frame(root)
        row.pack(fill="x", padx=14)
        ttk.Button(row, text="导入 CSV", command=self.on_import_csv).pack(side="left")
        ttk.Button(row, text="导入现有 HTML", command=self.on_import_html).pack(side="left", padx=8)
        self.path_var = tk.StringVar(value="还没有选择文件")
        ttk.Label(row, textvariable=self.path_var, background="#f4f4f5").pack(side="left", fill="x", expand=True)

        today = datetime.now()
        self._syncing_date = False
        self.year_var = tk.IntVar(value=today.year)
        self.month_var = tk.IntVar(value=today.month)
        self.day_var = tk.IntVar(value=today.day)
        self.iso_var = tk.StringVar(value=today.strftime("%Y-%m-%d"))
        self.short_var = tk.StringVar(value=f"{today.month}{today.day:02d}")
        self.note_var = tk.StringVar()
        self.title_var = tk.StringVar()

        date_row = ttk.LabelFrame(root, text="发布日期（可手动改）")
        date_row.pack(fill="x", padx=14, pady=8)
        inner = ttk.Frame(date_row)
        inner.pack(fill="x", padx=8, pady=8)
        ttk.Label(inner, text="年").pack(side="left")
        tk.Spinbox(inner, from_=2024, to=2035, textvariable=self.year_var, width=6, command=self._on_date_spin).pack(side="left", padx=(4, 10))
        ttk.Label(inner, text="月").pack(side="left")
        tk.Spinbox(inner, from_=1, to=12, textvariable=self.month_var, width=4, command=self._on_date_spin).pack(side="left", padx=(4, 10))
        ttk.Label(inner, text="日").pack(side="left")
        tk.Spinbox(inner, from_=1, to=31, textvariable=self.day_var, width=4, command=self._on_date_spin).pack(side="left", padx=(4, 10))
        ttk.Button(inner, text="今天", command=self._set_today).pack(side="left", padx=(8, 12))
        ttk.Label(inner, text="ISO").pack(side="left")
        ttk.Entry(inner, textvariable=self.iso_var, width=12).pack(side="left", padx=4)
        ttk.Label(inner, textvariable=self.short_var).pack(side="left", padx=8)

        self.year_var.trace_add("write", lambda *_: self._on_date_spin())
        self.month_var.trace_add("write", lambda *_: self._on_date_spin())
        self.day_var.trace_add("write", lambda *_: self._on_date_spin())
        self.iso_var.trace_add("write", lambda *_: self._on_iso_typed())

        grid = ttk.Frame(root)
        grid.pack(fill="x", padx=14, pady=4)
        self._labeled(grid, 0, "短码", self.short_var, 8)
        self._labeled(grid, 1, "备注", self.note_var, 28)

        opts = ttk.Frame(root)
        opts.pack(fill="x", padx=14)
        self.top5 = tk.BooleanVar(value=True)
        self.banned = tk.BooleanVar(value=True)
        self.flat = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="Top 5%", variable=self.top5).pack(side="left")
        ttk.Checkbutton(opts, text="去违禁词", variable=self.banned).pack(side="left", padx=10)
        ttk.Checkbutton(opts, text="去 2D/平面", variable=self.flat).pack(side="left")

        self.status_var = tk.StringVar(value="先导入 CSV。scored.csv 会按 Top5% + 去违禁 + 去 2D 标准化。")
        ttk.Label(root, textvariable=self.status_var, background="#f4f4f5").pack(anchor="w", **pad)

        actions = ttk.Frame(root)
        actions.pack(fill="x", padx=14, pady=4)
        ttk.Button(actions, text="生成并预览", command=self.on_preview).pack(side="left")
        self.upload_btn = ttk.Button(actions, text="上传 Cloudflare", command=self.on_upload)
        self.upload_btn.pack(side="left", padx=8)

        self.log = tk.Text(root, height=14, wrap="word", font=("Consolas", 9), bg="#fff")
        self.log.pack(fill="both", expand=True, padx=14, pady=(8, 14))
        self._log("站点 " + WORKER_URL)

    def _labeled(self, parent, col: int, text: str, var, width: int) -> None:
        """放一列带标签的输入框。"""
        from tkinter import ttk

        box = ttk.Frame(parent)
        box.grid(row=0, column=col, sticky="w", padx=(0, 10))
        ttk.Label(box, text=text).pack(anchor="w")
        ttk.Entry(box, textvariable=var, width=width).pack(anchor="w")

    def _log(self, msg: str) -> None:
        """往窗口日志追加一行。"""
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.root.update_idletasks()

    def _ask(self, title: str, patterns: list[tuple[str, str]]) -> Path | None:
        """打开文件选择框。"""
        from tkinter import filedialog

        desktop = Path.home() / "Desktop"
        chosen = filedialog.askopenfilename(
            title=title,
            initialdir=str(desktop if desktop.is_dir() else Path.home()),
            filetypes=patterns,
        )
        return Path(chosen).resolve() if chosen else None

    def _set_today(self) -> None:
        """把发布日期拨到系统今天。"""
        now = datetime.now()
        self._apply_iso(now.strftime("%Y-%m-%d"))

    def _short_from_iso(self, iso: str) -> str:
        """2026-09-18 -> 918。"""
        try:
            _y, m, d = iso.split("-")
            return f"{int(m)}{int(d):02d}"
        except ValueError:
            return iso.replace("-", "")[-3:]

    def _apply_iso(self, iso: str, short: str | None = None) -> None:
        """同步年/月/日、ISO 和短码。"""
        try:
            parsed = datetime.strptime(iso, "%Y-%m-%d")
        except ValueError:
            return
        self._syncing_date = True
        self.year_var.set(parsed.year)
        self.month_var.set(parsed.month)
        self.day_var.set(parsed.day)
        self.iso_var.set(iso)
        self.short_var.set(short or self._short_from_iso(iso))
        self._syncing_date = False

    def _on_date_spin(self) -> None:
        """手动拨年月日时，重写 ISO 和短码。"""
        if self._syncing_date:
            return
        try:
            y, m, d = int(self.year_var.get()), int(self.month_var.get()), int(self.day_var.get())
            iso = f"{y:04d}-{m:02d}-{d:02d}"
            datetime.strptime(iso, "%Y-%m-%d")
        except (ValueError, self.tk.TclError):
            return
        self._syncing_date = True
        self.iso_var.set(iso)
        self.short_var.set(self._short_from_iso(iso))
        self._syncing_date = False

    def _on_iso_typed(self) -> None:
        """直接改 ISO 文本时，回写年/月/日。"""
        if self._syncing_date:
            return
        self._apply_iso(self.iso_var.get().strip())

    def _fill_from_path(self, path: Path) -> None:
        """用文件名回填日期、短码、备注；仍可再手动改日期。"""
        iso, short, label = parse_day(path)
        note = label[len(iso) :].strip() if label.startswith(iso) else ""
        self._apply_iso(iso, short)
        self.note_var.set(note)
        self.path_var.set(str(path))

    def on_import_csv(self) -> None:
        """选择 CSV 并预读行数、自动判断要不要再截 Top5%。"""
        path = self._ask("选择选品 CSV", [("CSV", "*.csv"), ("Excel", "*.xlsx *.xls"), ("全部", "*.*")])
        if path is None:
            return
        try:
            df = normalize_df(load_table(path))
        except Exception as exc:
            self._log(f"读取失败: {exc}")
            return
        self.src = path
        self.html = ""
        self._fill_from_path(path)
        pre = looks_prefiltered(path, len(df))
        self.top5.set(not pre)
        self.banned.set(True)
        self.flat.set(True)
        self.status_var.set(f"已导入 {len(df)} 行。{'已像过滤结果，默认不再截 Top5%。' if pre else '按 scored 全量处理：Top5% + 去违禁 + 去2D。'}")
        self._log(f"导入 CSV {path.name}  {len(df)} 行")

    def on_import_html(self) -> None:
        """兼容已经手筛好的 HTML，仍走同一套上传。"""
        path = self._ask("选择选品 HTML", [("HTML", "*.html *.htm"), ("全部", "*.*")])
        if path is None:
            return
        self.src = path
        self.html = path.read_text(encoding="utf-8")
        self._fill_from_path(path)
        self.status_var.set("已读入现有 HTML，可直接预览或上传。")
        self._log(f"导入 HTML {path.name}")

    def _page_title(self) -> str:
        """生成标准页标题。"""
        iso = self.iso_var.get().strip() or datetime.now().strftime("%Y-%m-%d")
        note = self.note_var.get().strip()
        return f"选品 {iso}" + (f" · {note}" if note else "")

    def build_html(self) -> str:
        """按当前选项生成标准 HTML。"""
        if self.src is None:
            raise SystemExit("请先导入 CSV 或 HTML")
        if self.src.suffix.lower() in {".html", ".htm"}:
            html = self.src.read_text(encoding="utf-8")
            self.stats = {"kept": html.count('class="card"')}
            return html
        top_pct = 5.0 if self.top5.get() else 100.0
        html, stats = html_from_csv(
            self.src,
            self._page_title(),
            top_pct,
            self.banned.get(),
            self.flat.get(),
        )
        self.stats = stats
        self.status_var.set(
            f"原始 {stats['raw']} → Top {stats['top']} → 去掉 {stats['blocked']} → 保留 {stats['kept']}"
        )
        self._log(self.status_var.get())
        return html

    def on_preview(self) -> None:
        """生成本地标准 HTML 并用浏览器打开。"""
        try:
            html = self.build_html()
            iso = self.iso_var.get().strip() or datetime.now().strftime("%Y-%m-%d")
            html = inject_nav(html, iso)
            self.html = html
            PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
            out = PREVIEW_DIR / f"{iso}.html"
            out.write_text(html, encoding="utf-8")
            webbrowser.open(out.as_uri())
            self._log(f"预览 {out}")
        except Exception as exc:
            self._log(f"预览失败: {exc}")

    def on_upload(self) -> None:
        """后台发布，避免窗口卡住。"""
        self.upload_btn.state(["disabled"])
        threading.Thread(target=self._upload_job, daemon=True).start()

    def _upload_job(self) -> None:
        """生成页面、写入 public、调用 wrangler。"""
        try:
            html = self.html or self.build_html()
            iso = self.iso_var.get().strip() or datetime.now().strftime("%Y-%m-%d")
            short = self.short_var.get().strip() or iso.replace("-", "")[-3:]
            note = self.note_var.get().strip()
            label = f"{iso} {note}".strip()
            html = inject_nav(html, iso)
            self.html = html
            write_pages(html, iso, short)
            upsert_days(iso, short, label)
            self.root.after(0, lambda: self._log("开始 wrangler deploy…"))
            url = deploy()
            self.root.after(0, lambda: self._done(url, iso))
        except Exception as exc:
            msg = str(exc)
            self.root.after(0, lambda m=msg: self._fail(m))

    def _done(self, url: str, iso: str) -> None:
        """上传成功后恢复按钮并写出链接。"""
        self.upload_btn.state(["!disabled"])
        self.status_var.set(f"已上线 {url}")
        self._log(f"最新 {url}")
        self._log(f"归档 {url}/days/{iso}/")
        webbrowser.open(url)

    def _fail(self, msg: str) -> None:
        """上传失败时恢复按钮。"""
        self.upload_btn.state(["!disabled"])
        self.status_var.set("上传失败")
        self._log(f"失败: {msg}")

    def run(self) -> None:
        """进入窗口循环。"""
        self.root.mainloop()


def run_headless(path: Path) -> None:
    """命令行丢一个文件进来：CSV 标准化，HTML 原样，然后上传。"""
    iso, short, label = parse_day(path)
    if path.suffix.lower() in {".csv", ".xlsx", ".xls"}:
        pre = looks_prefiltered(path, 10**9)
        html, stats = html_from_csv(path, f"选品 {iso}", 100.0 if pre else 5.0, True, True)
        print(f"[csv] {stats}")
    else:
        html = path.read_text(encoding="utf-8")
    html = inject_nav(html, iso)
    write_pages(html, iso, short)
    upsert_days(iso, short, label)
    url = deploy()
    print(f"[done] 最新 {url}")
    print(f"[done] 归档 {url}/days/{iso}/")


def main() -> None:
    """有文件参数就直接传；否则开 UI。"""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) > 1:
        run_headless(Path(sys.argv[1]).expanduser().resolve())
        return
    UploaderApp().run()


if __name__ == "__main__":
    main()
