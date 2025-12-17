from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional

from .action_schema import Action, ButtonsAction, WaitAction, action_to_dict, safe_fallback_action
from .bridge_client import BridgeClient
from .gemini_client import GeminiClient
from .input_controller import InputController
from .logging_setup import RunPaths, write_json
from .window_capture import WindowCapture


logger = logging.getLogger(__name__)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AgentStatus:
    running: bool = False
    paused: bool = True
    last_step: int = 0
    last_state: Optional[Dict[str, Any]] = None
    last_action: Optional[Dict[str, Any]] = None
    last_error: Optional[str] = None
    last_action_t: Optional[str] = None


class StepLogger:
    def __init__(self, run_paths: RunPaths):
        self._steps_dir = run_paths.steps_dir

    def log_step(
        self,
        *,
        step: int,
        state: Dict[str, Any],
        events: List[Dict[str, Any]],
        action: Action,
        screenshot_png: bytes,
    ) -> None:
        png_name = f"{step:06d}.png"
        json_name = f"{step:06d}.json"

        png_path = self._steps_dir / png_name
        png_path.write_bytes(screenshot_png)

        record = {
            "step": step,
            "t": utc_now_iso(),
            "state": state,
            "events": events,
            "action": action_to_dict(action),
            "screenshot": png_name,
        }
        write_json(self._steps_dir / json_name, record)


class AgentController:
    def __init__(
        self,
        *,
        run_paths: RunPaths,
        step_delay_ms: int,
        max_actions_per_minute: int,
        bridge: BridgeClient,
        capture: WindowCapture,
        input_ctrl: InputController,
        gemini: GeminiClient,
        rules_text_spanish: Optional[str] = None,
        on_events: Optional[Callable[[List[Dict[str, Any]], Dict[str, Any], bytes], None]] = None,
    ):
        self._run_paths = run_paths
        self._step_delay_s = max(0.0, step_delay_ms / 1000.0)
        self._max_actions_per_minute = max_actions_per_minute
        self._bridge = bridge
        self._capture = capture
        self._input = input_ctrl
        self._gemini = gemini
        self._rules_text_spanish = rules_text_spanish
        self._on_events = on_events

        self._stop = threading.Event()
        self._paused = threading.Event()
        self._paused.set()
        self._thread: Optional[threading.Thread] = None

        self._status = AgentStatus()
        self._status_lock = threading.Lock()
        self._recent_actions: Deque[Dict[str, Any]] = deque(maxlen=10)
        self._action_times: Deque[float] = deque(maxlen=1200)

        self._step_logger = StepLogger(run_paths)

    def set_event_handler(
        self, handler: Optional[Callable[[List[Dict[str, Any]], Dict[str, Any], bytes], None]]
    ) -> None:
        self._on_events = handler

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._paused.clear()
        self._thread = threading.Thread(target=self._run_loop, name="agent-loop", daemon=True)
        self._thread.start()
        with self._status_lock:
            self._status.running = True
            self._status.paused = False

    def pause(self) -> None:
        self._paused.set()
        with self._status_lock:
            self._status.paused = True

    def resume(self) -> None:
        self._paused.clear()
        with self._status_lock:
            self._status.paused = False

    def stop(self) -> None:
        self._stop.set()
        self._paused.clear()
        if self._thread:
            self._thread.join(timeout=5.0)
        with self._status_lock:
            self._status.running = False
            self._status.paused = True

    def set_thinking_level(self, level: str) -> None:
        self._gemini.set_thinking_level(level)

    def get_status(self) -> AgentStatus:
        with self._status_lock:
            return AgentStatus(**json.loads(json.dumps(self._status.__dict__)))

    def capture_screenshot(self, out_path: Path) -> Path:
        return self._capture.capture_to_file(out_path)

    def _rate_limit(self) -> None:
        if self._max_actions_per_minute <= 0:
            return
        now = time.time()
        window = 60.0
        while self._action_times and (now - self._action_times[0]) > window:
            self._action_times.popleft()
        if len(self._action_times) >= self._max_actions_per_minute:
            sleep_s = max(0.05, window - (now - self._action_times[0]))
            logger.info("rate limit reached, sleeping %.2fs", sleep_s)
            time.sleep(sleep_s)

    def _execute_action(self, action: Action) -> None:
        if isinstance(action, ButtonsAction):
            buttons = [b.model_dump() for b in action.buttons]
            self._input.sequence(buttons, wait_ms=action.wait_ms)
        elif isinstance(action, WaitAction):
            time.sleep(action.wait_ms / 1000.0)
        else:
            time.sleep(0.25)

    def _run_loop(self) -> None:
        step = 0
        try:
            while not self._stop.is_set():
                if self._paused.is_set():
                    time.sleep(0.25)
                    continue

                self._rate_limit()

                events: List[Dict[str, Any]] = []
                state: Dict[str, Any] = {}
                screenshot_png: bytes = b""
                action: Action = safe_fallback_action("uninitialized")

                try:
                    state = self._bridge.get_state()
                    events = self._bridge.get_events()
                except Exception as exc:
                    with self._status_lock:
                        self._status.last_error = f"bridge_error: {exc}"
                    logger.warning("bridge error: %s", exc)

                try:
                    screenshot_png, _ = self._capture.capture()
                except Exception as exc:
                    with self._status_lock:
                        self._status.last_error = f"capture_error: {exc}"
                    logger.warning("capture error: %s", exc)

                try:
                    if self._on_events and events:
                        self._on_events(events, state, screenshot_png)
                except Exception as exc:
                    logger.exception("event handler error: %s", exc)

                if self._paused.is_set() or self._stop.is_set():
                    time.sleep(0.25)
                    continue

                try:
                    action = self._gemini.decide_action(
                        screenshot_png=screenshot_png,
                        state=state,
                        recent_actions=list(self._recent_actions),
                        rules_text_spanish=self._rules_text_spanish,
                    )
                except Exception as exc:
                    with self._status_lock:
                        self._status.last_error = f"gemini_error: {exc}"
                    logger.warning("gemini error: %s", exc)
                    action = safe_fallback_action("gemini_error")

                try:
                    self._execute_action(action)
                    self._action_times.append(time.time())
                except Exception as exc:
                    with self._status_lock:
                        self._status.last_error = f"input_error: {exc}"
                    logger.warning("input error: %s", exc)
                    time.sleep(0.25)

                try:
                    if screenshot_png:
                        self._step_logger.log_step(
                            step=step,
                            state=state,
                            events=events,
                            action=action,
                            screenshot_png=screenshot_png,
                        )
                except Exception as exc:
                    logger.warning("step log error: %s", exc)

                with self._status_lock:
                    self._status.last_step = step
                    self._status.last_state = state
                    self._status.last_action = action_to_dict(action)
                    self._status.last_action_t = utc_now_iso()

                self._recent_actions.append(self._status.last_action or {})
                step += 1
                time.sleep(self._step_delay_s)
        except Exception as exc:
            logger.exception("agent loop crashed: %s", exc)
            with self._status_lock:
                self._status.last_error = f"loop_crash: {exc}"
        finally:
            with self._status_lock:
                self._status.running = False
                self._status.paused = True
