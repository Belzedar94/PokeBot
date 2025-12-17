from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv

from .bridge_client import BridgeClient, BridgeClientConfig
from .config import AppConfig, load_config
from .decision_loop import AgentController
from .discord_bot import AnilDiscordBot, OutboundMessage
from .gemini_client import GeminiClient, GeminiConfig
from .input_controller import InputController, InputControllerConfig
from .logging_setup import setup_logging
from .report_store import ReportStore
from .reporter import Reporter, ReporterConfig
from .window_capture import WindowCapture, WindowCaptureConfig


logger = logging.getLogger(__name__)


def build_event_handler(
    *,
    cfg: AppConfig,
    agent: AgentController,
    send: Any,
    store: ReportStore,
    reporter: Reporter,
) -> Any:
    def on_events(events: List[Dict[str, Any]], state: Dict[str, Any], screenshot_png: bytes) -> None:
        for ev in events:
            et = str(ev.get("type") or "")
            if et == "pokemon_acquired":
                if screenshot_png:
                    store.add_capture(ev, screenshot_png)
            elif et == "pokemon_death":
                if screenshot_png:
                    store.add_death(ev, screenshot_png)
            elif et == "badge_earned":
                badge_count = int(ev.get("badge_count") or 0)
                last = store.get_last_badge_reported()
                if badge_count <= last:
                    continue

                agent.pause()

                day = store.load_today().get("date")
                day = str(day)

                # Fill missing summaries.
                for kind in ("captures", "deaths"):
                    report = store.load_today()
                    items = report.get(kind, [])
                    if not isinstance(items, list):
                        continue
                    changed = False
                    for rec in items:
                        if not isinstance(rec, dict):
                            continue
                        if rec.get("summary"):
                            continue
                        rec["summary"] = reporter.generate_funny_summary(rec, kind=kind)
                        changed = True
                    if changed:
                        store.save(report)

                # Post unreported items.
                for kind, channel_id in (
                    ("captures", cfg.discord.captures_channel_id),
                    ("deaths", cfg.discord.deaths_channel_id),
                ):
                    if int(channel_id) <= 0:
                        continue
                    for rec in store.iter_unreported(kind):
                        rel = str(rec.get("screenshot") or "")
                        if not rel:
                            continue
                        path = store.resolve_screenshot_path(day, rel)
                        summary = str(rec.get("summary") or "")
                        send(
                            OutboundMessage(
                                channel_id=int(channel_id),
                                content=summary or f"{kind}: {rel}",
                                file_path=path,
                                filename=Path(rel).name,
                            )
                        )
                        store.mark_reported(day, kind, rel)

                if int(cfg.discord.announce_channel_id) > 0:
                    send(
                        OutboundMessage(
                            channel_id=int(cfg.discord.announce_channel_id),
                            content=f"Badge earned (total={badge_count}). Agent paused. Use /resume.",
                        )
                    )

                store.update_last_badge_reported(badge_count)

    return on_events


def main() -> int:
    load_dotenv()

    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, default=Path("config.yaml"))
    ap.add_argument("--bridge-test", action="store_true", help="Run 100x ping/state/events then exit.")
    ap.add_argument("--screenshot-test", action="store_true", help="Capture one window screenshot then exit.")
    args = ap.parse_args()

    cfg = load_config(args.config)
    run_paths = setup_logging(cfg.paths.logs_dir)

    bridge = BridgeClient(BridgeClientConfig(host=cfg.game.ruby_host, port=cfg.game.ruby_port))
    capture = WindowCapture(
        WindowCaptureConfig(
            window_title_contains=cfg.game.window_title_contains,
            screenshot_max_width=cfg.game.screenshot_max_width,
        )
    )
    input_ctrl = InputController(InputControllerConfig(window_title_contains=cfg.game.window_title_contains))

    if args.screenshot_test:
        out = run_paths.run_dir / "screenshot_test.png"
        capture.capture_to_file(out)
        logger.info("saved screenshot to %s", out)
        return 0

    if args.bridge_test:
        ok = bridge.ping()
        if not ok:
            raise RuntimeError("bridge ping failed")
        for _ in range(100):
            bridge.ping()
            bridge.get_state()
            bridge.get_events()
        logger.info("bridge test OK")
        return 0

    token = os.environ.get(cfg.discord.token_env, "")
    if not token:
        raise RuntimeError(f"Missing Discord token in env var {cfg.discord.token_env}")

    gemini = GeminiClient(GeminiConfig(model=cfg.agent.model, thinking_level=cfg.agent.thinking_level))

    store = ReportStore(cfg.paths.reports_dir)
    reporter = Reporter(
        ReporterConfig(mode=cfg.agent.summary_mode, model=cfg.agent.model, thinking_level="low")
    )

    agent = AgentController(
        run_paths=run_paths,
        step_delay_ms=cfg.agent.step_delay_ms,
        max_actions_per_minute=cfg.agent.max_actions_per_minute,
        bridge=bridge,
        capture=capture,
        input_ctrl=input_ctrl,
        gemini=gemini,
        rules_text_spanish=cfg.agent.rules_text_spanish,
        on_events=None,
    )

    bot = AnilDiscordBot(
        token=token,
        guild_id=cfg.discord.guild_id,
        agent=agent,
        scratch_dir=run_paths.run_dir,
        control_channel_id=cfg.discord.control_channel_id,
        captures_channel_id=cfg.discord.captures_channel_id,
        deaths_channel_id=cfg.discord.deaths_channel_id,
        announce_channel_id=cfg.discord.announce_channel_id,
    )

    on_events = build_event_handler(
        cfg=cfg,
        agent=agent,
        send=bot.enqueue_from_thread,
        store=store,
        reporter=reporter,
    )
    agent.set_event_handler(on_events)

    bot.run_bot()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
