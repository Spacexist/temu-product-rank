# -*- coding: utf-8 -*-
"""厨房收纳日更：清洗 → 统计 → 按店铺切分训练 → 预测 → HTML。

不写 D:\\temu_rank_npz，不碰 datta 主模型。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from hashlib import md5
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PIPE = ROOT / "pipeline"
SCREENER = ROOT / "screener"
INBOX = ROOT / "inbox"
RAW = ROOT / "data" / "raw"
CLEANED = ROOT / "data" / "cleaned"
PUBLISHED = ROOT / "data" / "published"
DATA_CACHE = ROOT / "data_cache"
ART = ROOT / "artifacts"
OUTPUT = ROOT / "output"
CACHE_JSON = ROOT / "cache.json"
IMG_DIR = Path(r"D:\temu_images")
WORDS = ROOT / "words" / "banned.txt"
PY = Path(r"F:\Clip\venv\Scripts\python.exe")
ASCII_ROOT = Path(r"C:\Users\ZFGJ-WCH\AppData\Local\kitchen_rank")
TABLE_SUFFIXES = {".csv", ".xlsx", ".xls"}


def py_bin() -> str:
    """优先 F:\\Clip\\venv。"""
    return str(PY) if PY.is_file() else sys.executable


def day_id(path: Path, now: datetime | None = None) -> str:
    """从 918.csv / 20260918.csv 解析 YYYY-MM-DD。"""
    now = now or datetime.now()
    stem = path.stem
    if stem.isdigit() and len(stem) == 8:
        return f"{stem[:4]}-{stem[4:6]}-{stem[6:]}"
    if stem.isdigit() and len(stem) == 4:
        return f"{now.year}-{stem[:2]}-{stem[2:]}"
    if stem.isdigit() and len(stem) == 3:
        return f"{now.year}-{int(stem[0]):02d}-{stem[1:]}"
    return now.strftime("%Y-%m-%d")


def child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """隔离 ART/NPZ，强制店铺切分（不设 DATTA_STRATIFY_POS）。"""
    env = os.environ.copy()
    env["DATTA_ART"] = str(ART)
    env["DATTA_NPZ"] = str(ASCII_ROOT / "npz")
    env["DATTA_LGB_TMP"] = str(ASCII_ROOT / "lgb")
    env["DATTA_RAW"] = str(RAW)
    env["DATTA_USE_ALL_RAW"] = "1"
    env["DATTA_TRAIN_FULL_ONLY"] = "1"
    env["KITCHEN_ASCII"] = str(ASCII_ROOT)
    env["DATTA_IMG"] = r"D:\temu_images"
    env.setdefault("HF_HOME", r"F:\Clip\hf-cache")
    env.setdefault("HF_HUB_OFFLINE", "1")
    env.setdefault("OMP_NUM_THREADS", "1")
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env.pop("DATTA_STRATIFY_POS", None)
    if extra:
        env.update(extra)
    ASCII_ROOT.mkdir(parents=True, exist_ok=True)
    (ASCII_ROOT / "npz").mkdir(parents=True, exist_ok=True)
    (ASCII_ROOT / "lgb").mkdir(parents=True, exist_ok=True)
    ART.mkdir(parents=True, exist_ok=True)
    Path(r"D:\temu_images").mkdir(parents=True, exist_ok=True)
    return env


def run_py(script: Path, args: list[str], extra_env: dict[str, str] | None = None) -> None:
    """跑子进程，失败立刻退出。"""
    cmd = [py_bin(), str(script), *args]
    print(f"[cmd] {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=str(ROOT), env=child_env(extra_env))
    if proc.returncode != 0:
        raise SystemExit(f"{script.name} 失败 exit={proc.returncode}")


def merge_today_files(paths: list[Path]) -> Path:
    """日更入口：单文件直接 ingest，多文件走 merge_csv。"""
    if len(paths) == 1:
        return ingest(paths[0])
    sys.path.insert(0, str(PIPE))
    from merge_csv import merge_files  # noqa: WPS433

    copied = [ingest(p) for p in paths]
    return merge_files(copied)


def ingest(src: Path) -> Path:
    """把当天 CSV 放进 inbox 镜像和 data/raw。"""
    src = src.expanduser().resolve()
    if not src.is_file():
        raise FileNotFoundError(src)
    INBOX.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    dest_raw = RAW / src.name
    dest_in = INBOX / src.name
    if dest_raw.resolve() != src:
        shutil.copy2(src, dest_raw)
    if dest_in.resolve() != src and dest_in.resolve() != dest_raw.resolve():
        shutil.copy2(src, dest_in)
    print(f"[ingest] {dest_raw}")
    return dest_raw


def clean_csv(src: Path) -> Path:
    """按 words/banned.txt 去掉命中行。"""
    sys.path.insert(0, str(SCREENER / "src"))
    from read_table import read_input  # noqa: WPS433
    from word_filter import apply_banned, load_words, log_stats  # noqa: WPS433

    CLEANED.mkdir(parents=True, exist_ok=True)
    df = read_input(src, src.name)
    entries = load_words(WORDS, ROOT / "words" / "words_normalized.json")
    df, hits = apply_banned(df, entries)
    log_stats(df, len(entries), hits)
    n_ban = int(df["banned"].sum())
    kept = df.loc[~df["banned"].astype(bool)].copy()
    out = CLEANED / f"{src.stem}.csv"
    kept.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"[clean] 去掉违禁 {n_ban} 行，保留 {len(kept)} → {out}")
    return out


def compute_stats(df: pd.DataFrame) -> dict:
    """行数、动销率、销量均值/中位数/P90、价格均值/中位数。"""
    sales_col = "总销量" if "总销量" in df.columns else None
    price_col = next((c for c in ("美元价格($)", "美元价格", "价格") if c in df.columns), None)
    sales = pd.to_numeric(df[sales_col], errors="coerce").fillna(0) if sales_col else pd.Series([0.0] * len(df))
    price = pd.to_numeric(df[price_col], errors="coerce").fillna(0) if price_col else pd.Series([0.0] * len(df))
    return {
        "n": int(len(df)),
        "pos_rate": float((sales > 0).mean()) if len(df) else 0.0,
        "sales_mean": float(sales.mean()) if len(df) else 0.0,
        "sales_median": float(sales.median()) if len(df) else 0.0,
        "sales_p90": float(sales.quantile(0.9)) if len(df) else 0.0,
        "price_mean": float(price.mean()) if len(df) else 0.0,
        "price_median": float(price.median()) if len(df) else 0.0,
    }


def append_cache(iso: str, stem: str, stats: dict) -> None:
    """cache.json 按日期追加；同一天重跑则覆盖。"""
    payload = {"days": []}
    if CACHE_JSON.exists():
        try:
            payload = json.loads(CACHE_JSON.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {"days": []}
    days = [d for d in payload.get("days", []) if d.get("id") != iso]
    rec = {"id": iso, "file": stem, "at": datetime.now().isoformat(timespec="seconds"), **stats}
    days.append(rec)
    days.sort(key=lambda d: str(d.get("id", "")))
    CACHE_JSON.write_text(json.dumps({"days": days}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[cache] {iso} n={stats['n']} pos={stats['pos_rate']:.3f} sales_med={stats['sales_median']:.2f}")


def latest_published() -> Path | None:
    """最近一份人工保存、用于增量训练的 CSV。"""
    if not PUBLISHED.is_dir():
        return None
    files = [p for p in PUBLISHED.iterdir() if p.suffix.lower() in TABLE_SUFFIXES]
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def model_txt() -> Path:
    return ASCII_ROOT / "lgb" / "lgbm_full.txt"


def write_screener_config(inference_source: str = "") -> None:
    """预测阶段只读本项目缓存，不指向 D:\\temu_rank_npz。"""
    cfg = {
        "embed_cache_art_dir": str(ART),
        "npz_dir": str(ASCII_ROOT / "npz"),
        "inference_source": inference_source,
        "download_concurrency": 200,
        "seed": 42,
        "image_cache_dirs": [r"D:\temu_images"],
        "lgb_model_ascii_fallback": str(model_txt()),
        "hf_model": "BAAI/bge-small-zh-v1.5",
        "embed_batch": 32,
    }
    (SCREENER / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def train_shop_split(train_csv: Path, warm: bool) -> None:
    """文档 12.1：GroupShuffleSplit 按店铺 25% test，再 10% valid。"""
    extra = {
        "DATTA_RAW_FILE": str(train_csv),
        "DATTA_USE_ALL_RAW": "1",
    }
    init = model_txt()
    if warm and init.is_file():
        extra["DATTA_INIT_MODEL"] = str(init)
        print(f"[train] continue 昨天 {train_csv.name}")
    else:
        extra.pop("DATTA_INIT_MODEL", None)
        print(f"[train] 从头训练 {train_csv.name}（店铺切分）")
    for stage in ("prep", "download", "embed", "train"):
        run_py(PIPE / "rank_products.py", ["--stage", stage], extra)
    run_py(PIPE / "export_bundle.py", [], extra)


def url_cache_path(url: str) -> Path | None:
    """主图 URL 对应 D:\\temu_images 下的文件。"""
    if not url:
        return None
    h = md5(url.encode("utf-8")).hexdigest()
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        p = IMG_DIR / f"{h}{ext}"
        if p.exists():
            return p
    return None


def delete_train_images(train_csv: Path, keep_csv: Path | None) -> None:
    """删掉已进训练集的图；今天预测文件的图先留着。"""
    if keep_csv and train_csv.resolve() == keep_csv.resolve():
        print("[img] 训练文件就是今天预测文件，图先不删")
        return
    keep_ids: set[str] = set()
    if keep_csv and keep_csv.is_file():
        kdf = pd.read_csv(keep_csv, encoding="utf-8-sig", dtype=str)
        if "商品ID" in kdf.columns:
            keep_ids = set(kdf["商品ID"].astype(str))
    df = pd.read_csv(train_csv, encoding="utf-8-sig", dtype=str)
    url_col = next((c for c in ("main_url", "主图URL", "商品主图") if c in df.columns), None)
    id_col = "商品ID" if "商品ID" in df.columns else None
    n = 0
    for _, row in df.iterrows():
        if id_col and str(row.get(id_col, "")) in keep_ids:
            continue
        url = str(row.get(url_col, "") or "") if url_col else ""
        p = url_cache_path(url)
        if p and p.exists():
            p.unlink()
            n += 1
    print(f"[img] 删除训练集图片 {n} 张")


def predict_and_html(today: Path, iso: str) -> Path:
    """打分并生成可删改的分享 HTML。"""
    write_screener_config(today.name)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    run_py(SCREENER / "src" / "run.py", ["--input", str(today)])
    scored = SCREENER / "output" / f"{today.stem}_scored.csv"
    if not scored.is_file():
        raise SystemExit(f"缺少预测 CSV: {scored}")
    shutil.copy2(scored, OUTPUT / scored.name)
    title = f"选品 {iso}"
    run_py(
        SCREENER / "src" / "generate_html.py",
        ["--input", str(scored), "--out-dir", str(OUTPUT), "--title", title, "--top-pct", "5"],
    )
    share = OUTPUT / f"{today.stem}_分享.html"
    print(f"[html] {share}")
    return share


def mark_published(src: Path) -> Path:
    """把人工筛选后的 CSV/从 HTML 抽出的清单存成明天的训练数据。"""
    PUBLISHED.mkdir(parents=True, exist_ok=True)
    dest = PUBLISHED / src.name
    if src.suffix.lower() in {".html", ".htm"}:
        ids = ids_from_share_html(src)
        scored = next(OUTPUT.glob("*_scored.csv"), None)
        if scored is None:
            raise SystemExit("还没有 scored CSV，无法从 HTML 反推训练清单")
        df = pd.read_csv(scored, encoding="utf-8-sig", dtype=str)
        df = df[df["商品ID"].astype(str).isin(ids)].copy()
        dest = PUBLISHED / f"{scored.stem.replace('_scored', '')}_published.csv"
        df.to_csv(dest, index=False, encoding="utf-8-sig")
    else:
        shutil.copy2(src, dest)
    print(f"[published] {dest} 行数={sum(1 for _ in dest.open(encoding='utf-8-sig')) - 1}")
    return dest


def iso_from_scored() -> str:
    """优先用当天 scored/cleaned 文件名里的日期。"""
    for folder, pat in ((OUTPUT, "*_scored.csv"), (CLEANED, "*.csv"), (RAW, "*merged*.csv")):
        hits = sorted(folder.glob(pat), key=lambda p: p.stat().st_mtime, reverse=True) if folder.is_dir() else []
        if not hits:
            continue
        stem = hits[0].stem.replace("_scored", "").replace("_merged", "")
        digits = "".join(ch for ch in stem if ch.isdigit())
        if len(digits) >= 8:
            d = digits[:8]
            return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        parsed = day_id(hits[0])
        if parsed:
            return parsed
    return datetime.now().strftime("%Y-%m-%d")


def prepare_upload(src: Path, iso: str = "") -> Path:
    """生成要上传阶段：把筛选 HTML 和数分页按天写入 data_cache，旧天不覆盖。"""
    src = src.expanduser().resolve()
    if not src.is_file():
        raise FileNotFoundError(src)
    iso = (iso or "").strip() or iso_from_scored()
    folder = DATA_CACHE / iso
    folder.mkdir(parents=True, exist_ok=True)

    if src.suffix.lower() in {".html", ".htm"}:
        upload_html = folder / "上传.html"
        shutil.copy2(src, upload_html)
        published = str(upload_html)
    else:
        shutil.copy2(src, folder / src.name)
        published = ""

    cleaned = None
    if CLEANED.is_dir():
        cands = sorted(CLEANED.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
        cleaned = cands[0] if cands else None
    if cleaned is None:
        raise SystemExit("data/cleaned 里没有表，无法做数分")

    args = [
        "--cleaned",
        str(cleaned),
        "--iso",
        iso,
        "--out",
        str(folder / "分析.html"),
    ]
    if published:
        args.extend(["--published", published])
    run_py(PIPE / "analyze.py", args)
    print(f"[cache] {folder}")
    return folder


def ids_from_share_html(path: Path) -> set[str]:
    """从保存后的筛选 HTML 里抽出还在的 data-id。"""
    import re

    text = path.read_text(encoding="utf-8", errors="ignore")
    return set(re.findall(r'data-id="([^"]+)"', text))


def run_today(today: Path, retrain: bool = False) -> Path:
    """一天的完整流程。retrain=True 时用今天清洗结果按店铺从头训。"""
    today = ingest(today)
    cleaned = clean_csv(today)
    df = pd.read_csv(cleaned, encoding="utf-8-sig")
    append_cache(day_id(today), today.stem, compute_stats(df))
    shutil.copy2(cleaned, RAW / today.name)

    published = latest_published()
    has_model = model_txt().is_file()
    if retrain or not has_model:
        train_shop_split(cleaned, warm=False)
    elif published is not None:
        train_shop_split(published, warm=True)
        delete_train_images(published, keep_csv=cleaned)
    else:
        print("[train] 已有模型且还没有 published，跳过增量，只预测")

    return predict_and_html(cleaned, day_id(today))


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="厨房收纳日更")
    ap.add_argument("--today", nargs="*", default=[], help="当天 1～N 个 CSV，多文件先合并再跑")
    ap.add_argument("--publish", default="", help="把筛选后的 CSV/HTML 标为明天训练，并生成上传用数分")
    ap.add_argument("--bundle", default="", help="只做生成要上传：写入 data_cache/日期/")
    ap.add_argument("--iso", default="", help="发布/缓存日期 YYYY-MM-DD")
    ap.add_argument("--retrain", action="store_true", help="忽略已有模型，用今天清洗结果按店铺从头训")
    args = ap.parse_args()
    if args.publish:
        src = Path(args.publish)
        mark_published(src)
        prepare_upload(src, args.iso)
        return
    if args.bundle:
        prepare_upload(Path(args.bundle), args.iso)
        return
    paths = [Path(p) for p in args.today] if args.today else []
    if not paths:
        cands = [p for p in INBOX.iterdir() if p.is_file() and p.suffix.lower() in TABLE_SUFFIXES] if INBOX.is_dir() else []
        if not cands:
            raise SystemExit("inbox 为空，请 --today 或把 CSV 丢进 inbox")
        paths = [max(cands, key=lambda p: p.stat().st_mtime)]
    today = merge_today_files(paths)
    share = run_today(today, retrain=args.retrain)
    print(f"[done] {share}")


if __name__ == "__main__":
    main()
