from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


logger = logging.getLogger(__name__)


def _today_str() -> str:
    return date.today().isoformat()


_SAFE = re.compile(r"[^a-z0-9_]+")


def _slug(s: str) -> str:
    s = s.strip().lower().replace(" ", "_")
    s = _SAFE.sub("", s)
    return s or "unknown"


@dataclass(frozen=True)
class ReportPaths:
    day_dir: Path
    report_json: Path
    captures_dir: Path
    deaths_dir: Path


class ReportStore:
    def __init__(self, reports_dir: Path):
        self._reports_dir = reports_dir
        self._lock = threading.Lock()

    def _paths_for_date(self, day: str) -> ReportPaths:
        day_dir = self._reports_dir / day
        return ReportPaths(
            day_dir=day_dir,
            report_json=day_dir / "report.json",
            captures_dir=day_dir / "captures",
            deaths_dir=day_dir / "deaths",
        )

    def load_today(self) -> Dict[str, Any]:
        return self.load(_today_str())

    def load(self, day: str) -> Dict[str, Any]:
        with self._lock:
            return self._load_locked(day)

    def _load_locked(self, day: str) -> Dict[str, Any]:
        p = self._paths_for_date(day)
        p.day_dir.mkdir(parents=True, exist_ok=True)
        p.captures_dir.mkdir(parents=True, exist_ok=True)
        p.deaths_dir.mkdir(parents=True, exist_ok=True)

        if p.report_json.exists():
            try:
                return json.loads(p.report_json.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("failed to load report.json (%s), recreating: %s", p.report_json, exc)

        report = {"date": day, "captures": [], "deaths": [], "last_badge_reported": 0}
        p.report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    def save(self, report: Dict[str, Any]) -> None:
        with self._lock:
            self._save_locked(report)

    def _save_locked(self, report: Dict[str, Any]) -> None:
        day = str(report.get("date") or _today_str())
        p = self._paths_for_date(day)
        p.day_dir.mkdir(parents=True, exist_ok=True)
        p.report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    def add_capture(self, event: Dict[str, Any], screenshot_png: bytes) -> Dict[str, Any]:
        return self._add_event(kind="captures", event=event, screenshot_png=screenshot_png)

    def add_death(self, event: Dict[str, Any], screenshot_png: bytes) -> Dict[str, Any]:
        return self._add_event(kind="deaths", event=event, screenshot_png=screenshot_png)

    def _add_event(self, *, kind: str, event: Dict[str, Any], screenshot_png: bytes) -> Dict[str, Any]:
        if kind not in ("captures", "deaths"):
            raise ValueError("kind must be captures or deaths")

        day = _today_str()
        with self._lock:
            report = self._load_locked(day)
            items: List[Dict[str, Any]] = report.get(kind, [])
            if not isinstance(items, list):
                items = []
                report[kind] = items

            n = len(items) + 1
            species = str(event.get("species") or "unknown")
            name = str(event.get("name") or species)
            level = event.get("level")
            uid = event.get("uid")
            map_id = event.get("map_id")
            t = event.get("t")

            fname = f"{n:03d}_{_slug(species)}.png"
            rel = f"{kind}/{fname}"

            p = self._paths_for_date(day)
            out_path = p.day_dir / rel
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(screenshot_png)

            rec = {
                "t": t,
                "uid": uid,
                "species": species,
                "name": name,
                "level": level,
                "map_id": map_id,
                "screenshot": rel,
                "summary": None,
                "reported": False,
            }
            items.append(rec)
            self._save_locked(report)
            return rec

    def iter_unreported(self, kind: str) -> List[Dict[str, Any]]:
        day = _today_str()
        with self._lock:
            report = self._load_locked(day)
            items = report.get(kind, [])
            if not isinstance(items, list):
                return []
            return [x for x in items if isinstance(x, dict) and not x.get("reported")]

    def mark_reported(self, day: str, kind: str, screenshot_rel: str) -> None:
        with self._lock:
            report = self._load_locked(day)
            items = report.get(kind, [])
            if not isinstance(items, list):
                return
            for rec in items:
                if isinstance(rec, dict) and rec.get("screenshot") == screenshot_rel:
                    rec["reported"] = True
            self._save_locked(report)

    def update_last_badge_reported(self, badge_count: int) -> None:
        day = _today_str()
        with self._lock:
            report = self._load_locked(day)
            report["last_badge_reported"] = int(badge_count)
            self._save_locked(report)

    def get_last_badge_reported(self) -> int:
        day = _today_str()
        with self._lock:
            report = self._load_locked(day)
            try:
                return int(report.get("last_badge_reported") or 0)
            except Exception:
                return 0

    def resolve_screenshot_path(self, day: str, screenshot_rel: str) -> Path:
        return (self._reports_dir / day / screenshot_rel).resolve()
