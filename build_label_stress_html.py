# -*- coding: utf-8 -*-
"""从 external_*_labelp*.json 生成 label 正例率压力测试 HTML 汇总。"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ART = ROOT / "artifacts_v2"
FILE_STEM = "2097863420316155906"
LEVELS = (0, 10, 30, 50, 80, 100)


def load_rows() -> list[dict]:
    rows: list[dict] = []
    for p in LEVELS:
        path = ART / f"external_{FILE_STEM}_labelp{p}.json"
        if not path.exists():
            continue
        d = json.loads(path.read_text(encoding="utf-8"))
        d["_label_pos_pct"] = p
        rows.append(d)
    return rows


def pct(x: float | None, digits: int = 1) -> str:
    if x is None or (isinstance(x, float) and x != x):
        return "—"
    return f"{100 * x:.{digits}f}%"


def num(x: float | None, digits: int = 3) -> str:
    if x is None or (isinstance(x, float) and x != x):
        return "—"
    return f"{x:.{digits}f}"


def build_html(rows: list[dict]) -> str:
    ref_path = ART / f"external_{FILE_STEM}.json"
    ref = json.loads(ref_path.read_text(encoding="utf-8")) if ref_path.exists() else None
    gen = datetime.now().strftime("%Y-%m-%d %H:%M")

    def row_tr(d: dict, hl: bool = False) -> str:
        p = d.get("label_pos_pct", d.get("_label_pos_pct"))
        cls = ' class="hl"' if hl else ""
        lift = d["prec_sale_gt0"] / d["base_sale_gt0"] if d.get("base_sale_gt0", 0) > 0 else float("nan")
        return f"""<tr{cls}>
          <td><strong>{p}%</strong></td>
          <td>{d.get("rows_scored", d.get("n", "—"))}</td>
          <td>{pct(d.get("actual_pos_rate"))}</td>
          <td>{pct(d.get("prec_sale_gt0"))}</td>
          <td>{pct(d.get("base_sale_gt0"))}</td>
          <td>{num(lift, 2) if lift == lift else "—"}</td>
          <td>{pct(d.get("prec_sale_ge5"))}</td>
          <td>{num(d.get("pred_top5pct_mean"))}</td>
          <td>{num(d.get("spearman"), 2)}</td>
          <td>{d.get("elapsed_sec", "—")}s</td>
        </tr>"""

    body_rows = "\n".join(row_tr(d, hl=d.get("label_pos_pct") == 0) for d in rows)
    missing = [p for p in LEVELS if not (ART / f"external_{FILE_STEM}_labelp{p}.json").exists()]
    pending = (
        f'<p class="sub warn">待跑档位：{", ".join(f"labelp{p}" for p in missing)}</p>'
        if missing
        else '<p class="sub ok">全部档位 JSON 已齐。</p>'
    )

    ref_block = ""
    if ref:
        ref_block = f"""
    <section>
      <h2>对照：随机 2000 条（自然正例率 ~{pct(ref.get("base_sale_gt0"))}）</h2>
      <div class="grid">
        <div class="card"><div class="label">Top5% P(有销量)</div><div class="val good">{pct(ref["prec_sale_gt0"])}</div><p>基线 {pct(ref["base_sale_gt0"])}</p></div>
        <div class="card"><div class="label">Spearman</div><div class="val">{num(ref["spearman"], 2)}</div><p>n={ref.get("rows_scored")}</p></div>
      </div>
    </section>"""

    p0 = next((d for d in rows if d.get("label_pos_pct") == 0), None)
    alert = ""
    if p0:
        alert = f"""
    <div class="note warn-box">
      <strong>label 0% 压力结论：</strong>子集内<strong>无一单</strong>，但模型 top5% 平均预测仍约 <strong>{num(p0.get("pred_top5pct_mean"))}</strong>
      （全池预测均值 {num(p0.get("pred_mean"))}）。Top5% 的「有销量」精度为 <strong>0%</strong>——排序在纯负样本上<strong>虚高</strong>，需结合业务阈值或校准。
    </div>"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Label 正例率压力测试 — {FILE_STEM[:16]}</title>
  <style>
    :root {{ --bg:#f4f6f8; --card:#fff; --ink:#1a1a1a; --muted:#5a6270; --blue:#1d4ed8; --green:#047857;
      --amber:#b45309; --line:#e2e8f0; --warn-bg:#fffbeb; --warn-bd:#fcd34d; }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; font-family:"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; background:var(--bg);
      color:var(--ink); line-height:1.65; font-size:15px; }}
    .wrap {{ max-width: 960px; margin:0 auto; padding:1.75rem 1.25rem 2.5rem; }}
    h1 {{ font-size:1.5rem; margin:0 0 0.25rem; }}
    .sub {{ color:var(--muted); font-size:0.9rem; margin-bottom:1rem; }}
    .sub.warn {{ color:var(--amber); }}
    .sub.ok {{ color:var(--green); }}
    section {{ margin-bottom:1.5rem; }}
    section h2 {{ font-size:1.05rem; margin:0 0 0.6rem; padding-left:0.55rem; border-left:4px solid var(--blue); }}
    .grid {{ display:grid; gap:0.85rem; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); margin-bottom:1rem; }}
    .card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:1rem 1.1rem; }}
    .card .label {{ font-size:0.75rem; color:var(--muted); text-transform:uppercase; letter-spacing:0.04em; }}
    .card .val {{ font-size:1.5rem; font-weight:700; color:var(--blue); margin:0.2rem 0; }}
    .card .val.good {{ color:var(--green); }}
    .card p {{ margin:0; font-size:0.85rem; color:var(--muted); }}
    .note {{ background:#eff6ff; border:1px solid #bfdbfe; border-radius:10px; padding:0.85rem 1rem; font-size:0.9rem; margin-bottom:1rem; }}
    .warn-box {{ background:var(--warn-bg); border-color:var(--warn-bd); }}
    table {{ width:100%; border-collapse:collapse; background:var(--card); border-radius:12px; overflow:hidden;
      border:1px solid var(--line); font-size:0.84rem; }}
    th, td {{ padding:0.45rem 0.55rem; text-align:right; border-bottom:1px solid var(--line); }}
    th:first-child, td:first-child {{ text-align:left; }}
    th {{ background:#f8fafc; color:var(--muted); font-weight:600; }}
    tr.hl {{ background:#fef2f2; }}
    tr:last-child td {{ border-bottom:none; }}
    code {{ background:#f1f5f9; padding:0.1rem 0.35rem; border-radius:4px; font-size:0.85em; }}
    .foot {{ font-size:0.8rem; color:var(--muted); margin-top:1.5rem; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Label 正例率压力测试</h1>
    <p class="sub">
      文件 <code>{FILE_STEM}.csv</code> · 参数 <code>--pos-pct</code>（子集内「总销量&gt;0」占比）·
      0%=仅零销量 · 100%=仅有销量 · 中间档分层抽样 cap≤5000（seed 固定）·
      模型：909–911 训练 <strong>full</strong>（每次外测内存重训，与主实验一致）
    </p>
    {pending}
    {alert}
    {ref_block}
    <section>
      <h2>扫档汇总（top 5% 验收）</h2>
      <table>
        <thead>
          <tr>
            <th>目标正例率</th>
            <th>打分 n</th>
            <th>实际正例率</th>
            <th>P(有销量)</th>
            <th>基线</th>
            <th>lift</th>
            <th>P(≥5)</th>
            <th>top5% 预测均值</th>
            <th>Spearman</th>
            <th>耗时</th>
          </tr>
        </thead>
        <tbody>
{body_rows}
        </tbody>
      </table>
      <p class="foot">生成时间 {gen} · JSON：<code>external_{FILE_STEM}_labelp*.json</code> ·
      运行 <code>python build_label_stress_html.py</code> 可刷新本页</p>
    </section>
  </div>
</body>
</html>"""


def main() -> None:
    rows = load_rows()
    out = ART / "外测_label压力_2097863420.html"
    out.write_text(build_html(rows), encoding="utf-8")
    summary = {
        "file": f"{FILE_STEM}.csv",
        "levels": LEVELS,
        "completed": [d.get("label_pos_pct") for d in rows],
        "rows": rows,
    }
    (ART / f"external_{FILE_STEM}_label_stress_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[html] {len(rows)}/{len(LEVELS)} 档 -> {out}")


if __name__ == "__main__":
    main()
