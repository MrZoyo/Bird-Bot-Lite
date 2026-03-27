from __future__ import annotations

import discord


async def ensure_admin_channel(interaction: discord.Interaction, admin_channel_id: int, message: str) -> bool:
    if interaction.channel_id == admin_channel_id:
        return True
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)
    return False


def in_voice_channel(user: discord.abc.User) -> bool:
    voice = getattr(user, "voice", None)
    return voice is not None and voice.channel is not None
