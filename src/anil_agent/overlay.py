from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import Optional, Tuple

try:
    import tkinter as tk
except Exception as exc:  # pragma: no cover
    raise RuntimeError("tkinter is required for the overlay UI") from exc

from .config import load_config


logger = logging.getLogger(__name__)


def _find_hwnd(title_contains: str) -> int:
    try:
        import win32gui  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("pywin32 is required for overlay window attach") from exc

    wanted = title_contains.lower()
    matches: list[int] = []

    def enum_cb(hwnd: int, _: object) -> None:
        try:
            title = win32gui.GetWindowText(hwnd)
            if title and wanted in title.lower():
                matches.append(hwnd)
        except Exception:
            return

    win32gui.EnumWindows(enum_cb, None)
    if not matches:
        raise RuntimeError(f'window not found (title contains "{title_contains}")')
    return matches[0]


def _client_rect_on_screen(hwnd: int) -> Tuple[int, int, int, int]:
    import win32gui  # type: ignore

    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    (sx, sy) = win32gui.ClientToScreen(hwnd, (left, top))
    (ex, ey) = win32gui.ClientToScreen(hwnd, (right, bottom))
    width = max(1, ex - sx)
    height = max(1, ey - sy)
    return sx, sy, width, height


class OverlayApp:
    def __init__(
        self,
        *,
        title_contains: str,
        status_path: Path,
        anchor: str,
        width: int,
        height: int,
        offset_x: int,
        offset_y: int,
        refresh_ms: int,
        font_size: int,
        click_through: bool,
    ) -> None:
        self._title_contains = title_contains
        self._status_path = status_path
        self._anchor = anchor
        self._width = max(120, int(width))
        self._height = max(80, int(height))
        self._offset_x = int(offset_x)
        self._offset_y = int(offset_y)
        self._refresh_ms = max(50, int(refresh_ms))
        self._font_size = max(8, int(font_size))
        self._click_through = bool(click_through)

        self._root = tk.Tk()
        self._root.title("Anil Overlay")
        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)
        self._root.configure(bg="#111111")
        self._root.attributes("-alpha", 0.88)

        self._label = tk.Label(
            self._root,
            text="Starting overlay...",
            justify="left",
            anchor="nw",
            fg="#f5f5f5",
            bg="#111111",
            font=("Consolas", self._font_size),
        )
        self._label.pack(fill="both", expand=True, padx=8, pady=6)

        self._root.update_idletasks()
        self._apply_click_through()
        self._tick()

    def run(self) -> None:
        self._root.mainloop()

    def _apply_click_through(self) -> None:
        if not self._click_through:
            return
        try:
            import win32con  # type: ignore
            import win32gui  # type: ignore

            hwnd = self._root.winfo_id()
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            style |= win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_TOOLWINDOW
            no_activate = getattr(win32con, "WS_EX_NOACTIVATE", 0)
            if no_activate:
                style |= no_activate
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, style)
        except Exception as exc:
            logger.warning("overlay click-through failed: %s", exc)

    def _tick(self) -> None:
        self._update_position()
        self._update_text()
        self._root.after(self._refresh_ms, self._tick)

    def _update_position(self) -> None:
        try:
            hwnd = _find_hwnd(self._title_contains)
            x, y, w, h = _client_rect_on_screen(hwnd)
            width = min(self._width, w)
            height = min(self._height, h)

            if self._anchor == "topright":
                x = x + w - width - self._offset_x
                y = y + self._offset_y
            elif self._anchor == "bottomleft":
                x = x + self._offset_x
                y = y + h - height - self._offset_y
            elif self._anchor == "bottomright":
                x = x + w - width - self._offset_x
                y = y + h - height - self._offset_y
            else:
                x = x + self._offset_x
                y = y + self._offset_y

            self._root.geometry(f"{width}x{height}+{int(x)}+{int(y)}")
        except Exception as exc:
            self._label.config(text=f"Waiting for game window...\n{exc}")

    def _read_status(self) -> Optional[dict]:
        try:
            raw = self._status_path.read_text(encoding="utf-8")
            return json.loads(raw)
        except Exception:
            return None

    def _update_text(self) -> None:
        data = self._read_status()
        if not data:
            self._label.config(text="Waiting for live status...\nStart the bot to populate logs/live.json")
            return

        state = data.get("state") or {}
        action = data.get("action") or {}
        events = data.get("events") or []

        scene = state.get("scene")
        map_id = state.get("map_id")
        xy = state.get("player_xy")
        in_battle = state.get("in_battle")
        badges = state.get("badges_count")
        money = state.get("money")

        action_type = action.get("type") or "?"
        note = action.get("note") or ""

        action_line = f"action: {action_type}"
        if action_type == "buttons":
            buttons = action.get("buttons") or []
            btns = " ".join(
                f"{b.get('key', '?')}({b.get('ms', 0)})" for b in buttons if isinstance(b, dict)
            )
            wait_ms = action.get("wait_ms", 0)
            action_line = f"action: buttons {btns} wait={wait_ms}"
        elif action_type == "wait":
            wait_ms = action.get("wait_ms", 0)
            action_line = f"action: wait {wait_ms}"

        last_error = data.get("last_error") or ""

        age_s = 0.0
        try:
            age_s = max(0.0, time.time() - self._status_path.stat().st_mtime)
        except Exception:
            age_s = 0.0

        lines = [
            f"step: {data.get('step')}",
            f"scene: {scene}",
            f"map_id: {map_id}  xy: {xy}",
            f"in_battle: {in_battle}  badges: {badges}  money: {money}",
            action_line,
        ]
        if note:
            lines.append(f"note: {note}")
        lines.append(f"events: {len(events)}  last_update_s: {age_s:.1f}")
        if last_error:
            lines.append(f"last_error: {last_error}")

        self._label.config(text="\n".join(lines))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, default=Path("config.yaml"))
    ap.add_argument("--status-path", type=Path, default=None)
    ap.add_argument("--anchor", choices=["topleft", "topright", "bottomleft", "bottomright"], default="topleft")
    ap.add_argument("--width", type=int, default=420)
    ap.add_argument("--height", type=int, default=200)
    ap.add_argument("--offset-x", type=int, default=8)
    ap.add_argument("--offset-y", type=int, default=8)
    ap.add_argument("--refresh-ms", type=int, default=200)
    ap.add_argument("--font-size", type=int, default=11)
    ap.add_argument("--no-click-through", dest="click_through", action="store_false")
    ap.set_defaults(click_through=True)
    args = ap.parse_args()

    cfg = load_config(args.config)
    status_path = args.status_path or (cfg.paths.logs_dir / "live.json")

    app = OverlayApp(
        title_contains=cfg.game.window_title_contains,
        status_path=status_path,
        anchor=args.anchor,
        width=args.width,
        height=args.height,
        offset_x=args.offset_x,
        offset_y=args.offset_y,
        refresh_ms=args.refresh_ms,
        font_size=args.font_size,
        click_through=args.click_through,
    )
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
