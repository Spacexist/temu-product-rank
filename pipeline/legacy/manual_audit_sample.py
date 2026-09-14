# -*- coding: utf-8 -*-
"""分层抽 N 条（正例率对齐 train）→ 静态 JSON + HTML（主图用 URL，不跑嵌入/打分）。"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

import rank_products as rp
from score_external_one import prepare_one_file

ROOT = Path(__file__).resolve().parent
ART = ROOT / "artifacts_v2"
DEFAULT_FILE = Path(r"C:\Users\ZFGJ-WCH\Desktop\831-910\2097863420316155906.csv")
TRAIN_POS_CACHE = ART / "train_pos_rate.json"


def train_positive_rate() -> tuple[float, int]:
    if TRAIN_POS_CACHE.exists():
        d = json.loads(TRAIN_POS_CACHE.read_text(encoding="utf-8"))
        return float(d["pos_rate"]), int(d["train_n"])

    ds = ART / "dataset.csv"
    if ds.exists():
        df = pd.read_csv(ds, encoding="utf-8-sig", dtype={"商品ID": str})
        if "split" in df.columns:
            tr = df[df["split"] == "train"]
            if len(tr):
                p = float((tr["总销量"] > 0).mean())
                n = len(tr)
                TRAIN_POS_CACHE.write_text(
                    json.dumps(
                        {"pos_rate": p, "train_n": n, "source": "dataset.csv split=train"},
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                return p, n

    bundle = rp.make_split_bundle()
    tr = bundle["train"]
    p = float((tr["总销量"] > 0).mean())
    n = len(tr)
    TRAIN_POS_CACHE.write_text(
        json.dumps({"pos_rate": p, "train_n": n, "source": "make_split_bundle"},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return p, n


def stratified_n(
    df: pd.DataFrame, n: int, target_pos_rate: float, seed: int
) -> pd.DataFrame:
    pos = df[df["总销量"] > 0]
    neg = df[df["总销量"] == 0]
    p = float(np.clip(target_pos_rate, 0.0, 1.0))
    n_pos = int(round(n * p))
    n_pos = min(n_pos, len(pos))
    n_neg = min(n - n_pos, len(neg))
    if n_pos + n_neg < n and len(pos) > n_pos:
        n_pos = min(len(pos), n - n_neg)
    parts = []
    if n_pos:
        parts.append(pos.sample(n=n_pos, random_state=seed))
    if n_neg:
        parts.append(neg.sample(n=n_neg, random_state=seed))
    if not parts:
        return df.iloc[:0].copy()
    return (
        pd.concat(parts, ignore_index=True)
        .sample(frac=1, random_state=seed)
        .reset_index(drop=True)
    )


def image_urls_for_row(row: pd.Series) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []

    def add_from(val) -> None:
        for u in rp.parse_urls(val):
            if u and u not in seen:
                seen.add(u)
                urls.append(u)

    main = str(row.get("main_url") or "").strip()
    if "商品主图" in row.index:
        add_from(row.get("商品主图"))
    if "商品轮播图" in row.index:
        add_from(row.get("商品轮播图"))
    if main and main not in seen:
        urls.insert(0, main)
    elif main and main in seen:
        urls.remove(main)
        urls.insert(0, main)
    return urls[:32]


def enrich_payload_galleries(payload: dict, source: Path) -> dict:
    ids = {str(it["商品ID"]) for it in payload.get("items", [])}
    full = prepare_one_file(source)
    full = full[full["商品ID"].astype(str).isin(ids)]
    by_id = full.set_index("商品ID", drop=False)
    for it in payload["items"]:
        pid = str(it["商品ID"])
        if pid in by_id.index:
            row = by_id.loc[pid]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
            it["image_urls"] = image_urls_for_row(row)
            it["cat_l1"] = str(row.get("cat_l1", it.get("cat_l1", "")))
        elif not it.get("image_urls"):
            mu = str(it.get("main_url") or "")
            it["image_urls"] = [mu] if mu else []
    return payload


def build_html(payload: dict, out: Path) -> None:
    for it in payload.get("items", []):
        if not it.get("image_urls"):
            mu = str(it.get("main_url") or "")
            it["image_urls"] = [mu] if mu else []
        it["price_usd"] = float(it.get("美元价格($)", 0) or 0)
        it["cate_label"] = str(it.get("cat_l2") or it.get("cat_l1") or "—")
    data = json.dumps(payload, ensure_ascii=False)
    data = data.replace("</", "<\\/")
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>人工出单判定 — 500 条</title>
  <style>
    :root {{
      --bg:#f7f6f3; --card:#fff; --ink:#2f3437; --muted:#787774; --line:#eaeaea;
      --ok-bg:#edf3ec; --ok-ink:#346538; --no-bg:#fdebec; --no-ink:#9f2f2d;
      --price-bg:#e1f3fe; --price-ink:#1f6c9f; --cate-bg:#fbf3db; --cate-ink:#956400;
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:"SF Pro Display","PingFang SC","Microsoft YaHei",sans-serif;
      background:var(--bg); color:var(--ink); min-height:100vh; line-height:1.5; }}
    .shell {{ max-width:440px; margin:0 auto; min-height:100vh; padding:12px 12px 20px; }}
    .card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; overflow:hidden;
      box-shadow:0 1px 2px rgba(0,0,0,.04); }}
    .top {{ padding:10px 14px; font-size:13px; color:var(--muted); display:flex;
      justify-content:space-between; border-bottom:1px solid var(--line); }}
    .top strong {{ color:var(--ink); }}
    .hero {{ position:relative; background:#fafafa; min-height:min(48vh,360px); }}
    #hero-img-wrap {{ min-height:min(48vh,360px); display:flex; align-items:center; justify-content:center; }}
    .hero img {{ max-width:100%; max-height:min(48vh,360px); object-fit:contain; }}
    .hero .empty {{ color:var(--muted); padding:2rem; }}
    .car-btn {{ position:absolute; top:50%; transform:translateY(-50%); z-index:2;
      width:40px; height:40px; border:1px solid var(--line); border-radius:8px; background:#fff;
      font-size:20px; cursor:pointer; color:var(--ink); }}
    .car-prev {{ left:10px; }}
    .car-next {{ right:10px; }}
    .dots {{ text-align:center; font-size:12px; color:var(--muted); padding:8px 0 4px; }}
    .chips {{ display:flex; flex-wrap:wrap; gap:8px; padding:12px 14px 0; }}
    .chip {{ font-size:13px; font-weight:600; padding:6px 12px; border-radius:999px; letter-spacing:.02em; }}
    .chip.price {{ background:var(--price-bg); color:var(--price-ink); }}
    .chip.cate {{ background:var(--cate-bg); color:var(--cate-ink); max-width:100%;
      overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
    .title {{ padding:10px 14px 4px; font-size:15px; font-weight:600; line-height:1.45; margin:0; }}
    .meta-line {{ padding:0 14px 10px; font-size:12px; color:var(--muted); font-family:ui-monospace,monospace; }}
    .truth {{ margin:0 14px 12px; padding:10px 12px; background:#f9f9f8; border:1px solid var(--line);
      border-radius:8px; font-size:13px; }}
    .truth.hidden {{ visibility:hidden; height:0; margin:0; padding:0; border:none; overflow:hidden; }}
    .actions {{ display:flex; gap:10px; padding:0 14px 14px; }}
    .actions button {{ flex:1; border:1px solid var(--line); border-radius:8px; padding:14px 8px;
      font-size:15px; font-weight:600; cursor:pointer; font-family:inherit; transition:transform .12s; }}
    .actions button:active {{ transform:scale(.98); }}
    .actions .ok {{ background:var(--ok-bg); color:var(--ok-ink); }}
    .actions .ok.on {{ border-color:var(--ok-ink); box-shadow:inset 0 0 0 1px var(--ok-ink); }}
    .actions .no {{ background:var(--no-bg); color:var(--no-ink); }}
    .actions .no.on {{ border-color:var(--no-ink); box-shadow:inset 0 0 0 1px var(--no-ink); }}
    .accuracy {{ text-align:center; padding:14px; font-size:14px; border-top:1px solid var(--line); color:var(--muted); }}
    .accuracy strong {{ font-size:22px; color:var(--ink); font-weight:700; }}
    .tools {{ padding:10px 14px 14px; display:flex; flex-wrap:wrap; gap:6px; justify-content:center;
      border-top:1px solid var(--line); }}
    .tools button, .tools label {{ font-size:12px; border:1px solid var(--line); background:#fff;
      border-radius:6px; padding:6px 10px; cursor:pointer; color:var(--ink); }}
    input[type=number] {{ width:3.2rem; font-size:12px; border:1px solid var(--line); border-radius:4px; }}
  </style>
</head>
<body>
  <div class="shell">
    <div class="card">
      <div class="top">
        <span id="hdr-meta"></span>
        <span id="hdr-done"></span>
      </div>
      <div class="hero" id="hero">
        <button type="button" class="car-btn car-prev" id="car-prev" aria-label="上一张">‹</button>
        <div id="hero-img-wrap"></div>
        <button type="button" class="car-btn car-next" id="car-next" aria-label="下一张">›</button>
      </div>
      <div class="dots" id="car-dots"></div>
      <div class="chips">
        <span class="chip price" id="chip-price">—</span>
        <span class="chip cate" id="chip-cate">—</span>
      </div>
      <p class="title" id="line-title"></p>
      <p class="meta-line" id="line-idx"></p>
      <div class="truth hidden" id="line-truth"></div>
      <p class="meta-line" id="hint-top5" style="padding-top:0;margin-top:-4px;"></p>
      <div class="actions">
        <button type="button" class="ok" id="btn-ok">进 Top5%</button>
        <button type="button" class="no" id="btn-bad">不进 Top5%</button>
      </div>
      <div class="accuracy" id="acc-line">你的 Top5% 名单质量：<strong id="acc-val">—</strong></div>
      <div class="tools">
        <button type="button" id="btn-prev">上一条</button>
        <button type="button" id="btn-next">下一条</button>
        <button type="button" id="btn-next-unset">未判定</button>
        <label><input type="checkbox" id="hide-truth" /> 显示真实销量</label>
        <span>跳转 <input type="number" id="jump" min="1" /> <button type="button" id="btn-jump">Go</button></span>
        <button type="button" id="btn-export">导出 JSON</button>
      </div>
    </div>
  </div>
  <script type="application/json" id="payload">{data}</script>
  <script>
(function () {{
  const P = JSON.parse(document.getElementById("payload").textContent);
  const items = P.items;
  const meta = P.meta;
  const LS = "manual_audit_top5_" + meta.seed;
  const topK = (P.baseline && P.baseline.top_k) ? P.baseline.top_k : Math.max(1, Math.ceil(items.length * 0.05));
  const baseRate = meta.pos_rate_pool || 0;
  const oracleTop = new Set(
    [...items].sort((a, b) => b["总销量"] - a["总销量"]).slice(0, topK).map((x) => String(x["抽样序号"]))
  );
  let i = 0;
  let car = 0;
  let verdicts = JSON.parse(localStorage.getItem(LS) || "{{}}");
  const oldLs = localStorage.getItem("manual_audit_verdicts_" + meta.seed);
  if (oldLs && Object.keys(verdicts).length === 0) {{
    try {{ verdicts = JSON.parse(oldLs); localStorage.setItem(LS, oldLs); }} catch (e) {{}}
  }}
  const el = (id) => document.getElementById(id);

  function saveVerdicts() {{ localStorage.setItem(LS, JSON.stringify(verdicts)); }}

  function stats() {{
    let inTop = 0, outTop = 0, unset = 0;
    items.forEach((it) => {{
      const v = verdicts[String(it["抽样序号"])];
      if (v === "ok") inTop++;
      else if (v === "no") outTop++;
      else unset++;
    }});
    return {{ inTop, outTop, unset, done: inTop + outTop }};
  }}

  function poolQuality() {{
    const picks = items.filter((it) => verdicts[String(it["抽样序号"])] === "ok");
    const n = picks.length;
    if (!n) return {{ n: 0, hits: 0, pSold: null, overlapOracle: 0 }};
    const hits = picks.filter((it) => it["总销量"] > 0).length;
    const overlapOracle = picks.filter((it) => oracleTop.has(String(it["抽样序号"]))).length;
    return {{ n, hits, pSold: hits / n, overlapOracle }};
  }}

  function imgs(it) {{
    const list = it.image_urls && it.image_urls.length ? it.image_urls : (it.main_url ? [it.main_url] : []);
    return list.filter(Boolean);
  }}

  function renderCarousel(it) {{
    const list = imgs(it);
    car = Math.max(0, Math.min(car, list.length - 1));
    const wrap = el("hero-img-wrap");
    if (!list.length) {{
      wrap.innerHTML = '<div class="empty">无图片</div>';
      el("car-dots").textContent = "";
      el("car-prev").style.visibility = el("car-next").style.visibility = "hidden";
      return;
    }}
    const u = list[car].replace(/"/g, "%22");
    wrap.innerHTML = '<img src="' + u + '" alt="" referrerpolicy="no-referrer" />';
    el("car-dots").textContent = (car + 1) + " / " + list.length;
    const multi = list.length > 1;
    el("car-prev").style.visibility = el("car-next").style.visibility = multi ? "visible" : "hidden";
  }}

  function render() {{
    const it = items[i];
    const n = items.length;
    const seq = it["抽样序号"];
    car = 0;
    el("hdr-meta").textContent = (i + 1) + " / " + n;
    const st = stats();
    el("hdr-done").textContent = "已判 " + st.done + " · 进Top5% " + st.inTop + "（建议 " + topK + "）";
    el("hint-top5").textContent =
      "模型验收口径：排序后取前 " + topK + " 个（5%），看名单里有销量占比；不是给每条判「能否出单」。";

    const price = Number(it.price_usd ?? it["美元价格($)"] ?? 0);
    const cate = (it.cate_label || it.cat_l2 || it.cat_l1 || "—").toString();
    el("chip-price").textContent = "Price $" + price.toFixed(2);
    el("chip-cate").textContent = "Cate " + cate;
    renderCarousel(it);

    el("line-title").textContent = it["标题"];
    el("line-idx").textContent = "#" + seq + " · ID " + it["商品ID"];
    const pos = it["总销量"] > 0;
    const inOracle = oracleTop.has(String(seq));
    el("line-truth").textContent =
      "表内销量 " + it["总销量"] + (inOracle ? " · 属于表内真Top5%" : " · 非表内真Top5%");
    const showTruth = el("hide-truth").checked;
    el("line-truth").classList.toggle("hidden", !showTruth);

    const v = verdicts[String(seq)];
    el("btn-ok").classList.toggle("on", v === "ok");
    el("btn-bad").classList.toggle("on", v === "no");
    el("jump").value = i + 1;
    el("jump").max = n;

    const pq = poolQuality();
    const blind = !el("hide-truth").checked;
    if (blind || !pq.n) {{
      el("acc-val").textContent = blind ? "盲审中" : "请先标「进 Top5%」";
    }} else {{
      el("acc-val").textContent =
        "P(有销量) " + (pq.pSold * 100).toFixed(1) + "%（" + pq.hits + "/" + pq.n + "）" +
        " · 基线随机" + topK + "约 " + (baseRate * 100).toFixed(1) + "%" +
        " · 重合真Top5% " + pq.overlapOracle + "/" + topK;
    }}
  }}

  function setVerdict(kind, advance) {{
    const seq = String(items[i]["抽样序号"]);
    verdicts[seq] = kind;
    saveVerdicts();
    render();
    if (advance && i < items.length - 1) go(1);
  }}

  function go(delta) {{
    i = Math.max(0, Math.min(items.length - 1, i + delta));
    render();
  }}

  el("car-prev").onclick = () => {{ car--; renderCarousel(items[i]); }};
  el("car-next").onclick = () => {{ car++; renderCarousel(items[i]); }};

  el("btn-prev").onclick = () => go(-1);
  el("btn-next").onclick = () => go(1);
  el("btn-jump").onclick = () => {{
    const v = parseInt(el("jump").value, 10);
    if (v >= 1 && v <= items.length) {{ i = v - 1; render(); }}
  }};
  el("btn-ok").onclick = () => setVerdict("ok", true);
  el("btn-bad").onclick = () => setVerdict("no", true);
  el("btn-next-unset").onclick = () => {{
    for (let j = 1; j <= items.length; j++) {{
      const k = (i + j) % items.length;
      const s = String(items[k]["抽样序号"]);
      if (!verdicts[s]) {{ i = k; render(); return; }}
    }}
  }};
  el("hide-truth").onchange = () => render();
  el("btn-export").onclick = () => {{
    const rows = items.map((it) => {{
      const seq = it["抽样序号"];
      return {{
        抽样序号: seq,
        商品ID: it["商品ID"],
        人工判定: verdicts[String(seq)] === "ok" ? "进Top5%" : (verdicts[String(seq)] === "no" ? "不进Top5%" : null),
        总销量: it["总销量"],
        标题: it["标题"],
      }};
    }});
    const out = {{ meta, baseline: P.baseline, top_k: topK, stats: stats(), pool_quality: poolQuality(), verdicts, rows }};
    const blob = new Blob([JSON.stringify(out, null, 2)], {{ type: "application/json" }});
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "manual_verdicts_500.json";
    a.click();
  }};
  document.addEventListener("keydown", (e) => {{
    if (e.target.tagName === "INPUT") return;
    if (e.key === "ArrowLeft" && !e.shiftKey) go(-1);
    if (e.key === "ArrowRight" && !e.shiftKey) go(1);
    if (e.key === "ArrowLeft" && e.shiftKey) {{ car--; renderCarousel(items[i]); }}
    if (e.key === "ArrowRight" && e.shiftKey) {{ car++; renderCarousel(items[i]); }}
    if (e.key === "y" || e.key === "Y") setVerdict("ok", true);
    if (e.key === "n" || e.key === "N") setVerdict("no", true);
    if (e.key === "h" || e.key === "H") {{ el("hide-truth").checked = !el("hide-truth").checked; render(); }}
  }});
  el("hide-truth").checked = false;
  render();
}})();
  </script>
</body>
</html>"""
    out.write_text(html, encoding="utf-8")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE)
    parser.add_argument("-n", type=int, default=500)
    parser.add_argument("--seed", type=int, default=rp.SEED)
    parser.add_argument("--ref-seed", type=int, default=2026)
    parser.add_argument("--out-stem", type=str, default=None)
    parser.add_argument(
        "--from-json",
        type=Path,
        default=None,
        help="仅从已有 JSON 重新生成翻页 HTML",
    )
    args = parser.parse_args()

    if args.from_json:
        payload = json.loads(args.from_json.read_text(encoding="utf-8"))
        src = DEFAULT_FILE.parent / payload["meta"].get("file", DEFAULT_FILE.name)
        if not src.exists():
            src = DEFAULT_FILE
        payload = enrich_payload_galleries(payload, src)
        for it in payload["items"]:
            it["price_usd"] = float(it.get("美元价格($)", 0) or 0)
            it["cate_label"] = str(it.get("cat_l2") or it.get("cat_l1") or "—")
        args.from_json.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        out_html = args.from_json.with_suffix(".html")
        build_html(payload, out_html)
        print(f"[audit] JSON+HTML 已更新（含轮播图 URL）")
        print(f"[audit] HTML {out_html}")
        return

    stem = args.out_stem or f"manual_audit_{args.n}_trainpos_{args.file.stem[:12]}"
    out_json = ART / f"{stem}.json"
    out_html = ART / f"{stem}.html"

    t0 = time.perf_counter()
    print(f"[audit] 文件: {args.file.name}")
    full = prepare_one_file(args.file)
    pos_rate_file = float((full["总销量"] > 0).mean())
    train_pos_rate, train_n = train_positive_rate()
    print(f"[audit] train 正例率 {train_pos_rate:.1%} (n={train_n})")

    drawn = stratified_n(full, args.n, train_pos_rate, args.seed)
    pos_rate_pool = float((drawn["总销量"] > 0).mean())
    print(
        f"[audit] 分层 {len(drawn)} 条，目标 train {train_pos_rate:.1%}，"
        f"实际 {pos_rate_pool:.1%}（文件自然 {pos_rate_file:.1%}）"
    )

    sales = drawn["总销量"].to_numpy(dtype=float)
    n = len(drawn)
    k = max(1, int(math.ceil(n * 0.05)))

    rng = np.random.default_rng(args.ref_seed)
    ref_idx = rng.choice(n, size=k, replace=False)
    ref_hits = int((sales[ref_idx] > 0).sum())
    ref_ge5 = int((sales[ref_idx] >= 5).sum())

    items = []
    for i in range(n):
        row = drawn.iloc[i]
        items.append(
            {
                "抽样序号": i + 1,
                "商品ID": str(row["商品ID"]),
                "标题": str(row["标题"]),
                "美元价格($)": float(row["美元价格($)"]),
                "cat_l1": str(row.get("cat_l1", "")),
                "cat_l2": str(row.get("cat_l2", "")),
                "总销量": float(row["总销量"]),
                "有销量": bool(row["总销量"] > 0),
                "销量_ge5": bool(row["总销量"] >= 5),
                "main_url": str(row.get("main_url", "")),
                "image_urls": image_urls_for_row(row),
            }
        )

    payload = {
        "meta": {
            "file": args.file.name,
            "seed": args.seed,
            "n_pool": n,
            "pos_rate_file_cleaned": pos_rate_file,
            "pos_rate_target_train": train_pos_rate,
            "train_n": train_n,
            "pos_rate_pool": pos_rate_pool,
            "n_positive": int((sales > 0).sum()),
            "n_negative": int((sales <= 0).sum()),
            "elapsed_sec": round(time.perf_counter() - t0, 1),
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "note": "无模型打分；图片仅用 main_url 嵌入 HTML",
        },
        "baseline": {
            "description": "随机选 top_k 个 SKU，precision 期望 = 池内正例率（池按 train 正例率分层）",
            "top_k": k,
            "expected_prec_sale_gt0": pos_rate_pool,
            "expected_hits_sale_gt0": k * pos_rate_pool,
            "expected_prec_sale_ge5": float((sales >= 5).mean()),
            "expected_hits_sale_ge5": k * float((sales >= 5).mean()),
        },
        "reference_random_draw": {
            "seed": args.ref_seed,
            "top_k": k,
            "抽样序号": (ref_idx + 1).tolist(),
            "商品ID": [items[j]["商品ID"] for j in ref_idx],
            "prec_sale_gt0": ref_hits / k,
            "hits_sale_gt0": ref_hits,
            "prec_sale_ge5": ref_ge5 / k,
            "hits_sale_ge5": ref_ge5,
        },
        "items": items,
    }

    ART.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    build_html(payload, out_html)
    print(f"[audit] top_k={k} baseline P(>0)≈{pos_rate_pool:.3f}")
    print(f"[audit] JSON {out_json}")
    print(f"[audit] HTML {out_html}")


if __name__ == "__main__":
    main()
