from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class RunPaths:
    run_id: str
    run_dir: Path
    steps_dir: Path


def make_run_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    rand = os.urandom(3).hex()
    return f"{ts}_{rand}"


def setup_logging(logs_dir: Path, run_id: Optional[str] = None) -> RunPaths:
    logs_dir.mkdir(parents=True, exist_ok=True)
    run_id = run_id or make_run_id()
    run_dir = logs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    steps_dir = run_dir / "steps"
    steps_dir.mkdir(parents=True, exist_ok=True)

    log_path = run_dir / "run.log"

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    for h in list(root.handlers):
        root.removeHandler(h)

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root.addHandler(sh)

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)

    logging.getLogger("discord").setLevel(logging.INFO)
    logging.getLogger("google").setLevel(logging.INFO)

    logging.getLogger(__name__).info("run_id=%s log=%s", run_id, log_path)
    return RunPaths(run_id=run_id, run_dir=run_dir, steps_dir=steps_dir)


def write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
