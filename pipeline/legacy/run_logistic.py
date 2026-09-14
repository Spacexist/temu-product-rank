# -*- coding: utf-8 -*-
"""在已有划分和特征缓存上跑 Logistic，不再下图、不重抽特征。"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parent
ART = ROOT / "hit_cache" / "artifacts"


def load_npz(path: Path, ids: list[str]) -> np.ndarray:
    z = np.load(path, allow_pickle=True)
    cached = [str(x) for x in z["ids"].tolist()]
    if cached != [str(x) for x in ids]:
        index = {k: i for i, k in enumerate(cached)}
        miss = [i for i in ids if str(i) not in index]
        if miss:
            raise SystemExit(f"{path.name} 对不上商品ID，缺 {len(miss)} 条")
        return z["X"][[index[str(i)] for i in ids]].astype(np.float32)
    return z["X"].astype(np.float32)


def tab_features(train: pd.DataFrame, test: pd.DataFrame):
    cats = sorted(train["category"].unique().tolist())
    cat_index = {c: i for i, c in enumerate(cats)}

    def onehot(frame):
        m = np.zeros((len(frame), len(cats)), dtype=np.float32)
        for i, c in enumerate(frame["category"].tolist()):
            j = cat_index.get(c)
            if j is not None:
                m[i, j] = 1.0
        price = frame["log_price"].to_numpy(dtype=np.float32)[:, None]
        video = frame["has_video"].to_numpy(dtype=np.float32)[:, None]
        return np.concatenate([m, price, video], axis=1)

    return onehot(train), onehot(test)


def fit_eval(name: str, Xtr, ytr, Xte, yte) -> dict:
    clf = Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "lr",
                LogisticRegression(
                    class_weight="balanced",
                    C=0.3,
                    solver="lbfgs",
                    max_iter=2000,
                    random_state=42,
                ),
            ),
        ]
    )
    clf.fit(Xtr, ytr)
    tr_p = clf.predict_proba(Xtr)[:, 1]
    te_p = clf.predict_proba(Xte)[:, 1]
    row = {
        "name": name,
        "model": "logistic",
        "train_auc": float(roc_auc_score(ytr, tr_p)),
        "train_prauc": float(average_precision_score(ytr, tr_p)),
        "test_auc": float(roc_auc_score(yte, te_p)),
        "test_prauc": float(average_precision_score(yte, te_p)),
        "test_pos_rate": float(yte.mean()),
        "train_n": int(len(ytr)),
        "train_pos": int(ytr.sum()),
        "test_n": int(len(yte)),
        "test_pos": int(yte.sum()),
    }
    print(
        f"{name:12s}  train AUC={row['train_auc']:.4f}  "
        f"test AUC={row['test_auc']:.4f}  PR-AUC={row['test_prauc']:.4f}"
    )
    return row


def main():
    train = pd.read_csv(ART / "train.csv")
    test = pd.read_csv(ART / "test.csv")
    ytr = train["label"].to_numpy()
    yte = test["label"].to_numpy()
    ids_tr = train["商品ID"].astype(str).tolist()
    ids_te = test["商品ID"].astype(str).tolist()
    img_tr = load_npz(ART / "img_train.npz", ids_tr)
    img_te = load_npz(ART / "img_test.npz", ids_te)

    def text_ok(path, n, dim=512):
        p = ART / path
        if not p.exists():
            return False
        z = np.load(p, allow_pickle=True)
        return z["X"].shape == (n, dim)

    if not text_ok("txt_train.npz", len(train)) or not text_ok("txt_test.npz", len(test)):
        from run_hit_experiment import text_features_for_df

        print("标题特征维数不一致或缺失，用本地 OpenCLIP 重抽…")
        txt_tr = text_features_for_df(train, "txt_train.npz")
        txt_te = text_features_for_df(test, "txt_test.npz")
    else:
        txt_tr = load_npz(ART / "txt_train.npz", ids_tr)
        txt_te = load_npz(ART / "txt_test.npz", ids_te)
    tab_tr, tab_te = tab_features(train, test)
    print(
        f"train={len(train)} pos={int(ytr.sum())} | "
        f"test={len(test)} pos={int(yte.sum())} pos_rate={yte.mean():.3f}"
    )
    print("==== Logistic ====")
    results = [
        fit_eval("title_only", txt_tr, ytr, txt_te, yte),
        fit_eval("image_only", img_tr, ytr, img_te, yte),
        fit_eval(
            "joint",
            np.concatenate([img_tr, txt_tr, tab_tr], axis=1),
            ytr,
            np.concatenate([img_te, txt_te, tab_te], axis=1),
            yte,
        ),
    ]
    out = {
        "note": "同一划分；StandardScaler + Logistic(class_weight=balanced, C=0.3)",
        "results": results,
    }
    (ART / "metrics_logistic.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("已写入", ART / "metrics_logistic.json")


if __name__ == "__main__":
    main()
