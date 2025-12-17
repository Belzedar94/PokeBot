from __future__ import annotations

import ctypes
import logging
import time
from dataclasses import dataclass
from typing import Iterable, Optional


logger = logging.getLogger(__name__)


_user32 = ctypes.windll.user32  # type: ignore[attr-defined]

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR),
    ]


class INPUT(ctypes.Structure):
    class _INPUT_UNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]

    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.c_ulong), ("u", _INPUT_UNION)]


@dataclass(frozen=True)
class InputControllerConfig:
    window_title_contains: str
    max_press_ms: int = 1500
    max_sequence_len: int = 20


_VK = {
    "UP": 0x26,
    "DOWN": 0x28,
    "LEFT": 0x25,
    "RIGHT": 0x27,
    "Z": ord("Z"),
    "X": ord("X"),
    "C": ord("C"),
    "A": ord("A"),
    "S": ord("S"),
    "D": ord("D"),
    "Q": ord("Q"),
    "W": ord("W"),
}


class InputController:
    def __init__(self, cfg: InputControllerConfig):
        self._cfg = cfg

    def _find_hwnd(self) -> int:
        try:
            import win32gui  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("pywin32 is required on Windows for input control") from exc

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

    def focus_window(self) -> None:
        import win32con  # type: ignore
        import win32gui  # type: ignore

        hwnd = self._find_hwnd()
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        except Exception:
            pass
        try:
            win32gui.SetForegroundWindow(hwnd)
            win32gui.BringWindowToTop(hwnd)
        except Exception as exc:
            logger.warning("failed to focus window: %s", exc)

    def _send_key(self, vk: int, down: bool) -> None:
        flags = 0 if down else KEYEVENTF_KEYUP
        extra = ULONG_PTR(0)
        inp = INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(vk, 0, flags, 0, extra))
        sent = _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        if sent != 1:
            raise RuntimeError("SendInput failed")

    def press(self, key: str, ms: int) -> None:
        key = key.upper()
        if key not in _VK:
            raise ValueError(f"unsupported key: {key}")
        ms = int(ms)
        if ms < 0:
            raise ValueError("ms must be >= 0")
        if ms > self._cfg.max_press_ms:
            ms = self._cfg.max_press_ms

        self.focus_window()
        self._press_no_focus(key, ms)

    def _press_no_focus(self, key: str, ms: int) -> None:
        vk = _VK[key]
        try:
            self._send_key(vk, True)
            time.sleep(ms / 1000.0)
            self._send_key(vk, False)
        except Exception:
            self._fallback_press(key, ms)

    def _fallback_press(self, key: str, ms: int) -> None:
        try:
            import pydirectinput  # type: ignore

            pydirectinput.FAILSAFE = False
            pydirectinput.keyDown(key.lower())
            time.sleep(ms / 1000.0)
            pydirectinput.keyUp(key.lower())
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(f"input failed: {exc}") from exc

    def sequence(self, buttons: Iterable[dict], wait_ms: Optional[int] = None) -> None:
        buttons_list = list(buttons)
        if len(buttons_list) > self._cfg.max_sequence_len:
            buttons_list = buttons_list[: self._cfg.max_sequence_len]
        self.focus_window()
        for b in buttons_list:
            key = str(b.get("key", "")).upper()
            ms = int(b.get("ms", 80))
            if key not in _VK:
                continue
            ms = min(max(ms, 0), self._cfg.max_press_ms)
            self._press_no_focus(key, ms)
        if wait_ms:
            time.sleep(max(0, int(wait_ms)) / 1000.0)
