"""从 artifacts_v2/temporal_metrics.json 生成时间外推验证 HTML。"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ART = ROOT / "artifacts_v2"
DEFAULT_METRICS = ART / "temporal_metrics.json"
DEFAULT_OUT = ART / "时间外推验证报告.html"


def pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def row_by_group(table: list[dict], group: str) -> dict:
    return next(r for r in table if r["group"] == group)


def build(data: dict) -> str:
    meta = data["meta"]
    ref = data["reference_shop_split_full"]
    main = data["main"]
    novel = data.get("novel_shops") or {}
    verdict = data["verdict"]
    grade = verdict["grade"]
    ratio = verdict["lift_gt0_ratio_vs_shop_split"]

    full = row_by_group(main["table"], "full")
    nf = row_by_group(novel["table"], "full") if novel.get("table") else None

    dedupe = meta["dedupe_removed"]
    dedupe_s = " · ".join(f"{k} {v}" for k, v in dedupe.items())

    grade_class = {"A": "grade-a", "B": "grade-b", "C": "grade-c"}[grade]
    grade_desc = {
        "A": "掉得不多（×基线 ≥ 现有 80%）→ 按天用站得住",
        "B": "明显下滑（50%–80%）→ 能用但需下调预期",
        "C": "基本失效（×基线接近 1.0）→ 不宜外推到新一天",
    }[grade]

    shop_gt0 = ref["prec_sale_gt0_lift_vs_base"]
    temp_gt0 = full["lift_gt0"]
    shop_ge5 = ref["prec_sale_ge5_lift_vs_base"]
    temp_ge5 = full["lift_ge5"]
    max_lift = max(shop_gt0, temp_gt0, shop_ge5, temp_ge5) * 1.05

    def bar_h(val: float) -> float:
        return max(4, 100 * val / max_lift)

    rows_main = []
    for r in main["table"]:
        g = r["group"]
        hl = " highlight" if g == "full" else ""
        sp = main["spearman"].get(g)
        sp_s = f"{sp:.3f}" if sp is not None else "—"
        lift5 = main["lift_at_5"].get(g, 0)
        rows_main.append(
            f"""          <tr class="{hl.strip()}">
            <td><strong>{g}</strong></td>
            <td>{pct(r['prec_gt0'])}</td>
            <td>{r['lift_gt0']:.2f}×</td>
            <td>{pct(r['prec_ge5'])}</td>
            <td>{r['lift_ge5']:.2f}×</td>
            <td>{pct(r['prec_ge20'])}</td>
            <td>{r['lift_ge20']:.2f}×</td>
            <td>{sp_s}</td>
            <td>{lift5:.3f}</td>
          </tr>"""
        )

    novel_block = ""
    if nf:
        novel_block = f"""
    <section>
      <h2>店铺未在 train 出现（新店铺子集）</h2>
      <div class="card">
        <p>行数 <strong>{novel['n_test']}</strong> · full P(&gt;0) ×基线 <strong>{nf['lift_gt0']:.2f}×</strong>（全 test {full['lift_gt0']:.2f}×）·
        P(≥5) ×基线 <strong>{nf['lift_ge5']:.2f}×</strong>（全 test {full['lift_ge5']:.2f}×）</p>
        <p>两数接近 → 时间外推下滑<strong>不主要</strong>来自「见过店铺」。</p>
      </div>
    </section>"""

    y_cap = meta["y_cap_p995_train"]
    train_label = " + ".join(meta.get("train_sources", []))
    test_label = meta.get("test_source", "911.csv")
    headline = f"{train_label} → {test_label}"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>时间外推验证 — {headline}</title>
  <style>
    :root {{
      --bg: #0f1419;
      --surface: #1a2332;
      --surface2: #243044;
      --ink: #e8edf4;
      --muted: #8b9cb3;
      --accent: #3b82f6;
      --accent2: #10b981;
      --warn: #f59e0b;
      --danger: #ef4444;
      --line: #2d3a4f;
      --radius: 14px;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      background: var(--bg);
      color: var(--ink);
      line-height: 1.6;
      font-size: 15px;
    }}
    .hero {{
      padding: 2.2rem 1.5rem 1.8rem;
      background: linear-gradient(135deg, #1e3a5f 0%, #0f1419 55%);
      border-bottom: 1px solid var(--line);
    }}
    .hero h1 {{ margin: 0 0 0.35rem; font-size: 1.65rem; font-weight: 700; }}
    .hero .lead {{ color: #b8c5d9; max-width: 54rem; margin: 0; font-size: 0.95rem; }}
    .verdict-pill {{
      display: inline-block;
      margin-top: 0.75rem;
      padding: 0.35rem 0.85rem;
      border-radius: 999px;
      font-weight: 700;
      font-size: 0.9rem;
      letter-spacing: 0.04em;
    }}
    .grade-a {{ background: rgba(16, 185, 129, 0.2); border: 1px solid var(--accent2); color: #6ee7b7; }}
    .grade-b {{ background: rgba(245, 158, 11, 0.15); border: 1px solid var(--warn); color: #fcd34d; }}
    .grade-c {{ background: rgba(239, 68, 68, 0.15); border: 1px solid var(--danger); color: #fca5a5; }}
    .wrap {{ max-width: 980px; margin: 0 auto; padding: 1.5rem 1.25rem 3rem; }}
    .grid {{
      display: grid;
      gap: 0.85rem;
      grid-template-columns: repeat(auto-fit, minmax(155px, 1fr));
      margin: 1.25rem 0;
    }}
    .kpi {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 1rem 1.1rem;
    }}
    .kpi .t {{ font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); }}
    .kpi .v {{ font-size: 1.75rem; font-weight: 700; margin: 0.15rem 0; color: var(--accent2); }}
    .kpi .v.warn {{ color: var(--warn); }}
    .kpi .v.blue {{ color: #60a5fa; }}
    .kpi .s {{ font-size: 0.8rem; color: var(--muted); margin: 0; }}
    section {{ margin-bottom: 2rem; }}
    section h2 {{
      font-size: 1.1rem;
      margin: 0 0 0.75rem;
      padding-left: 0.6rem;
      border-left: 4px solid var(--accent);
    }}
    .card {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 1rem 1.15rem;
      margin-bottom: 0.85rem;
    }}
    .card p {{ margin: 0.35rem 0; color: #c5d0e0; font-size: 0.92rem; }}
    .alert {{
      background: rgba(59, 130, 246, 0.1);
      border: 1px solid rgba(59, 130, 246, 0.35);
      border-radius: var(--radius);
      padding: 0.9rem 1rem;
      margin-bottom: 1rem;
      font-size: 0.9rem;
    }}
    .alert strong {{ color: #93c5fd; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.84rem;
      background: var(--surface);
      border-radius: var(--radius);
      overflow: hidden;
      border: 1px solid var(--line);
    }}
    th, td {{ padding: 0.5rem 0.6rem; text-align: right; border-bottom: 1px solid var(--line); }}
    th:first-child, td:first-child {{ text-align: left; }}
    th {{ background: var(--surface2); color: var(--muted); font-weight: 600; }}
    tr:last-child td {{ border-bottom: none; }}
    tr.highlight {{ background: rgba(59, 130, 246, 0.12); }}
    .chart-row {{ display: flex; align-items: flex-end; gap: 10px; height: 150px; margin: 1rem 0 0.5rem; }}
    .chart-col {{ flex: 1; display: flex; flex-direction: column; align-items: center; gap: 4px; }}
    .chart-bar {{
      width: 100%;
      max-width: 56px;
      border-radius: 6px 6px 2px 2px;
      min-height: 4px;
    }}
    .chart-bar.shop {{ background: linear-gradient(180deg, #94a3b8, #64748b); }}
    .chart-bar.temp {{ background: linear-gradient(180deg, #60a5fa, #2563eb); }}
    .chart-label {{ font-size: 0.68rem; color: var(--muted); text-align: center; line-height: 1.2; }}
    .chart-val {{ font-size: 0.72rem; color: #94a3b8; }}
    .legend {{ display: flex; gap: 1rem; font-size: 0.78rem; color: var(--muted); margin-bottom: 0.5rem; }}
    .dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 4px; vertical-align: middle; }}
    code {{ background: var(--surface2); padding: 0.12rem 0.4rem; border-radius: 4px; font-size: 0.85em; color: #93c5fd; }}
    .foot {{ font-size: 0.78rem; color: var(--muted); margin-top: 2rem; padding-top: 1rem; border-top: 1px solid var(--line); }}
    ul {{ margin: 0.4rem 0; padding-left: 1.2rem; color: #c5d0e0; font-size: 0.92rem; }}
    .delta {{ color: #f87171; font-size: 0.85rem; }}
  </style>
</head>
<body>
  <header class="hero">
    <h1>时间外推验证（{headline}）</h1>
    <p class="lead">
      用前两天训练、在第三天新品上测 Top 5% · 特征 <code>full</code>（表 + ResNet + BGE），<code>CAT_COLS</code> 仅 <code>cat_l2</code>（无 <code>source</code>）·
      脚本 <code>validate_temporal.py</code>
    </p>
    <span class="verdict-pill {grade_class}">结论 {grade} · 保留 {ratio:.0%}</span>
  </header>

  <div class="wrap">
    <div class="grid">
      <div class="kpi">
        <div class="t">full · P(&gt;0) ×基线</div>
        <div class="v warn">{temp_gt0:.2f}×</div>
        <p class="s">按店铺切分 {shop_gt0:.2f}×</p>
      </div>
      <div class="kpi">
        <div class="t">full · Top5% 有销量</div>
        <div class="v">{pct(full['prec_gt0'])}</div>
        <p class="s">{test_label} 基线 {pct(main['bases']['gt0'])}</p>
      </div>
      <div class="kpi">
        <div class="t">{test_label} test（清洗后）</div>
        <div class="v blue">{meta['n_test_after_dedupe']}</div>
        <p class="s">剔除 {dedupe_s}</p>
      </div>
      <div class="kpi">
        <div class="t">Spearman · lift@5</div>
        <div class="v blue">{main['spearman']['full']:.3f}</div>
        <p class="s">lift@5 {main['lift_at_5']['full']:.3f}</p>
      </div>
    </div>

    <div class="alert">
      <strong>铁律：</strong>{test_label} 动销基线（{pct(main['bases']['gt0'])}）与混合 test 不可直接比，<strong>禁止只看绝对 P(&gt;0)</strong>。
      主表每一档精度都要看 <strong>×基线</strong>。{meta.get('selection_bias_note', '')}
    </div>

    <section>
      <h2>设定摘要</h2>
      <div class="card">
        <p>train：909.xlsx + 910.csv · 拟合 {meta['n_train_fit']} · valid {meta['n_valid']}</p>
        <p>y = log1p(clip(销量, 0, {y_cap:.1f})) · seed {meta['seed']} · 耗时 {meta.get('elapsed_sec', 0):.0f}s</p>
      </div>
    </section>

    <section>
      <h2>{test_label} test 基线</h2>
      <table>
        <thead><tr><th>口径</th><th>全 test 比例</th></tr></thead>
        <tbody>
          <tr><td>有销量 (&gt;0)</td><td>{pct(main['bases']['gt0'])}</td></tr>
          <tr><td>≥ 5</td><td>{pct(main['bases']['ge5'])}</td></tr>
          <tr><td>≥ 20</td><td>{pct(main['bases']['ge20'])}</td></tr>
        </tbody>
      </table>
    </section>

    <section>
      <h2>主表 · Top 5%（含 ×基线）</h2>
      <table>
        <thead>
          <tr>
            <th>组别</th>
            <th>P(&gt;0)</th>
            <th>×基线</th>
            <th>P(≥5)</th>
            <th>×基线</th>
            <th>P(≥20)</th>
            <th>×基线</th>
            <th>Spearman</th>
            <th>lift@5</th>
          </tr>
        </thead>
        <tbody>
{chr(10).join(rows_main)}
        </tbody>
      </table>
    </section>

    <section>
      <h2>对比 · full：按店铺切分 vs 按天切分（看 ×基线）</h2>
      <div class="legend">
        <span><span class="dot" style="background:#64748b"></span>按店铺（现有）</span>
        <span><span class="dot" style="background:#2563eb"></span>按天（本次）</span>
      </div>
      <div class="chart-row">
        <div class="chart-col">
          <div class="chart-val">{shop_gt0:.2f}×</div>
          <div class="chart-bar shop" style="height:{bar_h(shop_gt0)}px"></div>
          <div class="chart-val">{temp_gt0:.2f}×</div>
          <div class="chart-bar temp" style="height:{bar_h(temp_gt0)}px"></div>
          <div class="chart-label">P(&gt;0)<br>×基线</div>
        </div>
        <div class="chart-col">
          <div class="chart-val">{shop_ge5:.2f}×</div>
          <div class="chart-bar shop" style="height:{bar_h(shop_ge5)}px"></div>
          <div class="chart-val">{temp_ge5:.2f}×</div>
          <div class="chart-bar temp" style="height:{bar_h(temp_ge5)}px"></div>
          <div class="chart-label">P(≥5)<br>×基线</div>
        </div>
        <div class="chart-col">
          <div class="chart-val">{ref['spearman']:.3f}</div>
          <div class="chart-bar shop" style="height:{bar_h(ref['spearman'])}px"></div>
          <div class="chart-val">{main['spearman']['full']:.3f}</div>
          <div class="chart-bar temp" style="height:{bar_h(main['spearman']['full'])}px"></div>
          <div class="chart-label">Spearman</div>
        </div>
        <div class="chart-col">
          <div class="chart-val">{ref['lift_at_5']:.3f}</div>
          <div class="chart-bar shop" style="height:{bar_h(ref['lift_at_5'])}px"></div>
          <div class="chart-val">{main['lift_at_5']['full']:.3f}</div>
          <div class="chart-bar temp" style="height:{bar_h(main['lift_at_5']['full'])}px"></div>
          <div class="chart-label">lift@5</div>
        </div>
      </div>
      <table>
        <thead>
          <tr><th>指标</th><th>按店铺切分</th><th>按天切分</th><th>变化</th></tr>
        </thead>
        <tbody>
          <tr>
            <td>P(&gt;0) ×基线</td>
            <td>{shop_gt0:.2f}</td>
            <td>{temp_gt0:.2f}</td>
            <td class="delta">{temp_gt0 - shop_gt0:+.2f}</td>
          </tr>
          <tr>
            <td>P(≥5) ×基线</td>
            <td>{shop_ge5:.2f}</td>
            <td>{temp_ge5:.2f}</td>
            <td class="delta">{temp_ge5 - shop_ge5:+.2f}</td>
          </tr>
          <tr>
            <td>Spearman</td>
            <td>{ref['spearman']:.4f}</td>
            <td>{main['spearman']['full']:.4f}</td>
            <td>{main['spearman']['full'] - ref['spearman']:+.4f}</td>
          </tr>
          <tr>
            <td>lift@5（截尾）</td>
            <td>{ref['lift_at_5']:.3f}</td>
            <td>{main['lift_at_5']['full']:.3f}</td>
            <td>{main['lift_at_5']['full'] - ref['lift_at_5']:+.3f}</td>
          </tr>
        </tbody>
      </table>
    </section>
{novel_block}

    <section>
      <h2>结论 · {grade}</h2>
      <div class="card">
        <p>{grade_desc}</p>
        <p>full P(&gt;0) ×基线 = <strong>{temp_gt0:.2f}×</strong>，为按店铺切分 {shop_gt0:.2f}× 的 <strong>{ratio:.0%}</strong>。</p>
      </div>
      <ul>
        <li>未改动 <code>rank_products.py</code>；指标来自缓存对齐样本。</li>
        <li>配套 Markdown：<code>temporal_validation.md</code> · JSON：<code>temporal_metrics.json</code></li>
      </ul>
    </section>

    <p class="foot">运行 <code>python build_temporal_validation_html.py</code> 可在重跑验证后刷新本页。</p>
  </div>
</body>
</html>
"""


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--metrics", type=Path, default=DEFAULT_METRICS)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    data = json.loads(args.metrics.read_text(encoding="utf-8"))
    args.out.write_text(build(data), encoding="utf-8")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
