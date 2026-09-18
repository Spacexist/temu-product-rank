# -*- coding: utf-8 -*-
"""日常增量训练 + 预测 + HTML 的唯一入口。

约定：
- 把当天日报放进 data/raw/ 后，训练集 = 除最新文件外的全部日报；
- 最新文件只用于当天预测，不进当天训练；
- 训练走累计数据全量重训，向量优先读 D:\\temu_rank_npz；
- 模型阶段只出 scored CSV，HTML 阶段再生成筛选页。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
SCREENER_DIR = PROJECT_ROOT / "screener"
OUTPUT_DIR = SCREENER_DIR / "output"
RUNS_DIR = PROJECT_ROOT / "runs"
CONFIG_PATH = SCREENER_DIR / "config.json"
MANIFEST_PATH = RUNS_DIR / "manifest.json"
PYTHON_DEFAULT = Path(r"F:\Clip\venv\Scripts\python.exe")
TABLE_SUFFIXES = {".csv", ".xlsx", ".xls"}
STAGES = ("ingest", "prep", "embed", "train", "export", "predict", "html", "archive")


def now_iso() -> str:
    """返回本地时间 ISO 字符串，写入 run 归档。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def day_key(path: Path) -> int:
    """从 909.csv / 917.csv 这类文件名解析排序键；无法解析的排到最后。"""
    try:
        return int(path.stem)
    except ValueError:
        return 10**9


def list_raw_files() -> list[Path]:
    """列出 data/raw 里可训练/预测的日报，按日期数字升序。"""
    if not RAW_DIR.is_dir():
        return []
    files = [
        p
        for p in RAW_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in TABLE_SUFFIXES
    ]
    return sorted(files, key=lambda p: (day_key(p), p.name))


def stem_to_run_date(stem: str, year: int | None = None) -> str:
    """把 917 编成 20260917；已是 8 位数字则原样使用。"""
    year = year or datetime.now().year
    if stem.isdigit() and len(stem) == 8:
        return stem
    if stem.isdigit() and len(stem) == 3:
        return f"{year}{int(stem[0]):02d}{int(stem[1:]):02d}"
    if stem.isdigit() and len(stem) == 4:
        return f"{year}{stem}"
    return datetime.now().strftime("%Y%m%d")


def copy_into_raw(src: Path) -> Path:
    """把当天日报复制进 data/raw，文件名保持原 stem。已在 raw 则不覆盖拷贝。"""
    src = src.expanduser().resolve()
    if not src.is_file():
        raise FileNotFoundError(f"找不到当天文件: {src}")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    dest = RAW_DIR / src.name
    if dest.resolve() == src:
        return dest
    if dest.exists() and dest.stat().st_size == src.stat().st_size:
        print(f"[ingest] 已存在 {dest}")
        return dest
    shutil.copy2(src, dest)
    print(f"[ingest] 复制 {src} -> {dest}")
    return dest


def resolve_files(today: Path | None) -> tuple[list[Path], Path]:
    """解析训练集和当天预测文件：最新日报预测，其余全部训练。"""
    raws = list_raw_files()
    if today is not None:
        predict = copy_into_raw(today)
        raws = list_raw_files()
        train = [p for p in raws if p.name != predict.name]
    else:
        if not raws:
            raise SystemExit("data/raw 为空，请先提供 --today")
        if len(raws) == 1:
            raise SystemExit("data/raw 只有 1 个文件，无法同时训练和预测")
        train, predict = raws[:-1], raws[-1]
    if not train:
        raise SystemExit("没有可训练的历史日报")
    if not predict.exists():
        raise SystemExit(f"预测文件不存在: {predict}")
    return train, predict


def python_bin(explicit: str) -> Path:
    """选择 Python：优先 F:\\Clip\\venv，否则用当前解释器。"""
    if explicit:
        return Path(explicit)
    if PYTHON_DEFAULT.is_file():
        return PYTHON_DEFAULT
    return Path(sys.executable)


def child_env() -> dict[str, str]:
    """给训练/预测子进程补 HF 离线缓存和线程限制。"""
    env = os.environ.copy()
    env.setdefault("HF_HOME", r"F:\Clip\hf-cache")
    env.setdefault("HF_HUB_OFFLINE", "1")
    env.setdefault("OMP_NUM_THREADS", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def run_script(py: Path, script: Path, extra: list[str] | None = None) -> None:
    """用指定 Python 跑一个项目脚本，失败立刻退出。"""
    cmd = [str(py), str(script), *(extra or [])]
    print(f"[cmd] {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), env=child_env())
    if proc.returncode != 0:
        raise SystemExit(f"子进程失败 exit={proc.returncode}: {script.name}")


def update_inference_source(train_files: list[Path]) -> str:
    """把 screener/config.json 的 inference_source 指到训练集最新一天。"""
    source_name = train_files[-1].name
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    cfg["inference_source"] = source_name
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[config] inference_source={source_name}")
    return source_name


def sanity_scored(csv_path: Path) -> dict:
    """检查预测 CSV：有行、有分数、分数不能全挤成同一个值。"""
    import pandas as pd

    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    n = int(len(df))
    if n <= 0:
        raise SystemExit(f"预测 CSV 为空: {csv_path}")
    if "预测分" not in df.columns:
        raise SystemExit(f"预测 CSV 缺少 预测分: {csv_path}")
    scores = df["预测分"].astype(float)
    nunique = int(scores.nunique(dropna=True))
    if nunique <= 1:
        raise SystemExit(f"预测分几乎全相同 nunique={nunique}，拒绝作为当天结果")
    banned = int(df["banned"].fillna(0).astype(int).sum()) if "banned" in df.columns else 0
    info = {
        "rows": n,
        "score_min": float(scores.min()),
        "score_max": float(scores.max()),
        "score_nunique": nunique,
        "banned": banned,
    }
    print(f"[sanity] rows={n} score=[{info['score_min']:.4f},{info['score_max']:.4f}] banned={banned}")
    return info


def archive_run(
    run_date: str,
    train_files: list[Path],
    predict_file: Path,
    scored: Path,
    extras: list[Path],
    sanity: dict,
    inference_source: str,
) -> Path:
    """把当天输入和产物拷到 runs/YYYYMMDD/，并更新 manifest。"""
    run_dir = RUNS_DIR / run_date
    input_dir = run_dir / "input"
    out_dir = run_dir / "output"
    input_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(predict_file, input_dir / predict_file.name)
    copied = []
    for src in [scored, *extras]:
        if src.exists():
            shutil.copy2(src, out_dir / src.name)
            copied.append(src.name)
    meta_src = SCREENER_DIR / "model" / "meta.json"
    if meta_src.exists():
        shutil.copy2(meta_src, run_dir / "model_meta.json")
    record = {
        "run_date": run_date,
        "status": "predicted",
        "created_at": now_iso(),
        "predict_file": predict_file.name,
        "train_files": [p.name for p in train_files],
        "inference_source": inference_source,
        "scored": scored.name,
        "outputs": copied,
        "sanity": sanity,
    }
    (run_dir / "run.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    upsert_manifest(record)
    print(f"[archive] {run_dir}")
    return run_dir


def upsert_manifest(record: dict) -> None:
    """按 run_date 覆盖写入 runs/manifest.json。"""
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    data = {"updated_at": now_iso(), "runs": []}
    if MANIFEST_PATH.exists():
        try:
            data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    runs = [r for r in data.get("runs", []) if r.get("run_date") != record["run_date"]]
    runs.append(record)
    runs.sort(key=lambda r: str(r.get("run_date", "")))
    payload = {"updated_at": now_iso(), "runs": runs}
    MANIFEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def print_plan(train_files: list[Path], predict_file: Path, run_date: str, stages: list[str]) -> None:
    """打印当天将执行的训练/预测切分，便于 dry-run 核对。"""
    print("==== daily plan ====")
    print(f"run_date: {run_date}")
    print(f"train:    {', '.join(p.name for p in train_files)}")
    print(f"predict:  {predict_file.name}")
    print(f"stages:   {', '.join(stages)}")
    print("====================")


def parse_args() -> argparse.Namespace:
    """解析日常 pipeline 参数。"""
    ap = argparse.ArgumentParser(description="Datta 日常增量训练/预测/HTML pipeline")
    ap.add_argument("--today", default="", help="当天待预测日报路径；省略则用 data/raw 最新文件")
    ap.add_argument("--run-date", default="", help="归档目录名，默认由文件名 917 -> 20260917")
    ap.add_argument("--python", default="", help="Python 解释器；默认 F:\\Clip\\venv")
    ap.add_argument(
        "--from-stage",
        choices=STAGES,
        default="ingest",
        help="从该阶段开始，用于训练已被别的进程跑完时续跑",
    )
    ap.add_argument("--skip-train", action="store_true", help="跳过 prep/embed/train/export，只预测和出 HTML")
    ap.add_argument("--html-only", action="store_true", help="只根据已有 scored CSV 生成 HTML 并归档")
    ap.add_argument("--with-eval", action="store_true", help="训练后再跑 slate eval；日常默认跳过")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不跑训练/预测")
    return ap.parse_args()


def selected_stages(args: argparse.Namespace) -> list[str]:
    """按开关裁剪要跑的阶段。"""
    if args.html_only:
        return ["html", "archive"]
    if args.skip_train:
        start = "predict"
    else:
        start = args.from_stage
    idx = STAGES.index(start)
    return list(STAGES[idx:])


def main() -> None:
    """执行日常 pipeline。"""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    stages = selected_stages(args)
    today = Path(args.today).expanduser() if args.today else None
    if "ingest" in stages and today is not None:
        today = copy_into_raw(today)
    train_files, predict_file = resolve_files(today if today is not None else None)
    run_date = args.run_date or stem_to_run_date(predict_file.stem)
    print_plan(train_files, predict_file, run_date, stages)
    if args.dry_run:
        return

    py = python_bin(args.python)
    rank = PROJECT_ROOT / "pipeline" / "rank_products.py"
    export = PROJECT_ROOT / "pipeline" / "export_bundle.py"
    run_py = SCREENER_DIR / "src" / "run.py"
    html_py = SCREENER_DIR / "src" / "generate_html.py"
    scored = OUTPUT_DIR / f"{predict_file.stem}_scored.csv"
    inference_source = train_files[-1].name

    if "prep" in stages or "embed" in stages or "train" in stages:
        inference_source = update_inference_source(train_files)
    if "prep" in stages:
        run_script(py, rank, ["--stage", "prep"])
    if "embed" in stages:
        run_script(py, rank, ["--stage", "embed"])
    if "train" in stages:
        run_script(py, rank, ["--stage", "train"])
        if args.with_eval:
            run_script(py, rank, ["--stage", "eval"])
    if "export" in stages:
        run_script(py, export)
        inference_source = update_inference_source(train_files)
    if "predict" in stages:
        run_script(py, run_py, ["--input", str(predict_file)])
    sanity = sanity_scored(scored)
    if "html" in stages:
        run_script(py, html_py, ["--input", str(scored)])
    extras = [
        OUTPUT_DIR / f"{predict_file.stem}_screener.html",
        OUTPUT_DIR / f"{predict_file.stem}_分享.html",
        OUTPUT_DIR / f"{predict_file.stem}_Top5pct_去违禁_去2D平面.csv",
    ]
    if "archive" in stages:
        archive_run(
            run_date,
            train_files,
            predict_file,
            scored,
            extras,
            sanity,
            inference_source,
        )
    share = extras[1]
    print(f"[done] 人工筛选页 {share}")


if __name__ == "__main__":
    main()
