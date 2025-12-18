from __future__ import annotations

import ctypes
import io
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional, Tuple

import mss
from PIL import Image


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WindowCaptureConfig:
    window_title_contains: str
    screenshot_max_width: Optional[int] = 768
    screenshot_mode: Literal["window", "window_on_screen", "screen"] = "window"
    screenshot_monitor_index: int = 1


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

    def _capture_window_offscreen(self, hwnd: int) -> Image.Image:
        try:
            import win32con  # type: ignore
            import win32gui  # type: ignore
            import win32ui  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("pywin32 is required on Windows for offscreen window capture") from exc

        if win32gui.IsIconic(hwnd):
            raise RuntimeError("window is minimized; cannot capture offscreen")

        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        width = max(1, right - left)
        height = max(1, bottom - top)

        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
        save_dc.SelectObject(bitmap)

        try:
            flags = 0x00000001  # PW_CLIENTONLY
            render_flag = getattr(win32con, "PW_RENDERFULLCONTENT", 0)
            if render_flag:
                flags |= render_flag
            result = ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), flags)
            if result != 1:
                raise RuntimeError("PrintWindow failed (window may be occluded or use an unsupported renderer)")

            bmpinfo = bitmap.GetInfo()
            bmpstr = bitmap.GetBitmapBits(True)
            img = Image.frombuffer(
                "RGB",
                (bmpinfo["bmWidth"], bmpinfo["bmHeight"]),
                bmpstr,
                "raw",
                "BGRX",
                0,
                1,
            )
            return img
        finally:
            try:
                win32gui.DeleteObject(bitmap.GetHandle())
            except Exception:
                pass
            try:
                save_dc.DeleteDC()
                mfc_dc.DeleteDC()
            except Exception:
                pass
            try:
                win32gui.ReleaseDC(hwnd, hwnd_dc)
            except Exception:
                pass

    def _screen_rect(self, sct: mss.mss) -> Tuple[int, int, int, int]:
        monitors = sct.monitors
        idx = int(self._cfg.screenshot_monitor_index)
        if idx < 0 or idx >= len(monitors):
            raise RuntimeError(
                f"invalid screenshot_monitor_index={idx} (valid range: 0..{len(monitors) - 1})"
            )
        mon = monitors[idx]
        return mon["left"], mon["top"], mon["width"], mon["height"]

    def capture(self) -> tuple[bytes, Image.Image]:
        mode = self._cfg.screenshot_mode
        if mode == "window":
            hwnd = self._find_hwnd()
            img = self._capture_window_offscreen(hwnd)
        else:
            with mss.mss() as sct:
                if mode == "screen":
                    x, y, w, h = self._screen_rect(sct)
                else:
                    hwnd = self._find_hwnd()
                    x, y, w, h = self._client_rect_on_screen(hwnd)

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
