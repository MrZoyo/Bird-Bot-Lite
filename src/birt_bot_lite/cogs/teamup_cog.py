from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands
from discord.utils import format_dt

from ..utils import ensure_admin_channel


class DefaultRoomView(discord.ui.View):
    def __init__(self, label: str, url: str):
        super().__init__(timeout=600)
        self.add_item(discord.ui.Button(style=discord.ButtonStyle.link, label=label, url=url))


class TeamInvitationView(discord.ui.View):
    def __init__(self, bot: commands.Bot, channel: discord.VoiceChannel, user_id: int):
        super().__init__(timeout=600)
        self.bot = bot
        self.channel = channel
        self.user_id = user_id
        invitation_messages = self.bot.config_store.messages["teamup"]["invitation"]
        self.responses = self.bot.config_store.messages["teamup"]["responses"]

        self.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.link,
                label=invitation_messages["invite_button"],
                url=f"https://discord.com/channels/{channel.guild.id}/{channel.id}",
            )
        )

        room_full_button = discord.ui.Button(
            style=discord.ButtonStyle.danger,
            label=invitation_messages["room_full_button"],
            custom_id=f"teamup_full_{channel.id}",
        )
        room_full_button.callback = self.room_full_callback
        self.add_item(room_full_button)

    async def room_full_callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        if interaction.user.id != self.user_id:
            await interaction.followup.send(self.responses["interaction_target_error"], ephemeral=True)
            return

        voice_channel_id = TeamupCog.extract_voice_channel_id(interaction.message.embeds[0].description or "")
        if voice_channel_id is None:
            await interaction.followup.send(self.responses["extract_channel_id_error"], ephemeral=True)
            return

        user_voice = getattr(interaction.user, "voice", None)
        if user_voice is None or user_voice.channel is None or user_voice.channel.id != voice_channel_id:
            await interaction.followup.send(self.responses["not_in_vc"], ephemeral=True)
            return

        teamup_cog = self.bot.get_cog("TeamupCog")
        if teamup_cog is None:
            await interaction.followup.send(self.bot.config_store.messages["common"]["internal_error"], ephemeral=True)
            return

        await teamup_cog.update_message_to_full(interaction.message)
        await self.bot.repository.remove_teamup_posts_by_voice_channel(voice_channel_id)

        board_cog = self.bot.get_cog("TeamupBoardCog")
        if board_cog is not None:
            await board_cog.refresh_all_boards()

        await interaction.followup.send(self.responses["room_full_set"], ephemeral=True)


class TeamupCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.messages = bot.config_store.messages
        self.settings = bot.config_store.settings
        self.keyword_pattern = re.compile(
            str(self.settings["teamup"]["keyword_detection"]["regex"]),
            re.IGNORECASE,
        )

    @staticmethod
    def extract_voice_channel_id(text: str) -> int | None:
        match = re.search(r"https://discord.com/channels/\d+/(\d+)", text)
        return int(match.group(1)) if match else None

    def should_ignore_short_message(self, content: str) -> bool:
        rules = self.settings["teamup"]["ignore_short_messages"]
        if not rules.get("enabled", True):
            return False
        if len(content) != int(rules["exact_length"]):
            return False
        if re.search(r"[=＝\s]", content):
            return False
        allow_keywords = [keyword.lower() for keyword in rules["allow_keywords"]]
        lowered = content.lower()
        if any(keyword in lowered for keyword in allow_keywords):
            return False
        if re.search(r"[\u4e00-\u9FFF]", content):
            return False
        return True

    async def build_invitation_embed(
        self,
        author: discord.abc.User,
        voice_channel: discord.VoiceChannel,
        title: str,
    ) -> discord.Embed:
        invitation_messages = self.messages["teamup"]["invitation"]
        signature_record = await self.bot.repository.get_signature(author.id)
        signature = None
        if signature_record and not bool(signature_record["is_disabled"]):
            signature = signature_record["signature"]

        current_time = discord.utils.utcnow()
        embed = discord.Embed(
            title=title[:256],
            description=invitation_messages["description"].format(
                vc_url=f"https://discord.com/channels/{voice_channel.guild.id}/{voice_channel.id}",
                mention=author.mention,
                time=format_dt(current_time, style="R"),
            ),
            color=self.bot.config_store.color("info"),
        )

        if signature:
            embed.add_field(name="", value=str(signature), inline=False)

        avatar = getattr(author, "avatar", None)
        if avatar:
            embed.set_thumbnail(url=avatar.url)
        elif self.bot.user and self.bot.user.avatar:
            embed.set_thumbnail(url=self.bot.user.avatar.url)

        embed.timestamp = current_time
        embed.set_footer(text=invitation_messages["footer"])
        return embed

    async def update_message_to_full(self, message: discord.Message) -> None:
        if not message.embeds:
            return

        invitation_messages = self.messages["teamup"]["invitation"]
        original = message.embeds[0]
        description = original.description or ""
        voice_channel_id = self.extract_voice_channel_id(description)

        new_description = description
        if voice_channel_id is not None:
            voice_channel = self.bot.get_channel(voice_channel_id)
            channel_name = voice_channel.name if voice_channel else "未知频道"
            guild_id_match = re.search(r"https://discord.com/channels/(\d+)/\d+", description)
            guild_id = guild_id_match.group(1) if guild_id_match else ""
            url = f"https://discord.com/channels/{guild_id}/{voice_channel_id}"
            mention_match = re.search(r"<@\d+>", description)
            mention = mention_match.group(0) if mention_match else ""
            time_match = re.search(r"<t:\d+:R>", description)
            time_text = time_match.group(0) if time_match else ""
            new_description = invitation_messages["full_description"].format(
                name=channel_name,
                url=url,
                mention=mention,
                time=time_text,
            )

        embed = discord.Embed(
            title=f"{invitation_messages['full_title_prefix']} ~~{original.title or ''}~~",
            description=new_description,
            color=self.bot.config_store.color("danger"),
        )
        for field in original.fields:
            embed.add_field(name=field.name, value=field.value, inline=field.inline)
        if original.thumbnail:
            embed.set_thumbnail(url=original.thumbnail.url)

        await message.edit(embed=embed, view=None)

    async def mark_old_post_full(self, post: dict[str, Any]) -> None:
        invitation_channel_id = post.get("invitation_channel_id")
        invitation_message_id = post.get("invitation_message_id")
        if not invitation_channel_id or not invitation_message_id:
            return

        channel = self.bot.get_channel(int(invitation_channel_id))
        if channel is None:
            return

        try:
            message = await channel.fetch_message(int(invitation_message_id))
        except (discord.NotFound, discord.Forbidden):
            return

        await self.update_message_to_full(message)

    async def refresh_boards(self) -> None:
        board_cog = self.bot.get_cog("TeamupBoardCog")
        if board_cog is not None:
            await board_cog.refresh_all_boards()

    def build_default_room_view(self, guild_id: int) -> DefaultRoomView:
        invitation_messages = self.messages["teamup"]["invitation"]
        default_channel_id = int(self.settings["teamup"]["default_create_room_channel_id"])
        url = f"https://discord.com/channels/{guild_id}/{default_channel_id}"
        return DefaultRoomView(invitation_messages["create_room_button"], url)

    async def create_teamup_message(
        self,
        author: discord.Member | discord.User,
        voice_channel: discord.VoiceChannel,
        title: str,
        source_channel_id: int,
        send_callable,
    ) -> None:
        old_post = await self.bot.repository.get_last_teamup_post(voice_channel.id)
        embed = await self.build_invitation_embed(author, voice_channel, title)
        view = TeamInvitationView(self.bot, voice_channel, author.id)
        new_message = await send_callable(embed=embed, view=view)

        game_type = await self.bot.repository.get_game_type(source_channel_id)
        post_id = await self.bot.repository.create_teamup_post(
            user_id=author.id,
            source_channel_id=source_channel_id,
            voice_channel_id=voice_channel.id,
            message_content=title,
            player_count=len(voice_channel.members),
            game_type=game_type,
            expire_minutes=int(self.settings["teamup"]["invite_expire_minutes"]),
        )
        await self.bot.repository.save_teamup_message(post_id, new_message.id, source_channel_id)
        await self.refresh_boards()

        if old_post is not None:
            asyncio.create_task(self.mark_old_post_full(old_post))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author == self.bot.user or message.author.bot:
            return

        if self.should_ignore_short_message(message.content):
            return

        if re.search(r"https?://", message.content):
            return

        ignore_user_ids = {int(user_id) for user_id in self.settings["teamup"]["ignore_user_ids"]}
        if message.author.id in ignore_user_ids:
            return

        matches = self.keyword_pattern.findall(message.content)
        valid_matches = [
            match for match in matches if not re.search(r"\d[A-Z]$", message.content, re.IGNORECASE)
        ]
        if not valid_matches:
            return

        ignore_channel_ids = set(self.bot.config_store.ignored_channel_ids())
        if message.channel.id in ignore_channel_ids:
            await message.reply(self.messages["teamup"]["responses"]["ignored_channel"], delete_after=10)
            return

        logging.getLogger("teamup.keyword").info(
            "Detected teamup content from %s: %s, matches=%s",
            message.author,
            message.content,
            valid_matches,
        )

        if message.author.voice and message.author.voice.channel:
            try:
                await self.create_teamup_message(
                    author=message.author,
                    voice_channel=message.author.voice.channel,
                    title=message.content[:256],
                    source_channel_id=message.channel.id,
                    send_callable=lambda **kwargs: message.reply(**kwargs),
                )
            except Exception as exc:
                logging.exception("Failed to create teamup reply: %s", exc)
                await message.reply(self.messages["teamup"]["responses"]["create_failed"])
            return

        await message.reply(
            self.messages["teamup"]["responses"]["illegal_team"].format(mention=message.author.mention),
            view=self.build_default_room_view(message.guild.id),
        )

    @app_commands.command(name="invt", description="手动发送一条组队邀请消息")
    async def invitation(self, interaction: discord.Interaction, title: str | None = None) -> None:
        await interaction.response.defer()

        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.followup.send(
                self.messages["teamup"]["responses"]["illegal_team"].format(
                    mention=interaction.user.mention
                ),
                view=self.build_default_room_view(interaction.guild.id),
            )
            return

        try:
            await self.create_teamup_message(
                author=interaction.user,
                voice_channel=interaction.user.voice.channel,
                title=(title or self.messages["teamup"]["invitation"]["default_title"])[:256],
                source_channel_id=interaction.channel.id,
                send_callable=lambda **kwargs: interaction.followup.send(wait=True, **kwargs),
            )
        except Exception as exc:
            logging.exception("Failed to create slash invitation: %s", exc)
            await interaction.followup.send(self.messages["teamup"]["responses"]["create_failed"])

    @app_commands.command(name="invt_checkignorelist", description="查看组队忽略频道列表")
    async def check_ignore_list(self, interaction: discord.Interaction) -> None:
        allowed = await ensure_admin_channel(
            interaction,
            self.bot.config_store.admin_channel_id,
            self.messages["common"]["command_restricted"],
        )
        if not allowed:
            return

        await interaction.response.defer(ephemeral=True)
        command_messages = self.messages["teamup"]["ignore_commands"]
        embed = discord.Embed(
            title=command_messages["list_title"],
            description=command_messages["list_description"],
            color=self.bot.config_store.color("info"),
        )

        ignored_channel_ids = self.bot.config_store.ignored_channel_ids()
        if not ignored_channel_ids:
            embed.add_field(name="Ignored", value=command_messages["list_empty"], inline=False)
        else:
            lines = []
            for channel_id in ignored_channel_ids:
                channel = self.bot.get_channel(channel_id)
                channel_ref = channel.mention if channel else f"<#{channel_id}>"
                lines.append(command_messages["list_line"].format(channel_ref=channel_ref))
            embed.add_field(name="Ignored", value="\n".join(lines), inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="invt_addignorelist", description="将频道加入组队忽略列表")
    async def add_ignore_list(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        allowed = await ensure_admin_channel(
            interaction,
            self.bot.config_store.admin_channel_id,
            self.messages["common"]["command_restricted"],
        )
        if not allowed:
            return

        ignored = self.bot.config_store.ignored_channel_ids()
        if channel.id in ignored:
            await interaction.response.send_message(
                self.messages["teamup"]["ignore_commands"]["already_ignored"].format(
                    channel_mention=channel.mention
                ),
                ephemeral=True,
            )
            return

        ignored.append(channel.id)
        ignored = sorted(set(ignored))
        self.bot.config_store.set_ignored_channel_ids(ignored)
        await interaction.response.send_message(
            self.messages["teamup"]["ignore_commands"]["add_success"].format(
                channel_mention=channel.mention
            ),
            ephemeral=True,
        )

    @app_commands.command(name="invt_removeignorelist", description="将频道移出组队忽略列表")
    async def remove_ignore_list(
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

        ignored = self.bot.config_store.ignored_channel_ids()
        if target_channel_id not in ignored:
            channel_ref = channel.mention if channel else f"<#{target_channel_id}>"
            await interaction.response.send_message(
                self.messages["teamup"]["ignore_commands"]["not_ignored"].format(channel_ref=channel_ref),
                ephemeral=True,
            )
            return

        ignored.remove(target_channel_id)
        self.bot.config_store.set_ignored_channel_ids(ignored)
        channel_ref = channel.mention if channel else f"<#{target_channel_id}>"
        await interaction.response.send_message(
            self.messages["teamup"]["ignore_commands"]["remove_success"].format(channel_ref=channel_ref),
            ephemeral=True,
        )

    @app_commands.command(name="signature_set", description="设置或更新你的个性签名")
    async def signature_set(self, interaction: discord.Interaction, text: str) -> None:
        max_length = int(self.settings["teamup"]["signature_max_length"])
        if len(text) > max_length:
            await interaction.response.send_message(
                f"签名最多只能有 {max_length} 个字符。",
                ephemeral=True,
            )
            return

        existing = await self.bot.repository.get_signature(interaction.user.id)
        if existing and bool(existing["is_disabled"]):
            await interaction.response.send_message(
                self.messages["teamup"]["signature"]["disabled"],
                ephemeral=True,
            )
            return

        await self.bot.repository.set_signature(interaction.user.id, text)
        await interaction.response.send_message(
            self.messages["teamup"]["signature"]["set_success"],
            ephemeral=True,
        )

    @app_commands.command(name="signature_clear", description="清空你的个性签名")
    async def signature_clear(self, interaction: discord.Interaction) -> None:
        await self.bot.repository.clear_signature(interaction.user.id)
        await interaction.response.send_message(
            self.messages["teamup"]["signature"]["clear_success"],
            ephemeral=True,
        )

    @app_commands.command(name="signature_view", description="查看某个成员的个性签名")
    async def signature_view(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
    ) -> None:
        target = member or interaction.user
        record = await self.bot.repository.get_signature(target.id)
        if record is None or not record.get("signature"):
            await interaction.response.send_message(
                self.messages["teamup"]["signature"]["empty"],
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title=self.messages["teamup"]["signature"]["view_title"],
            description=self.messages["teamup"]["signature"]["view_description"].format(
                member_mention=target.mention,
                signature=record["signature"],
            ),
            color=self.bot.config_store.color("info"),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="signature_toggle", description="管理员启用或禁用某个成员的个性签名")
    async def signature_toggle(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        disabled: bool,
    ) -> None:
        allowed = await ensure_admin_channel(
            interaction,
            self.bot.config_store.admin_channel_id,
            self.messages["common"]["command_restricted"],
        )
        if not allowed:
            return

        await self.bot.repository.set_signature_disabled(member.id, disabled)
        key = "toggle_disabled" if disabled else "toggle_enabled"
        await interaction.response.send_message(
            self.messages["teamup"]["signature"][key].format(member_mention=member.mention),
            ephemeral=True,
        )
