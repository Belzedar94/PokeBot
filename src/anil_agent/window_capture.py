from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import mss
from PIL import Image


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WindowCaptureConfig:
    window_title_contains: str
    screenshot_max_width: Optional[int] = 768


class WindowCapture:
    def __init__(self, cfg: WindowCaptureConfig):
        self._cfg = cfg

    def _find_hwnd(self) -> int:
        try:
            import win32gui  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("pywin32 is required on Windows for window capture") from exc

        wanted = self._cfg.window_title_contains.lower()
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
            raise RuntimeError(f'window not found (title contains "{self._cfg.window_title_contains}")')
        return matches[0]

    def _client_rect_on_screen(self, hwnd: int) -> Tuple[int, int, int, int]:
        import win32gui  # type: ignore

        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        (sx, sy) = win32gui.ClientToScreen(hwnd, (left, top))
        (ex, ey) = win32gui.ClientToScreen(hwnd, (right, bottom))
        width = max(1, ex - sx)
        height = max(1, ey - sy)
        return sx, sy, width, height

    def capture(self) -> tuple[bytes, Image.Image]:
        hwnd = self._find_hwnd()
        x, y, w, h = self._client_rect_on_screen(hwnd)

        with mss.mss() as sct:
            raw = sct.grab({"left": x, "top": y, "width": w, "height": h})
            img = Image.frombytes("RGB", raw.size, raw.rgb)

        max_w = self._cfg.screenshot_max_width
        if max_w and img.width > max_w:
            new_h = int(img.height * (max_w / float(img.width)))
            img = img.resize((max_w, max(1, new_h)), resample=Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue(), img

    def capture_to_file(self, path: Path) -> Path:
        png, _ = self.capture()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png)
        return path

