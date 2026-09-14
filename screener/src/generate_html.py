# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG / "src"))

from render_html import is_flat_print_product, render, render_share, rows_from_df  # noqa: E402


def parse_args() -> argparse.Namespace:
    """读取 HTML 阶段参数；本阶段只接受模型已输出的 scored CSV。"""
    ap = argparse.ArgumentParser(description="从 *_scored.csv 生成筛选 HTML 和过滤后 Top CSV")
    ap.add_argument("--input", required=True, help="模型阶段输出的 *_scored.csv")
    ap.add_argument("--out-dir", default="", help="HTML/过滤 CSV 输出目录；默认跟随输入 CSV")
    ap.add_argument("--top-pct", type=float, default=5.0, help="分享页默认取模型排序前 N%%")
    ap.add_argument("--title", default="", help="页面标题；默认由文件名生成")
    ap.add_argument("--prefix", default="", help="输出文件前缀；默认由输入文件名去掉 _scored")
    return ap.parse_args()


def default_prefix(input_path: Path) -> str:
    """按日常命名规则生成输出前缀，例如 913_scored.csv -> 913。"""
    stem = input_path.stem
    if stem.endswith("_scored"):
        return stem[: -len("_scored")]
    return stem


def build_title(prefix: str, input_path: Path, custom_title: str) -> str:
    """生成 HTML 页面标题，保留手工标题覆盖能力。"""
    if custom_title:
        return custom_title
    return f"选品 Top5% · {prefix or input_path.name}"


def write_filtered_top(df: pd.DataFrame, rows: list[dict], top_pct: float, out_path: Path) -> int:
    """按分享页同一逻辑导出自动剔除违禁和 2D/平面类后的 Top CSV。"""
    ranked = sorted(rows, key=lambda r: -(r.get("score") or 0))
    if top_pct < 100:
        top_n = max(1, int(len(ranked) * top_pct / 100))
        ranked = ranked[:top_n]
    kept_ids = [
        str(r.get("id", ""))
        for r in ranked
        if not r.get("banned") and not is_flat_print_product(r)
    ]
    kept_set = set(kept_ids)
    out_df = df[df["商品ID"].astype(str).isin(kept_set)].copy()
    order = {pid: idx for idx, pid in enumerate(kept_ids)}
    out_df["_html_order"] = out_df["商品ID"].astype(str).map(order)
    out_df = out_df.sort_values("_html_order").drop(columns=["_html_order"])
    out_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    return len(out_df)


def main() -> None:
    """执行 HTML pipeline：scored CSV -> screener HTML、分享 HTML、过滤 Top CSV。"""
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else input_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    prefix = args.prefix or default_prefix(input_path)
    title = build_title(prefix, input_path, args.title)
    df = pd.read_csv(input_path, encoding="utf-8-sig", dtype={"商品ID": str})
    rows = rows_from_df(df)

    screener_path = out_dir / f"{prefix}_screener.html"
    share_path = out_dir / f"{prefix}_分享.html"
    filtered_path = out_dir / f"{prefix}_Top5pct_去违禁_去2D平面.csv"

    render(rows, title, screener_path)
    render_share(rows, title, share_path, top_pct=args.top_pct)
    kept_n = write_filtered_top(df, rows, args.top_pct, filtered_path)

    print(f"[html] 输入 CSV {input_path}")
    print(f"[html] 完整筛子 {screener_path}")
    print(f"[html] 人工筛选页 {share_path}")
    print(f"[html] 自动过滤 Top CSV {filtered_path} ({kept_n} 条)")


if __name__ == "__main__":
    main()
