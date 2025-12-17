from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from .decision_loop import AgentController


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OutboundMessage:
    channel_id: int
    content: str
    file_path: Optional[Path] = None
    filename: Optional[str] = None


class AnilDiscordBot(commands.Bot):
    def __init__(
        self,
        *,
        token: str,
        guild_id: Optional[int],
        agent: AgentController,
        scratch_dir: Path,
        control_channel_id: int,
        captures_channel_id: int,
        deaths_channel_id: int,
        announce_channel_id: int,
    ):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)

        self._token = token
        self._guild_id = guild_id
        self.agent = agent
        self.scratch_dir = scratch_dir

        self.control_channel_id = control_channel_id
        self.captures_channel_id = captures_channel_id
        self.deaths_channel_id = deaths_channel_id
        self.announce_channel_id = announce_channel_id

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._out_queue: Optional[asyncio.Queue[OutboundMessage]] = None
        self._sender_task: Optional[asyncio.Task] = None

        self.tree.add_command(self._cmd_start())
        self.tree.add_command(self._cmd_pause())
        self.tree.add_command(self._cmd_resume())
        self.tree.add_command(self._cmd_stop())
        self.tree.add_command(self._cmd_status())
        self.tree.add_command(self._cmd_screenshot())
        self.tree.add_command(self._cmd_thinking())

    async def setup_hook(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._out_queue = asyncio.Queue()

        if self._guild_id:
            guild = discord.Object(id=int(self._guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logger.info("synced commands to guild %s", self._guild_id)
        else:
            await self.tree.sync()
            logger.info("synced global commands")

        self._sender_task = asyncio.create_task(self._sender_loop())

    async def _sender_loop(self) -> None:
        cooldown_s = 0.75
        while not self.is_closed():
            assert self._out_queue is not None
            msg = await self._out_queue.get()
            try:
                await self._send_outbound(msg)
            except Exception as exc:
                logger.warning("failed to send outbound message: %s", exc)
            await asyncio.sleep(cooldown_s)

    async def _send_outbound(self, msg: OutboundMessage) -> None:
        ch = self.get_channel(msg.channel_id)
        if ch is None:
            ch = await self.fetch_channel(msg.channel_id)
        if not isinstance(ch, (discord.TextChannel, discord.Thread)):
            raise RuntimeError("channel is not a text channel")

        if msg.file_path:
            file = discord.File(fp=str(msg.file_path), filename=msg.filename or msg.file_path.name)
            await ch.send(content=msg.content, file=file)
        else:
            await ch.send(content=msg.content)

    def enqueue_from_thread(self, msg: OutboundMessage) -> None:
        if not self._loop or not self._out_queue:
            logger.warning("discord loop not ready yet; dropping outbound message")
            return

        def _put() -> None:
            try:
                assert self._out_queue is not None
                self._out_queue.put_nowait(msg)
            except Exception as exc:
                logger.warning("failed to enqueue outbound message: %s", exc)

        self._loop.call_soon_threadsafe(_put)

    def run_bot(self) -> None:
        super().run(self._token)

    # ---- Slash commands ----

    def _cmd_start(self) -> app_commands.Command:
        @app_commands.command(name="start", description="Start the agent loop.")
        async def start_cmd(interaction: discord.Interaction) -> None:
            self.agent.start()
            await interaction.response.send_message("Agent started.")

        return start_cmd

    def _cmd_pause(self) -> app_commands.Command:
        @app_commands.command(name="pause", description="Pause the agent.")
        async def pause_cmd(interaction: discord.Interaction) -> None:
            self.agent.pause()
            await interaction.response.send_message("Paused.")

        return pause_cmd

    def _cmd_resume(self) -> app_commands.Command:
        @app_commands.command(name="resume", description="Resume the agent.")
        async def resume_cmd(interaction: discord.Interaction) -> None:
            self.agent.resume()
            await interaction.response.send_message("Resumed.")

        return resume_cmd

    def _cmd_stop(self) -> app_commands.Command:
        @app_commands.command(name="stop", description="Stop the agent.")
        async def stop_cmd(interaction: discord.Interaction) -> None:
            self.agent.stop()
            await interaction.response.send_message("Stopped.")

        return stop_cmd

    def _cmd_status(self) -> app_commands.Command:
        @app_commands.command(name="status", description="Show agent status.")
        async def status_cmd(interaction: discord.Interaction) -> None:
            st = self.agent.get_status()
            s = st.last_state or {}
            scene = s.get("scene")
            map_id = s.get("map_id")
            xy = s.get("player_xy")
            badges = s.get("badges_count")
            msg = (
                f"running={st.running} paused={st.paused}\n"
                f"step={st.last_step} last_action_t={st.last_action_t}\n"
                f"scene={scene} map_id={map_id} xy={xy} badges={badges}\n"
                f"last_action={st.last_action}\n"
                f"last_error={st.last_error}"
            )
            await interaction.response.send_message(msg)

        return status_cmd

    def _cmd_screenshot(self) -> app_commands.Command:
        @app_commands.command(name="screenshot", description="Capture a game screenshot.")
        async def screenshot_cmd(interaction: discord.Interaction) -> None:
            await interaction.response.defer(thinking=True, ephemeral=True)
            out = self.scratch_dir / "discord_screenshot.png"
            try:
                path = self.agent.capture_screenshot(out)
                if self.control_channel_id > 0:
                    await self._send_outbound(
                        OutboundMessage(
                            channel_id=self.control_channel_id,
                            content="Screenshot:",
                            file_path=path,
                            filename=path.name,
                        )
                    )
                    await interaction.followup.send(
                        content=f"Posted to control channel <#{self.control_channel_id}>.",
                        ephemeral=True,
                    )
                else:
                    await interaction.followup.send(
                        content="Screenshot:",
                        file=discord.File(fp=str(path), filename=path.name),
                        ephemeral=True,
                    )
            except Exception as exc:
                await interaction.followup.send(f"Screenshot failed: {exc}", ephemeral=True)

        return screenshot_cmd

    def _cmd_thinking(self) -> app_commands.Command:
        @app_commands.command(name="thinking", description="Set Gemini thinking level (low|high).")
        @app_commands.describe(level="Thinking level")
        async def thinking_cmd(interaction: discord.Interaction, level: str) -> None:
            level = level.lower().strip()
            if level not in ("low", "high"):
                await interaction.response.send_message("Level must be 'low' or 'high'.", ephemeral=True)
                return
            self.agent.set_thinking_level(level)
            await interaction.response.send_message(f"Thinking level set to {level}.")

        return thinking_cmd
