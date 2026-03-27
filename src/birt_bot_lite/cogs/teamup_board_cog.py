from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..utils import ensure_admin_channel


class TeamupBoardCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.messages = self.bot.config_store.messages
        self.settings = self.bot.config_store.settings
        self.refresh_boards.change_interval(
            minutes=int(self.settings["teamup_board"]["refresh_interval_minutes"])
        )
        self.refresh_boards.start()

    def cog_unload(self) -> None:
        self.refresh_boards.cancel()

    @tasks.loop(minutes=2)
    async def refresh_boards(self) -> None:
        cleaned = await self.bot.repository.cleanup_expired_teamup_posts()
        if cleaned:
            logging.getLogger("rooms.activity").info("Cleaned %s expired teamup posts", cleaned)
        await self.refresh_all_boards()

    @refresh_boards.before_loop
    async def before_refresh(self) -> None:
        await self.bot.wait_until_ready()

    async def refresh_all_boards(self) -> None:
        boards = await self.bot.repository.list_boards()
        for channel_id, message_id in boards:
            await self.update_board(channel_id, message_id)

    async def update_board(self, channel_id: int, message_id: int) -> None:
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            await self.bot.repository.remove_board(channel_id)
            return

        try:
            message = await channel.fetch_message(message_id)
        except discord.NotFound:
            await self.bot.repository.remove_board(channel_id)
            return
        except discord.Forbidden:
            logging.warning("No permission to edit teamup board message %s", message_id)
            return

        embed = await self.create_board_embed()
        await message.edit(embed=embed)

    async def create_board_embed(self) -> discord.Embed:
        board_messages = self.messages["board"]
        embed = discord.Embed(
            title=board_messages["display_title"],
            color=self.bot.config_store.color("board"),
        )

        posts = await self.bot.repository.get_active_teamup_posts()
        if not posts:
            embed.description = board_messages["no_teamup_message"]
        else:
            game_types = await self.bot.repository.list_game_types()
            grouped: dict[str, list[str]] = {}
            general_lines: list[str] = []

            for post in posts:
                line = await self.format_post_line(post)
                if not line:
                    continue
                game_type = post.get("game_type")
                if game_type and game_type in game_types.values():
                    grouped.setdefault(game_type, []).append(line)
                else:
                    general_lines.append(line)

            chunks: list[str] = []
            for _, game_type in game_types.items():
                lines = grouped.get(game_type)
                if not lines:
                    continue
                chunks.append(f"**{game_type}**")
                chunks.append("\n\n".join(lines))

            if general_lines:
                chunks.append(f"**{board_messages['general_teamup_title']}**")
                chunks.append("\n\n".join(general_lines))

            embed.description = "\n\n".join(chunks) if chunks else board_messages["no_teamup_message"]

        if self.bot.user and self.bot.user.avatar:
            embed.set_footer(text=board_messages["footer_text"], icon_url=self.bot.user.avatar.url)
        else:
            embed.set_footer(text=board_messages["footer_text"])

        return embed

    async def format_post_line(self, post: dict[str, object]) -> str:
        voice_channel = self.bot.get_channel(int(post["voice_channel_id"]))
        if voice_channel is None:
            await self.bot.repository.remove_teamup_posts_by_voice_channel(int(post["voice_channel_id"]))
            return ""

        content = str(post["message_content"])
        content = re.sub(r"<@\d+>", "", content)
        content = re.sub(r"<@&\d+>", "", content)
        max_length = int(self.settings["teamup_board"].get("max_content_length", 50))
        if len(content) > max_length:
            content = content[: max_length - 3] + "..."

        created_at = datetime.strptime(str(post["created_at"]), "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
        time_ago = discord.utils.format_dt(created_at, style="R")
        channel_link = f"https://discord.com/channels/{voice_channel.guild.id}/{voice_channel.id}"
        line_messages = self.messages["board"]["invitation_lines"]
        emojis = self.messages["board"]["emojis"]

        return "\n".join(
            [
                line_messages["title_line"].format(
                    search_emoji=emojis["search"],
                    content=content,
                ),
                line_messages["meta_line"].format(
                    players_emoji=emojis["players"],
                    player_count=len(voice_channel.members),
                    time_emoji=emojis["time"],
                    time_ago=time_ago,
                ),
                line_messages["link_line"].format(
                    link_emoji=emojis["link"],
                    channel_link=channel_link,
                ),
            ]
        )

    @app_commands.command(name="teamup_init", description="在指定频道创建组队展示板")
    async def teamup_init(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        allowed = await ensure_admin_channel(
            interaction,
            self.bot.config_store.admin_channel_id,
            self.messages["common"]["command_restricted"],
        )
        if not allowed:
            return

        await interaction.response.defer(ephemeral=True)
        bot_member = interaction.guild.me or interaction.guild.get_member(self.bot.user.id)
        permissions = channel.permissions_for(bot_member)
        if not permissions.send_messages or not permissions.read_message_history:
            await interaction.followup.send(self.messages["board"]["permission_error"], ephemeral=True)
            return

        embed = await self.create_board_embed()
        message = await channel.send(embed=embed)
        await self.bot.repository.save_board(channel.id, message.id)
        await interaction.followup.send(self.messages["board"]["init_success"], ephemeral=True)

    @app_commands.command(name="teamup_type_add", description="将频道标记为某个游戏类型")
    async def teamup_type_add(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        game_type: str,
    ) -> None:
        allowed = await ensure_admin_channel(
            interaction,
            self.bot.config_store.admin_channel_id,
            self.messages["common"]["command_restricted"],
        )
        if not allowed:
            return

        await interaction.response.defer(ephemeral=True)
        await self.bot.repository.add_game_type(channel.id, game_type)
        await self.refresh_all_boards()
        await interaction.followup.send(
            self.messages["board"]["channel_set_as_type"].format(
                channel_mention=channel.mention,
                game_type=game_type,
            ),
            ephemeral=True,
        )

    @app_commands.command(name="teamup_type_delete", description="删除某个频道的游戏类型")
    async def teamup_type_delete(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
        channel_id: str | None = None,
    ) -> None:
        allowed = await ensure_admin_channel(
            interaction,
            self.bot.config_store.admin_channel_id,
            self.messages["common"]["command_restricted"],
        )
        if not allowed:
            return

        if channel is None and channel_id is None:
            await interaction.response.send_message(self.messages["common"]["invalid_channel_id"], ephemeral=True)
            return

        target_channel_id: int
        if channel_id is not None:
            try:
                target_channel_id = int(channel_id)
            except ValueError:
                await interaction.response.send_message(self.messages["common"]["invalid_channel_id"], ephemeral=True)
                return
        else:
            target_channel_id = channel.id

        await interaction.response.defer(ephemeral=True)
        await self.bot.repository.remove_game_type(target_channel_id)
        await self.refresh_all_boards()
        await interaction.followup.send(
            self.messages["board"]["channel_type_deleted"].format(channel_id=target_channel_id),
            ephemeral=True,
        )

    @app_commands.command(name="teamup_type_list", description="查看所有游戏类型配置")
    async def teamup_type_list(self, interaction: discord.Interaction) -> None:
        allowed = await ensure_admin_channel(
            interaction,
            self.bot.config_store.admin_channel_id,
            self.messages["common"]["command_restricted"],
        )
        if not allowed:
            return

        await interaction.response.defer(ephemeral=True)
        embed = discord.Embed(
            title=self.messages["board"]["type_list_title"],
            color=self.bot.config_store.color("info"),
        )

        game_types = await self.bot.repository.list_game_types()
        if not game_types:
            embed.description = self.messages["board"]["type_list_empty"]
        else:
            lines = []
            for channel_id, game_type in game_types.items():
                channel = self.bot.get_channel(channel_id)
                channel_ref = channel.mention if channel else f"<#{channel_id}> {self.messages['board']['channel_not_exist']}"
                lines.append(f"• **{game_type}** - {channel_ref}")
            embed.description = "\n".join(lines)

        await interaction.followup.send(embed=embed, ephemeral=True)
