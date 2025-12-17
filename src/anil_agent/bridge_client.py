from __future__ import annotations

import json
import logging
import socket
import threading
from dataclasses import dataclass
from typing import Any, Optional


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BridgeClientConfig:
    host: str
    port: int
    connect_timeout_s: float = 1.0
    request_timeout_s: float = 1.5


class BridgeClient:
    def __init__(self, cfg: BridgeClientConfig):
        self._cfg = cfg
        self._lock = threading.Lock()
        self._sock: Optional[socket.socket] = None
        self._file = None

    def close(self) -> None:
        with self._lock:
            self._close_locked()

    def _close_locked(self) -> None:
        try:
            if self._file is not None:
                self._file.close()
        except Exception:
            pass
        try:
            if self._sock is not None:
                self._sock.close()
        except Exception:
            pass
        self._sock = None
        self._file = None

    def _ensure_connected_locked(self) -> None:
        if self._sock is not None and self._file is not None:
            return
        self._close_locked()

        sock = socket.create_connection(
            (self._cfg.host, self._cfg.port), timeout=self._cfg.connect_timeout_s
        )
        sock.settimeout(self._cfg.request_timeout_s)
        self._sock = sock
        self._file = sock.makefile("rwb", buffering=0)

    def request(self, obj: dict[str, Any]) -> dict[str, Any]:
        payload = (json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )

        with self._lock:
            for attempt in range(2):
                try:
                    self._ensure_connected_locked()
                    assert self._file is not None
                    self._file.write(payload)
                    self._file.flush()
                    line = self._file.readline()
                    if not line:
                        raise ConnectionError("bridge closed connection")
                    return json.loads(line.decode("utf-8"))
                except Exception as exc:
                    logger.warning("bridge request failed (attempt %s): %s", attempt + 1, exc)
                    self._close_locked()
            raise ConnectionError("bridge request failed after retries")

    def ping(self) -> bool:
        resp = self.request({"cmd": "ping"})
        return bool(resp.get("ok")) and bool(resp.get("pong"))

    def get_state(self) -> dict[str, Any]:
        resp = self.request({"cmd": "state"})
        if not resp.get("ok"):
            raise RuntimeError(f"bridge state error: {resp}")
        state = resp.get("state")
        if not isinstance(state, dict):
            raise RuntimeError(f"bridge state invalid: {resp}")
        return state

    def get_events(self) -> list[dict[str, Any]]:
        resp = self.request({"cmd": "events"})
        if not resp.get("ok"):
            raise RuntimeError(f"bridge events error: {resp}")
        events = resp.get("events", [])
        if not isinstance(events, list):
            raise RuntimeError(f"bridge events invalid: {resp}")
        out: list[dict[str, Any]] = []
        for e in events:
            if isinstance(e, dict):
                out.append(e)
        return out

    def set_debug(self, enabled: bool) -> None:
        self.request({"cmd": "set", "key": "debug", "value": bool(enabled)})

