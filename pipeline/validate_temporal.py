# -*- coding: utf-8 -*-
"""按天切分：909+910 训练 → 911 测新品（见 TASK_temporal_validation.md）。"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from scipy.stats import spearmanr
from sklearn.model_selection import GroupShuffleSplit

import rank_products as rp

ROOT = Path(__file__).resolve().parent
ART = ROOT / "artifacts_v2"
PRESETS = {
    "911": {
        "train": ("909.xlsx", "910.csv"),
        "test": "911.csv",
        "metrics": "temporal_metrics.json",
        "report": "temporal_validation.md",
        "title": "909+910 → 911",
        "y_cap_note": "909+910",
    },
    "913": {
        "train": ("909.xlsx", "910.csv", "911.csv", "912.csv"),
        "test": "913.csv",
        "metrics": "temporal_metrics_913.json",
        "report": "temporal_validation_913.md",
        "title": "909+910+911+912 → 913",
        "y_cap_note": "909–912",
    },
}
TRAIN_SOURCES = PRESETS["911"]["train"]
TEST_SOURCE = PRESETS["911"]["test"]
PRESET = PRESETS["911"]
CAT_COLS = ("cat_l2",)
GROUPS = ("random", "tab_only", "full")
REF_SHOP_FULL = {
    "prec_sale_gt0_lift_vs_base": 2.4947128525401214,
    "prec_sale_ge5_lift_vs_base": 3.8108409101293006,
    "prec_sale_ge20_lift_vs_base": 5.5037870706208665,
    "spearman": 0.3135,
    "lift_at_5": 1.981,
}


def load_aligned() -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    df = pd.read_csv(ART / "dataset.csv", encoding="utf-8-sig", dtype={"商品ID": str})
    img_p, txt_p = rp.npz_paths()
    with np.load(img_p, allow_pickle=True) as z_img:
        img_map = {str(i): v for i, v in zip(z_img["ids"], z_img["X"])}
    with np.load(txt_p, allow_pickle=True) as z_txt:
        txt_map = {str(i): v for i, v in zip(z_txt["ids"], z_txt["X"])}
    ok = df["商品ID"].isin(img_map) & df["商品ID"].isin(txt_map)
    df = df[ok].reset_index(drop=True)
    X_img = np.stack([img_map[i] for i in df["商品ID"]])
    X_txt = np.stack([txt_map[i] for i in df["商品ID"]])
    if "y_raw" not in df.columns:
        df["y_raw"] = df["总销量"].astype(float)
    return df, X_img, X_txt


def dedupe_test(
    train: pd.DataFrame,
    test: pd.DataFrame,
    X_img_tr: np.ndarray,
    X_img_te: np.ndarray,
    X_txt_te: np.ndarray,
) -> tuple[pd.DataFrame, np.ndarray, np.ndarray, dict]:
    stats: dict[str, int] = {}
    keep = np.ones(len(test), dtype=bool)

    train_ids = set(train["商品ID"].astype(str))
    m0 = test["商品ID"].astype(str).isin(train_ids).to_numpy()
    stats["商品ID"] = int(m0.sum())
    keep &= ~m0

    t_urls = set(train["main_url"].astype(str))
    m1 = test["main_url"].astype(str).isin(t_urls).to_numpy()
    stats["main_url"] = int((keep & m1).sum())
    keep &= ~m1

    t_titles = set(train["标题"].astype(str).str.strip())
    m2 = test["标题"].astype(str).str.strip().isin(t_titles).to_numpy()
    stats["title"] = int((keep & m2).sum())
    keep &= ~m2

    if len(test) and len(train):
        block = 256
        drop = np.zeros(len(test), dtype=bool)
        for i in range(0, len(test), block):
            sim = X_img_te[i : i + block] @ X_img_tr.T
            drop[i : i + block] = sim.max(axis=1) > 0.98
        stats["image_cosine"] = int((keep & drop).sum())
        keep &= ~drop
    else:
        stats["image_cosine"] = 0

    test = test[keep].copy().reset_index(drop=True)
    return test, X_img_te[keep], X_txt_te[keep], stats


def winsorize_frames(train: pd.DataFrame, test: pd.DataFrame, cap: float) -> None:
    for frame in (train, test):
        frame["y"] = np.log1p(np.clip(frame["y_raw"].astype(float), 0, cap))


def shop_groups(df: pd.DataFrame) -> np.ndarray:
    if "店铺ID" in df.columns:
        return df["店铺ID"].astype(str).to_numpy()
    return df["shop_group"].astype(str).to_numpy()


def build_tab(frame: pd.DataFrame) -> pd.DataFrame:
    tab = frame[list(rp.NUM_TAB_COLS)].copy()
    tab["cat_l2"] = frame["cat_l2"].astype(str).astype("category")
    return tab


def feature_mats(
    train: pd.DataFrame,
    valid: pd.DataFrame,
    test: pd.DataFrame,
    X_img_tr: np.ndarray,
    X_img_va: np.ndarray,
    X_img_te: np.ndarray,
    X_txt_tr: np.ndarray,
    X_txt_va: np.ndarray,
    X_txt_te: np.ndarray,
    name: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if name == "tab_only":
        return build_tab(train), build_tab(valid), build_tab(test)
    if name == "full":
        return (
            rp.concat_features(build_tab(train), X_img_tr, X_txt_tr, None),
            rp.concat_features(build_tab(valid), X_img_va, X_txt_va, None),
            rp.concat_features(build_tab(test), X_img_te, X_txt_te, None),
        )
    raise ValueError(name)


def fit_lgbm_safe(X_tr: pd.DataFrame, y_tr, X_va: pd.DataFrame, y_va):
    cat_features = [c for c in X_tr.columns if c in CAT_COLS]
    y_tr = np.asarray(y_tr, dtype=np.float64)
    y_va = np.asarray(y_va, dtype=np.float64)
    last_err: Exception | None = None
    for attempt in range(1, 4):
        try:
            model = LGBMRegressor(**rp.LGB_PARAMS, n_jobs=1)
            model.fit(
                X_tr,
                y_tr,
                eval_set=[(X_va, y_va)],
                categorical_feature=cat_features if cat_features else "auto",
                callbacks=[lgb.early_stopping(100, verbose=False)],
            )
            return model
        except OSError as e:
            last_err = e
            time.sleep(2.0 * attempt)
    raise RuntimeError(f"LightGBM fit failed: {last_err}")


def categorize(parts: tuple[pd.DataFrame, ...]) -> tuple[pd.DataFrame, ...]:
    out = []
    for part in parts:
        p = part.copy()
        if "cat_l2" in p.columns:
            p["cat_l2"] = p["cat_l2"].astype(str).astype("category")
        out.append(p)
    return tuple(out)


def eval_top5_and_slate(
    sales: np.ndarray,
    sources: np.ndarray,
    preds: dict[str, np.ndarray],
    y_cap: float,
    repeats: int = 3000,
    k: int = 20,
) -> dict:
    sales_w = np.clip(sales.astype(float), 0, y_cap)
    top5 = {}
    for name, pred in preds.items():
        top5[name] = rp.top5pct_row(sales, pred)

    slates = rp.make_slates(sources, k, repeats, np.random.default_rng(rp.SEED + k))
    rnd_rng = np.random.default_rng(rp.SEED + 1)
    slate_lift = {}
    for name, pred in preds.items():
        raw = rp.per_slate_metrics(
            sales_w, slates, None if name == "random" else pred, rnd_rng
        )
        slate_lift[name] = rp.aggregate_slate_metrics(raw)["lift@5"]

    spearman = {}
    for name, pred in preds.items():
        if name == "random":
            continue
        sp, _ = spearmanr(pred, sales)
        spearman[name] = float(sp)

    return {"top5pct": top5, "lift_at_5": slate_lift, "spearman": spearman}


def format_top5_table(top5: dict[str, dict], groups: tuple[str, ...]) -> list[dict]:
    rows = []
    for g in groups:
        r = top5[g]
        rows.append(
            {
                "group": g,
                "n": r["n"],
                "top_k": r["top_k"],
                "prec_gt0": r["prec_sale_gt0"],
                "lift_gt0": r["prec_sale_gt0_lift_vs_base"],
                "prec_ge5": r["prec_sale_ge5"],
                "lift_ge5": r["prec_sale_ge5_lift_vs_base"],
                "prec_ge20": r["prec_sale_ge20"],
                "lift_ge20": r["prec_sale_ge20_lift_vs_base"],
                "base_gt0": r["base_sale_gt0"],
                "base_ge5": r["base_sale_ge5"],
                "base_ge20": r["base_sale_ge20"],
            }
        )
    return rows


def verdict(full_lift_gt0: float, ref: dict | None = None) -> str:
    ref = ref or REF_SHOP_FULL
    ratio = full_lift_gt0 / ref["prec_sale_gt0_lift_vs_base"]
    if ratio >= 0.8:
        return "A", ratio
    if ratio >= 0.5:
        return "B", ratio
    return "C", ratio


def run_subset(
    train_fit: pd.DataFrame,
    valid: pd.DataFrame,
    test: pd.DataFrame,
    mats: dict,
    y_cap: float,
    label: str,
) -> dict:
    sales = test["总销量"].to_numpy(dtype=float)
    sources = test["source"].astype(str).to_numpy()
    preds: dict[str, np.ndarray] = {
        "random": np.random.default_rng(rp.SEED + 99).random(len(test)),
    }
    for name in ("tab_only", "full"):
        X_tr, X_va, X_te = mats[name]
        model = fit_lgbm_safe(X_tr, train_fit["y"], X_va, valid["y"])
        preds[name] = model.predict(X_te)

    ev = eval_top5_and_slate(sales, sources, preds, y_cap)
    return {
        "label": label,
        "n_test": len(test),
        "bases": {
            "gt0": float((sales > 0).mean()),
            "ge5": float((sales >= 5).mean()),
            "ge20": float((sales >= 20).mean()),
        },
        "table": format_top5_table(ev["top5pct"], GROUPS),
        "lift_at_5": ev["lift_at_5"],
        "spearman": ev["spearman"],
    }


def load_ref_shop_full() -> dict:
    """当前 artifacts 按店铺切分 full 的 Top5% ×基线（重训后自动更新对照）。"""
    p = ART / "top5pct_metrics.json"
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            base = data["base_rates"]
            full = next(r for r in data["top5pct"] if r["group"] == "full")
            b0, b5, b20 = base["sale_gt0"], base["sale_ge5"], base["sale_ge20"]
            return {
                "prec_sale_gt0_lift_vs_base": float(full["prec_sale_gt0"] / b0),
                "prec_sale_ge5_lift_vs_base": float(full["prec_sale_ge5"] / b5),
                "prec_sale_ge20_lift_vs_base": float(full["prec_sale_ge20"] / b20),
                "spearman": float(data.get("spearman_full", REF_SHOP_FULL["spearman"])),
                "lift_at_5": float(REF_SHOP_FULL["lift_at_5"]),
            }
        except (json.JSONDecodeError, KeyError, TypeError, StopIteration):
            pass
    return dict(REF_SHOP_FULL)


def main() -> None:
    global TRAIN_SOURCES, TEST_SOURCE, PRESET
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--preset",
        choices=tuple(PRESETS.keys()),
        default="911",
        help="913 = 加入912训练后外推913",
    )
    args = ap.parse_args()
    PRESET = PRESETS[args.preset]
    TRAIN_SOURCES = PRESET["train"]
    TEST_SOURCE = PRESET["test"]
    ref_shop = load_ref_shop_full()

    t0 = time.perf_counter()
    df, X_img, X_txt = load_aligned()
    print(f"[temporal] 对齐样本 {len(df)} 行")

    tr_mask = df["source"].isin(TRAIN_SOURCES)
    te_mask = df["source"] == TEST_SOURCE
    train_all = df[tr_mask].copy().reset_index(drop=True)
    test_all = df[te_mask].copy().reset_index(drop=True)
    X_img_tr_all = X_img[tr_mask.to_numpy()]
    X_txt_tr_all = X_txt[tr_mask.to_numpy()]
    X_img_te = X_img[te_mask.to_numpy()]
    X_txt_te = X_txt[te_mask.to_numpy()]

    print(f"[temporal] train({PRESET['title']}) {len(train_all)} · test({TEST_SOURCE}) {len(test_all)}")

    test_clean, X_img_te, X_txt_te, dedupe = dedupe_test(
        train_all, test_all, X_img_tr_all, X_img_te, X_txt_te
    )
    print(f"[temporal] test 去重剔除: {dedupe}")

    y_cap = float(np.percentile(train_all["y_raw"].astype(float), 99.5))
    print(f"[temporal] y winsorize p99.5 (train {PRESET['y_cap_note']}) = {y_cap:.1f}")

    winsorize_frames(train_all, test_clean, y_cap)

    gss = GroupShuffleSplit(n_splits=1, test_size=0.1, random_state=rp.SEED)
    groups = shop_groups(train_all)
    tr_idx, va_idx = next(gss.split(train_all, groups=groups))
    train_fit = train_all.iloc[tr_idx].reset_index(drop=True)
    valid = train_all.iloc[va_idx].reset_index(drop=True)
    X_img_tr = X_img_tr_all[tr_idx]
    X_txt_tr = X_txt_tr_all[tr_idx]
    X_img_va = X_img_tr_all[va_idx]
    X_txt_va = X_txt_tr_all[va_idx]

    train_fit["cat_l2_te"] = rp.cat_l2_target_encode(train_fit, train_fit)
    valid["cat_l2_te"] = rp.cat_l2_target_encode(train_fit, valid)
    test_clean["cat_l2_te"] = rp.cat_l2_target_encode(train_fit, test_clean)

    mats = {}
    for name in ("tab_only", "full"):
        mats[name] = categorize(
            feature_mats(
                train_fit,
                valid,
                test_clean,
                X_img_tr,
                X_img_va,
                X_img_te,
                X_txt_tr,
                X_txt_va,
                X_txt_te,
                name,
            )
        )

    print("[temporal] 拟合 tab_only / full …")
    main_res = run_subset(train_fit, valid, test_clean, mats, y_cap, "all_test")

    train_shops = set(train_all["店铺ID"].astype(str)) if "店铺ID" in train_all.columns else set(
        train_all["shop_group"].astype(str)
    )
    shop_col = "店铺ID" if "店铺ID" in test_clean.columns else "shop_group"
    novel_mask = ~test_clean[shop_col].astype(str).isin(train_shops)
    novel_n = int(novel_mask.sum())
    print(f"[temporal] 店铺未在 train 出现: {novel_n} / {len(test_clean)}")

    if novel_n >= 50:
        test_novel = test_clean[novel_mask].reset_index(drop=True)
        X_img_n = X_img_te[novel_mask.to_numpy()]
        X_txt_n = X_txt_te[novel_mask.to_numpy()]
        test_novel["cat_l2_te"] = rp.cat_l2_target_encode(train_fit, test_novel)
        mats_n = {}
        for name in ("tab_only", "full"):
            mats_n[name] = categorize(
                feature_mats(
                    train_fit,
                    valid,
                    test_novel,
                    X_img_tr,
                    X_img_va,
                    X_img_n,
                    X_txt_tr,
                    X_txt_va,
                    X_txt_n,
                    name,
                )
            )
        novel_res = run_subset(train_fit, valid, test_novel, mats_n, y_cap, "novel_shops_only")
    else:
        novel_res = {"label": "novel_shops_only", "n_test": novel_n, "skipped": True}

    full_row = next(r for r in main_res["table"] if r["group"] == "full")
    grade, ratio = verdict(full_row["lift_gt0"], ref_shop)

    out = {
        "meta": {
            "preset": args.preset,
            "train_sources": list(TRAIN_SOURCES),
            "test_source": TEST_SOURCE,
            "n_aligned": len(df),
            "n_train_all": len(train_all),
            "n_test_raw": len(test_all),
            "n_test_911_raw": len(test_all),
            "n_test_after_dedupe": len(test_clean),
            "dedupe_removed": dedupe,
            "y_cap_p995_train": y_cap,
            "n_train_fit": len(train_fit),
            "n_valid": len(valid),
            "cat_cols": list(CAT_COLS),
            "seed": rp.SEED,
            "elapsed_sec": round(time.perf_counter() - t0, 1),
            "selection_bias_note": "主图未进缓存的 SKU 不在本次样本内，指标偏保守",
        },
        "reference_shop_split_full": ref_shop,
        "main": main_res,
        "novel_shops": novel_res,
        "verdict": {"grade": grade, "lift_gt0_ratio_vs_shop_split": ratio},
    }

    out_path = ART / PRESET["metrics"]
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(out, PRESET)
    print(f"[temporal] 结论 {grade} (×基线保留比 {ratio:.1%})")
    print(f"[temporal] 写入 {out_path}")


def write_report(data: dict, preset: dict) -> None:
    main = data["main"]
    bases = main["bases"]
    full = next(r for r in main["table"] if r["group"] == "full")
    ref = data["reference_shop_split_full"]
    grade = data["verdict"]["grade"]
    ratio = data["verdict"]["lift_gt0_ratio_vs_shop_split"]

    def pct(x: float) -> str:
        return f"{100 * x:.1f}%"

    lines = [
        f"# 时间外推验证（{preset['title']}）",
        "",
        f"供 Opus 审核。脚本：`validate_temporal.py --preset {data['meta'].get('preset', '911')}` · 指标：`{preset['metrics']}`",
        "",
        "## 设定",
        "",
        f"- train：`{'` + `'.join(preset['train'])}`（拟合 {data['meta']['n_train_fit']}，valid {data['meta']['n_valid']}）",
        f"- test：`{preset['test']}` 清洗后 **{data['meta']['n_test_after_dedupe']}** 行（去重剔除 {data['meta']['dedupe_removed']}）",
        f"- 特征：full = 表 + ResNet + BGE，**`CAT_COLS` 仅 `cat_l2`（无 `source`）**",
        f"- y：`log1p(clip(销量, 0, {data['meta']['y_cap_p995_train']:.1f}))`，p99.5 仅在 {preset['y_cap_note']} train 上算",
        f"- {data['meta']['selection_bias_note']}",
        "",
        f"### {preset['test']} test 基线（必看）",
        "",
        f"| 基线 | 比例 |",
        f"|------|------|",
        f"| P(有销量) | {pct(bases['gt0'])} |",
        f"| P(≥5) | {pct(bases['ge5'])} |",
        f"| P(≥20) | {pct(bases['ge20'])} |",
        "",
        "## 主表（Top 5%，含 ×基线）",
        "",
        "| 组别 | P(>0) | ×基线 | P(≥5) | ×基线 | P(≥20) | ×基线 | Spearman | lift@5 |",
        "|------|------:|------:|------:|------:|------:|------:|---------:|-------:|",
    ]
    for row in main["table"]:
        g = row["group"]
        sp = main["spearman"].get(g, float("nan"))
        sp_s = f"{sp:.3f}" if g != "random" else "—"
        lift5 = main["lift_at_5"].get(g, float("nan"))
        lines.append(
            f"| {g} | {pct(row['prec_gt0'])} | {row['lift_gt0']:.2f} | "
            f"{pct(row['prec_ge5'])} | {row['lift_ge5']:.2f} | "
            f"{pct(row['prec_ge20'])} | {row['lift_ge20']:.2f} | {sp_s} | {lift5:.3f} |"
        )

    lines += [
        "",
        "## 对比：按天 vs 按店铺切分（full，看 ×基线）",
        "",
        "| 指标 | 按店铺切分（现有） | 按天切分（本次） | 变化 |",
        "|------|------------------:|-----------------:|-----:|",
        f"| P(>0) ×基线 | {ref['prec_sale_gt0_lift_vs_base']:.2f} | {full['lift_gt0']:.2f} | {full['lift_gt0'] - ref['prec_sale_gt0_lift_vs_base']:+.2f} |",
        f"| P(≥5) ×基线 | {ref['prec_sale_ge5_lift_vs_base']:.2f} | {full['lift_ge5']:.2f} | {full['lift_ge5'] - ref['prec_sale_ge5_lift_vs_base']:+.2f} |",
        f"| Spearman | {ref['spearman']:.4f} | {main['spearman'].get('full', float('nan')):.4f} | — |",
        f"| lift@5 (截尾) | {ref['lift_at_5']:.3f} | {main['lift_at_5'].get('full', float('nan')):.3f} | — |",
        "",
    ]

    novel = data.get("novel_shops") or {}
    if novel.get("skipped"):
        lines.append("## 店铺未重叠子集\n\n样本过少，未单独评估。\n")
    else:
        nf = next(r for r in novel["table"] if r["group"] == "full")
        lines += [
            "## 店铺未重叠子集",
            "",
            f"行数：**{novel['n_test']}**（train 未出现过的店铺）",
            "",
            f"- full P(>0) ×基线：**{nf['lift_gt0']:.2f}**（全 test {full['lift_gt0']:.2f}）",
            f"- full P(≥5) ×基线：**{nf['lift_ge5']:.2f}**（全 test {full['lift_ge5']:.2f}）",
            "",
        ]

    grade_text = {
        "A": "掉得不多（×基线 ≥ 现有 80%）→ 按天用站得住",
        "B": "明显下滑（50%–80%）→ 能用但需下调预期",
        "C": "基本失效（×基线 接近 1.0）→ 不宜外推到新一天",
    }
    n_test = data["main"]["n_test"]
    lines += [
        f"## 结论：**{grade}**",
        "",
        grade_text[grade],
        "",
        f"- full P(>0) ×基线 = **{full['lift_gt0']:.2f}**，为按店铺切分 {ref['prec_sale_gt0_lift_vs_base']:.2f} 的 **{ratio:.0%}**",
        "",
        "## 审核提示",
        "",
        f"- {preset['test']} 动销基线与混合 test 不可直接比，**禁止只看绝对 P(>0)**。",
        f"- test 清洗后 **{n_test}** 行。",
        "- 主图未进缓存的 SKU 不在对齐样本内。",
        "",
    ]
    (ART / preset["report"]).write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
