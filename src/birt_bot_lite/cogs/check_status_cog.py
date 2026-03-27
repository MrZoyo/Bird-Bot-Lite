from __future__ import annotations

import io
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from ..utils import ensure_admin_channel


class CheckStatusCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.messages = bot.config_store.messages

    def _resolve_log_path(self, relative_path: str) -> Path:
        return (self.bot.config_store.paths.root / relative_path.replace("./", "")).resolve()

    @staticmethod
    def _normalize_log_type(log_type: str | None) -> str:
        log_type_map = {
            "1": "main",
            "2": "keyword",
            "3": "room",
            "main": "main",
            "keyword": "keyword",
            "room": "room",
        }
        return log_type_map.get((log_type or "main").lower(), "main")

    @app_commands.command(name="check_log", description="查看指定日志最后若干行")
    @app_commands.describe(
        x="从日志末尾返回多少行",
        log_type="日志类型：1/main、2/keyword、3/room，默认 main",
    )
    async def check_log(self, interaction: discord.Interaction, x: int, log_type: str = "main") -> None:
        allowed = await ensure_admin_channel(
            interaction,
            self.bot.config_store.admin_channel_id,
            self.messages["common"]["command_restricted"],
        )
        if not allowed:
            return

        if x <= 0:
            await interaction.response.send_message(self.messages["logs"]["invalid_line_count"], ephemeral=True)
            return

        normalized_type = self._normalize_log_type(log_type)
        logging_settings = self.bot.config_store.settings["logging"]
        log_config = {
            "main": {
                "file": self._resolve_log_path(str(logging_settings["main_file"])),
                "name": self.messages["logs"]["types"]["main"],
                "download_name": "main_log.txt",
            },
            "keyword": {
                "file": self._resolve_log_path(str(logging_settings["keyword_file"])),
                "name": self.messages["logs"]["types"]["keyword"],
                "download_name": "keyword_log.txt",
            },
            "room": {
                "file": self._resolve_log_path(str(logging_settings["room_file"])),
                "name": self.messages["logs"]["types"]["room"],
                "download_name": "room_log.txt",
            },
        }

        current = log_config[normalized_type]
        log_file = current["file"]
        log_type_name = current["name"]

        try:
            with log_file.open("r", encoding="utf-8") as handle:
                lines = handle.readlines()
        except FileNotFoundError:
            await interaction.response.send_message(
                self.messages["logs"]["file_missing"].format(log_type_name=log_type_name)
            )
            return

        if not lines:
            await interaction.response.send_message(
                self.messages["logs"]["file_empty"].format(log_type_name=log_type_name)
            )
            return

        last_x_lines = "".join(lines[-x:])
        if len(last_x_lines) > 1900:
            buffer = io.BytesIO(last_x_lines.encode("utf-8"))
            await interaction.response.send_message(
                self.messages["logs"]["too_long"].format(log_type_name=log_type_name),
                file=discord.File(buffer, filename=str(current["download_name"])),
            )
            return

        await interaction.response.send_message(
            self.messages["logs"]["inline_result"].format(
                log_type_name=log_type_name,
                x=x,
                content=last_x_lines,
            )
        )
