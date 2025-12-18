from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from pydantic import BaseModel, Field


class GameConfig(BaseModel):
    window_title_contains: str = Field(min_length=1)
    ruby_host: str = "127.0.0.1"
    ruby_port: int = Field(default=53135, ge=1, le=65535)
    screenshot_max_width: Optional[int] = Field(default=768, ge=64)
    screenshot_mode: Literal["window", "window_on_screen", "screen"] = "window"
    screenshot_monitor_index: int = Field(default=1, ge=0)


class AgentConfig(BaseModel):
    model: str = "gemini-3-pro-preview"
    thinking_level: Literal["low", "high"] = "high"
    step_delay_ms: int = Field(default=250, ge=0, le=60_000)
    max_actions_per_minute: int = Field(default=240, ge=1, le=10_000)
    summary_mode: Literal["template", "gemini"] = "gemini"
    rules_text_spanish: Optional[str] = None


class DiscordConfig(BaseModel):
    token_env: str = "DISCORD_BOT_TOKEN"
    guild_id: Optional[int] = None
    admin_user_ids: list[int] = Field(default_factory=list)
    commands_in_control_channel_only: bool = True
    control_channel_id: int = Field(ge=0)
    captures_channel_id: int = Field(ge=0)
    deaths_channel_id: int = Field(ge=0)
    announce_channel_id: int = Field(ge=0)


class PathsConfig(BaseModel):
    logs_dir: Path = Path("./logs")
    reports_dir: Path = Path("./reports")


class AppConfig(BaseModel):
    game: GameConfig
    agent: AgentConfig = AgentConfig()
    discord: DiscordConfig
    paths: PathsConfig = PathsConfig()

    def resolve_paths(self, base_dir: Path) -> "AppConfig":
        base_dir = base_dir.resolve()
        return self.model_copy(
            update={
                "paths": self.paths.model_copy(
                    update={
                        "logs_dir": (base_dir / self.paths.logs_dir).resolve()
                        if not self.paths.logs_dir.is_absolute()
                        else self.paths.logs_dir.resolve(),
                        "reports_dir": (base_dir / self.paths.reports_dir).resolve()
                        if not self.paths.reports_dir.is_absolute()
                        else self.paths.reports_dir.resolve(),
                    }
                )
            }
        )


def load_config(path: Path) -> AppConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("config must be a YAML mapping")
    cfg = AppConfig.model_validate(raw)
    return cfg.resolve_paths(path.parent)


def dump_config_example() -> dict[str, Any]:
    return AppConfig.model_validate({  # type: ignore[arg-type]
        "game": {"window_title_contains": "Pokémon Añil: Definitive Edition"},
        "discord": {
            "control_channel_id": 0,
            "captures_channel_id": 0,
            "deaths_channel_id": 0,
            "announce_channel_id": 0,
        },
    }).model_dump()
