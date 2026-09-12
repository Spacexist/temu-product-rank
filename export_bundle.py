# -*- coding: utf-8 -*-
"""一次性导出选品筛子 model/（勿改 artifacts_v2 指标文件）。"""
from __future__ import annotations

import json
import os
import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ART = ROOT / "artifacts_v2"
OUT = ROOT / "_screener_bundle" / "model"
# LightGBM 在含中文路径下 save_model 会失败，先写到 ASCII 临时目录
LGB_TMP = Path(r"F:\Clip\screener_lgb_export")
DESKTOP_OUT = Path(r"C:\Users\ZFGJ-WCH\Desktop\选品筛子\model")

sys.path.insert(0, str(ROOT))
import rank_products as rp  # noqa: E402


def cat_l2_te_mapping(train_fit, m: float = 20.0) -> dict:
    global_mean = float(train_fit["y"].mean())
    agg = train_fit.groupby("cat_l2", observed=True)["y"].agg(["mean", "count"])
    mapping: dict = {"_global": global_mean, "m": m}
    for cat, row in agg.iterrows():
        n = row["count"]
        mapping[str(cat)] = float((n * row["mean"] + m * global_mean) / (n + m))
    return mapping


def main() -> None:
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    pkl = ART / "lgbm_full.pkl"
    if not pkl.exists():
        raise SystemExit(f"缺少 {pkl}")

    OUT.mkdir(parents=True, exist_ok=True)
    LGB_TMP.mkdir(parents=True, exist_ok=True)
    with open(pkl, "rb") as f:
        model = pickle.load(f)

    bundle = rp.make_split_bundle()
    booster = model.booster_
    tmp_txt = LGB_TMP / "lgbm_full.txt"
    booster.save_model(str(tmp_txt))
    out_txt = OUT / "lgbm_full.txt"
    import shutil

    shutil.copy2(tmp_txt, out_txt)
    names = booster.feature_name()
    (OUT / "feature_names.json").write_text(
        json.dumps(names, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    te_map = cat_l2_te_mapping(bundle["train"])
    (OUT / "cat_l2_te.json").write_text(
        json.dumps(te_map, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    y_cap = float(bundle["y_cap_p995"])
    (OUT / "y_cap.json").write_text(
        json.dumps({"p995": y_cap}, indent=2), encoding="utf-8"
    )

    train_fit = bundle["train"]
    meta = {
        "exported_from": str(ART),
        "n_train_fit": int(len(train_fit)),
        "n_valid": int(len(bundle["valid"])),
        "n_test_shop_split": int(len(bundle["test"])),
        "y_cap_p995": y_cap,
        "CAT_COLS": list(rp.CAT_COLS),
        "NUM_TAB_COLS": list(rp.NUM_TAB_COLS),
        "inference_source_fixed": "911.csv",
        "forbidden_feature_cols": list(rp.LEAK_COLS)
        + ["店铺ID", "总销量", "y", "y_raw", "split", "shop_group"],
        "cat_l2_categories": sorted(train_fit["cat_l2"].astype(str).unique().tolist()),
        "source_categories": sorted(train_fit["source"].astype(str).unique().tolist()),
        "best_iteration": int(getattr(model, "best_iteration_", 0) or 0),
        "note": "导出时未在本进程 predict（Windows LGBM 偶发 access violation）；自测用 test_scores.npz 对齐",
    }
    (OUT / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    import shutil

    if DESKTOP_OUT.parent.exists() or True:
        try:
            DESKTOP_OUT.mkdir(parents=True, exist_ok=True)
            for name in (
                "lgbm_full.txt",
                "feature_names.json",
                "cat_l2_te.json",
                "y_cap.json",
                "meta.json",
            ):
                shutil.copy2(OUT / name, DESKTOP_OUT / name)
            print(f"[export] 已复制到 {DESKTOP_OUT}")
        except OSError as exc:
            print(f"[export] 复制到桌面目录失败 ({exc})，请手动复制 {OUT}")
    print(f"[export] 特征维数 {len(names)} · y_cap={y_cap:.1f}")
    print(f"[export] 写入 {out_txt}")


if __name__ == "__main__":
    main()
