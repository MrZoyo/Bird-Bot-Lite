from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..utils import ensure_admin_channel


class RoomControlPanelView(discord.ui.View):
    def __init__(
        self,
        bot: commands.Bot,
        voice_channel_id: int,
        creator_id: int,
        room_visibility: str,
        soundboard_enabled: bool,
    ):
        super().__init__(timeout=None)
        self.bot = bot
        self.voice_channel_id = voice_channel_id
        self.creator_id = creator_id
        self.room_visibility = room_visibility
        self.soundboard_enabled = soundboard_enabled
        self.panel_messages = self.bot.config_store.messages["rooms"]["control_panel"]

        unlock_button = discord.ui.Button(
            style=discord.ButtonStyle.success,
            label=self.panel_messages["buttons"]["unlock"],
            custom_id=f"room_unlock_{voice_channel_id}",
        )
        unlock_button.callback = self.unlock_callback
        self.add_item(unlock_button)

        lock_button = discord.ui.Button(
            style=discord.ButtonStyle.primary,
            label=self.panel_messages["buttons"]["lock"],
            custom_id=f"room_lock_{voice_channel_id}",
        )
        lock_button.callback = self.lock_callback
        self.add_item(lock_button)

        full_button = discord.ui.Button(
            style=discord.ButtonStyle.danger,
            label=self.panel_messages["buttons"]["full"],
            custom_id=f"room_full_{voice_channel_id}",
        )
        full_button.callback = self.full_callback
        self.add_item(full_button)

        soundboard_button = discord.ui.Button(
            style=discord.ButtonStyle.secondary,
            label=self.panel_messages["buttons"]["soundboard"],
            custom_id=f"room_soundboard_{voice_channel_id}",
        )
        soundboard_button.callback = self.soundboard_callback
        self.add_item(soundboard_button)

    def create_embed(self) -> discord.Embed:
        soundboard_status = (
            self.panel_messages["soundboard_enabled_text"]
            if self.soundboard_enabled
            else self.panel_messages["soundboard_disabled_text"]
        )
        embed = discord.Embed(
            title=self.panel_messages["title"],
            description=self.panel_messages["description"].format(
                owner_mention=f"<@{self.creator_id}>",
                soundboard_status=soundboard_status,
            ),
            color=self.bot.config_store.color(
                "room_public" if self.room_visibility == "public" else "room_private"
            ),
        )
        if self.bot.user and self.bot.user.avatar:
            embed.set_thumbnail(url=self.bot.user.avatar.url)
        embed.set_footer(text=self.panel_messages["footer"])
        return embed

    async def _fetch_voice_channel(self) -> discord.VoiceChannel | None:
        channel = self.bot.get_channel(self.voice_channel_id)
        return channel if isinstance(channel, discord.VoiceChannel) else None

    async def _ensure_member_inside(self, interaction: discord.Interaction) -> bool:
        voice = getattr(interaction.user, "voice", None)
        return voice is not None and voice.channel is not None and voice.channel.id == self.voice_channel_id

    async def unlock_callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._ensure_member_inside(interaction):
            await interaction.followup.send(self.panel_messages["responses"]["not_in_voice"], ephemeral=True)
            return

        channel = await self._fetch_voice_channel()
        if channel is None:
            await interaction.followup.send(self.panel_messages["responses"]["channel_not_found"], ephemeral=True)
            return

        try:
            overwrites = channel.overwrites_for(channel.guild.default_role)
            overwrites.connect = True
            await channel.set_permissions(channel.guild.default_role, overwrite=overwrites)
            self.room_visibility = "public"
            await self.bot.repository.update_temp_room_visibility(channel.id, "public")
            await interaction.message.edit(embed=self.create_embed(), view=self)
            await interaction.followup.send(self.panel_messages["responses"]["unlock_success"], ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send(self.panel_messages["responses"]["permission_error"], ephemeral=True)

    async def lock_callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._ensure_member_inside(interaction):
            await interaction.followup.send(self.panel_messages["responses"]["not_in_voice"], ephemeral=True)
            return

        channel = await self._fetch_voice_channel()
        if channel is None:
            await interaction.followup.send(self.panel_messages["responses"]["channel_not_found"], ephemeral=True)
            return

        try:
            overwrites = channel.overwrites_for(channel.guild.default_role)
            overwrites.connect = False
            await channel.set_permissions(channel.guild.default_role, overwrite=overwrites)
            self.room_visibility = "private"
            await self.bot.repository.update_temp_room_visibility(channel.id, "private")
            await interaction.message.edit(embed=self.create_embed(), view=self)
            await interaction.followup.send(self.panel_messages["responses"]["lock_success"], ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send(self.panel_messages["responses"]["permission_error"], ephemeral=True)

    async def full_callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._ensure_member_inside(interaction):
            await interaction.followup.send(self.panel_messages["responses"]["not_in_voice"], ephemeral=True)
            return

        teamup_post = await self.bot.repository.get_last_teamup_post(self.voice_channel_id)
        if teamup_post is None:
            await interaction.followup.send(self.panel_messages["responses"]["full_no_invitation"], ephemeral=True)
            return

        channel = self.bot.get_channel(int(teamup_post["invitation_channel_id"])) if teamup_post.get(
            "invitation_channel_id"
        ) else None
        if channel is None:
            await interaction.followup.send(
                self.panel_messages["responses"]["full_channel_not_found"],
                ephemeral=True,
            )
            return

        try:
            message = await channel.fetch_message(int(teamup_post["invitation_message_id"]))
        except discord.NotFound:
            await self.bot.repository.remove_teamup_posts_by_voice_channel(self.voice_channel_id)
            await interaction.followup.send(self.panel_messages["responses"]["full_message_deleted"], ephemeral=True)
            return
        except discord.Forbidden:
            await interaction.followup.send(self.panel_messages["responses"]["full_no_permission"], ephemeral=True)
            return

        teamup_cog = self.bot.get_cog("TeamupCog")
        if teamup_cog is None:
            await interaction.followup.send(self.panel_messages["responses"]["full_error"], ephemeral=True)
            return

        await teamup_cog.update_message_to_full(message)
        await self.bot.repository.remove_teamup_posts_by_voice_channel(self.voice_channel_id)
        board_cog = self.bot.get_cog("TeamupBoardCog")
        if board_cog is not None:
            await board_cog.refresh_all_boards()
        await interaction.followup.send(self.panel_messages["responses"]["full_success"], ephemeral=True)

    async def soundboard_callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if interaction.user.id != self.creator_id:
            await interaction.followup.send(self.panel_messages["responses"]["not_room_owner"], ephemeral=True)
            return

        channel = await self._fetch_voice_channel()
        if channel is None:
            await interaction.followup.send(self.panel_messages["responses"]["channel_not_found"], ephemeral=True)
            return

        try:
            overwrites = channel.overwrites_for(channel.guild.default_role)
            new_state = not self.soundboard_enabled
            overwrites.use_soundboard = new_state
            await channel.set_permissions(channel.guild.default_role, overwrite=overwrites)
            self.soundboard_enabled = new_state
            await self.bot.repository.update_temp_room_soundboard(channel.id, new_state)
            await interaction.message.edit(embed=self.create_embed(), view=self)
            key = "soundboard_enabled" if new_state else "soundboard_disabled"
            await interaction.followup.send(self.panel_messages["responses"][key], ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send(self.panel_messages["responses"]["permission_error"], ephemeral=True)


class RoomCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.messages = bot.config_store.messages
        self.settings = bot.config_store.settings
        self.template_map = self._build_template_map()
        self.cleanup_rooms.change_interval(
            minutes=int(self.settings["rooms"]["cleanup_interval_minutes"])
        )
        self.cleanup_rooms.start()

    def cog_unload(self) -> None:
        self.cleanup_rooms.cancel()

    def _build_template_map(self) -> dict[int, dict[str, str]]:
        return {
            int(item["channel_id"]): {
                "name_prefix": str(item["name_prefix"]),
                "visibility": str(item["visibility"]),
            }
            for item in self.bot.config_store.room_templates()
        }

    def _save_templates(self) -> None:
        templates = [
            {
                "channel_id": channel_id,
                "name_prefix": item["name_prefix"],
                "visibility": item["visibility"],
            }
            for channel_id, item in sorted(self.template_map.items())
        ]
        self.bot.config_store.set_room_templates(templates)

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        await self.cleanup_stale_rooms()
        await self.restore_control_panels()

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if after.channel and after.channel.id in self.template_map:
            template = self.template_map[after.channel.id]
            await self.create_temp_room(member, after.channel, template)

        if before.channel:
            await self.cleanup_empty_room(before.channel.id)

    async def create_temp_room(
        self,
        member: discord.Member,
        template_channel: discord.VoiceChannel,
        template: dict[str, str],
    ) -> None:
        fallback_name = f"{template['name_prefix']}-{self.settings['rooms']['blocked_name_fallback_suffix']}"
        preferred_name = f"{template['name_prefix']}-{member.display_name}"
        visibility = template["visibility"]
        public = visibility == "public"

        overwrites = {
            member.guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                connect=public,
                use_soundboard=True,
            ),
            member: discord.PermissionOverwrite(
                manage_channels=True,
                view_channel=True,
                connect=True,
                speak=True,
                move_members=True,
            ),
        }

        target_channel = await self._create_voice_channel(template_channel, preferred_name, fallback_name, overwrites)
        if target_channel is None:
            return

        try:
            await member.move_to(target_channel)
        except (discord.HTTPException, discord.NotFound):
            await target_channel.delete(reason="Cleanup unused room after move failure")
            if target_channel.category and not target_channel.category.channels:
                await target_channel.category.delete(reason="Cleanup empty temp category")
            return

        await self.bot.repository.add_temp_room(
            channel_id=target_channel.id,
            creator_id=member.id,
            template_channel_id=template_channel.id,
            room_visibility=visibility,
        )

        await asyncio.sleep(0.5)
        await self.send_control_panel(target_channel, member.id, visibility)

    async def _create_voice_channel(
        self,
        template_channel: discord.VoiceChannel,
        preferred_name: str,
        fallback_name: str,
        overwrites: dict[object, discord.PermissionOverwrite],
    ) -> discord.VoiceChannel | None:
        guild = template_channel.guild
        category = template_channel.category

        if category is None:
            try:
                return await guild.create_voice_channel(preferred_name, overwrites=overwrites)
            except discord.HTTPException as exc:
                if exc.code == 50035 and "Contains words not allowed" in str(exc):
                    return await guild.create_voice_channel(fallback_name, overwrites=overwrites)
                raise

        categories = [item for item in guild.categories if item.name == category.name]
        categories.sort(key=lambda item: item.position)

        for target_category in categories:
            try:
                return await guild.create_voice_channel(
                    preferred_name,
                    category=target_category,
                    overwrites=overwrites,
                )
            except discord.HTTPException as exc:
                if exc.code == 50035 and "Contains words not allowed" in str(exc):
                    try:
                        return await guild.create_voice_channel(
                            fallback_name,
                            category=target_category,
                            overwrites=overwrites,
                        )
                    except discord.HTTPException as inner_exc:
                        if inner_exc.code == 50035 and "Maximum number of channels" in str(inner_exc):
                            continue
                        raise
                if exc.code == 50035 and "Maximum number of channels" in str(exc):
                    continue
                raise

        new_category = await guild.create_category(category.name, position=category.position)
        try:
            return await guild.create_voice_channel(
                preferred_name,
                category=new_category,
                overwrites=overwrites,
            )
        except discord.HTTPException as exc:
            if exc.code == 50035 and "Contains words not allowed" in str(exc):
                return await guild.create_voice_channel(
                    fallback_name,
                    category=new_category,
                    overwrites=overwrites,
                )
            raise

    async def send_control_panel(
        self,
        voice_channel: discord.VoiceChannel,
        creator_id: int,
        room_visibility: str,
        soundboard_enabled: bool = True,
    ) -> None:
        view = RoomControlPanelView(
            bot=self.bot,
            voice_channel_id=voice_channel.id,
            creator_id=creator_id,
            room_visibility=room_visibility,
            soundboard_enabled=soundboard_enabled,
        )
        message = await voice_channel.send(embed=view.create_embed(), view=view)
        await self.bot.repository.update_control_panel_message(voice_channel.id, message.id, voice_channel.id)
        logging.getLogger("rooms.activity").info("Control panel sent for room %s", voice_channel.id)

    async def cleanup_empty_room(self, channel_id: int) -> None:
        tracked_rooms = {room["channel_id"] for room in await self.bot.repository.list_temp_rooms()}
        if channel_id not in tracked_rooms:
            return

        channel = self.bot.get_channel(channel_id)
        if channel is None:
            await self.bot.repository.remove_temp_room(channel_id)
            return
        if channel.members:
            return

        await self.bot.repository.remove_temp_room(channel_id)
        await self.bot.repository.remove_teamup_posts_by_voice_channel(channel_id)
        board_cog = self.bot.get_cog("TeamupBoardCog")
        if board_cog is not None:
            await board_cog.refresh_all_boards()

        await channel.delete(reason="Temporary room cleanup")
        await asyncio.sleep(0.2)
        if channel.category and not channel.category.channels:
            await channel.category.delete(reason="Cleanup empty temp category")

    async def cleanup_stale_rooms(self) -> None:
        rooms = await self.bot.repository.list_temp_rooms()
        for room in rooms:
            channel = self.bot.get_channel(int(room["channel_id"]))
            if channel is None:
                await self.bot.repository.remove_temp_room(int(room["channel_id"]))
            elif not channel.members:
                await self.cleanup_empty_room(channel.id)

    async def restore_control_panels(self) -> None:
        rooms = await self.bot.repository.list_temp_rooms()
        for room in rooms:
            message_id = room.get("control_panel_message_id")
            if not message_id:
                continue

            voice_channel = self.bot.get_channel(int(room["channel_id"]))
            if not isinstance(voice_channel, discord.VoiceChannel):
                continue

            try:
                message = await voice_channel.fetch_message(int(message_id))
            except discord.NotFound:
                await self.bot.repository.clear_control_panel_message(int(room["channel_id"]))
                continue
            except discord.Forbidden:
                continue

            view = RoomControlPanelView(
                bot=self.bot,
                voice_channel_id=int(room["channel_id"]),
                creator_id=int(room["creator_id"]),
                room_visibility=str(room["room_visibility"]),
                soundboard_enabled=bool(room["soundboard_enabled"]),
            )
            await message.edit(embed=view.create_embed(), view=view)

    @tasks.loop(minutes=60)
    async def cleanup_rooms(self) -> None:
        await self.cleanup_stale_rooms()

    @cleanup_rooms.before_loop
    async def before_cleanup(self) -> None:
        await self.bot.wait_until_ready()

    @app_commands.command(name="check_temp_channel_records", description="查看当前临时房间记录")
    async def check_temp_channel_records(
        self,
        interaction: discord.Interaction,
        limit: app_commands.Range[int, 1, 50] = 20,
    ) -> None:
        allowed = await ensure_admin_channel(
            interaction,
            self.bot.config_store.admin_channel_id,
            self.messages["common"]["command_restricted"],
        )
        if not allowed:
            return

        await interaction.response.defer(ephemeral=True)
        records = await self.bot.repository.list_temp_room_records(limit)
        embed = discord.Embed(
            title=self.messages["rooms"]["commands"]["temp_records_title"],
            color=self.bot.config_store.color("info"),
        )
        if not records:
            embed.description = self.messages["rooms"]["commands"]["temp_records_empty"]
        else:
            lines = [
                self.messages["rooms"]["commands"]["temp_records_line"].format(
                    created_at=record["created_at"],
                    channel_id=record["channel_id"],
                    creator_id=record["creator_id"],
                )
                for record in records
            ]
            embed.description = "\n\n".join(lines)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="vc_list", description="查看所有建房入口配置")
    async def vc_list(self, interaction: discord.Interaction) -> None:
        allowed = await ensure_admin_channel(
            interaction,
            self.bot.config_store.admin_channel_id,
            self.messages["common"]["command_restricted"],
        )
        if not allowed:
            return

        await interaction.response.defer(ephemeral=True)
        embed = discord.Embed(
            title=self.messages["rooms"]["commands"]["template_list_title"],
            color=self.bot.config_store.color("info"),
        )
        if not self.template_map:
            embed.description = self.messages["rooms"]["commands"]["template_list_empty"]
        else:
            lines = []
            for channel_id, template in sorted(self.template_map.items()):
                channel = self.bot.get_channel(channel_id)
                channel_ref = channel.mention if channel else f"<#{channel_id}>"
                lines.append(
                    self.messages["rooms"]["commands"]["template_list_line"].format(
                        channel_ref=channel_ref,
                        name_prefix=template["name_prefix"],
                        visibility=template["visibility"],
                    )
                )
            embed.description = "\n".join(lines)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="vc_add", description="添加一个建房入口语音频道")
    @app_commands.choices(
        visibility=[
            app_commands.Choice(name="公开", value="public"),
            app_commands.Choice(name="私密", value="private"),
        ]
    )
    async def vc_add(
        self,
        interaction: discord.Interaction,
        channel: discord.VoiceChannel,
        name_prefix: app_commands.Range[str, 1, 20],
        visibility: app_commands.Choice[str],
    ) -> None:
        allowed = await ensure_admin_channel(
            interaction,
            self.bot.config_store.admin_channel_id,
            self.messages["common"]["command_restricted"],
        )
        if not allowed:
            return

        if channel.id in self.template_map:
            await interaction.response.send_message(
                self.messages["rooms"]["commands"]["template_exists"],
                ephemeral=True,
            )
            return

        self.template_map[channel.id] = {
            "name_prefix": name_prefix,
            "visibility": visibility.value,
        }
        self._save_templates()
        await interaction.response.send_message(
            self.messages["rooms"]["commands"]["template_added_body"].format(
                channel_mention=channel.mention
            ),
            ephemeral=True,
        )

    @app_commands.command(name="vc_remove", description="移除一个建房入口语音频道")
    async def vc_remove(
        self,
        interaction: discord.Interaction,
        channel: discord.VoiceChannel | None = None,
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

        if target_channel_id not in self.template_map:
            await interaction.response.send_message(
                self.messages["rooms"]["commands"]["template_missing"],
                ephemeral=True,
            )
            return

        del self.template_map[target_channel_id]
        self._save_templates()
        channel_ref = channel.mention if channel else f"<#{target_channel_id}>"
        await interaction.response.send_message(
            self.messages["rooms"]["commands"]["template_removed_body"].format(channel_ref=channel_ref),
            ephemeral=True,
        )
