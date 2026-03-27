from __future__ import annotations

import logging
from pathlib import Path

import discord
from discord.ext import commands

from .config import ConfigStore
from .repository import LiteRepository


class LiteBot(commands.Bot):
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.config_store = ConfigStore(project_root)
        self.config_store.paths.data_dir.mkdir(parents=True, exist_ok=True)

        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.voice_states = True
        intents.message_content = True

        super().__init__(command_prefix="!", intents=intents)

        db_path = str(self.config_store.paths.data_dir / "birt_bot_lite.db")
        self.repository = LiteRepository(db_path)
        self.global_commands_synced = False

    async def setup_hook(self) -> None:
        from .cogs import RoomCog, TeamupBoardCog, TeamupCog

        configure_logging(self.config_store)
        await self.repository.initialize()

        await self.add_cog(TeamupBoardCog(self))
        await self.add_cog(TeamupCog(self))
        await self.add_cog(RoomCog(self))

    async def on_ready(self) -> None:
        guild_id = self.config_store.guild_id
        logging.info("Logged in as %s", self.user)

        for guild in self.guilds:
            if guild.id == guild_id:
                await self.change_presence(
                    activity=discord.Game(name=str(self.config_store.settings["discord"]["presence"]))
                )
                if not self.global_commands_synced:
                    synced = await self.tree.sync()
                    self.global_commands_synced = True
                    logging.info("Global commands synced: %s", len(synced))
            else:
                logging.info("Bot connected to non-target guild: %s", guild.name)


def configure_logging(config_store: ConfigStore) -> None:
    settings = config_store.settings["logging"]
    data_dir = config_store.paths.root

    logging.basicConfig(
        level=logging.INFO,
        filename=str((data_dir / str(settings["main_file"]).replace("./", "")).resolve()),
        filemode="a",
        format="%(asctime)s - %(levelname)s - %(message)s",
        encoding="utf-8",
        force=True,
    )

    keyword_logger = logging.getLogger("teamup.keyword")
    keyword_logger.handlers.clear()
    keyword_handler = logging.FileHandler(
        (data_dir / str(settings["keyword_file"]).replace("./", "")).resolve(),
        mode="a",
        encoding="utf-8",
    )
    keyword_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    keyword_logger.addHandler(keyword_handler)
    keyword_logger.setLevel(logging.INFO)
    keyword_logger.propagate = False

    room_logger = logging.getLogger("rooms.activity")
    room_logger.handlers.clear()
    room_handler = logging.FileHandler(
        (data_dir / str(settings["room_file"]).replace("./", "")).resolve(),
        mode="a",
        encoding="utf-8",
    )
    room_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    room_logger.addHandler(room_handler)
    room_logger.setLevel(logging.INFO)
    room_logger.propagate = False


def create_bot(project_root: Path) -> LiteBot:
    bot = LiteBot(project_root)

    @bot.command()
    async def synccommands(ctx: commands.Context) -> None:
        synced = await bot.tree.sync()
        await ctx.send(f"Commands synced: {len(synced)}")

    return bot


def run_bot(project_root: Path) -> None:
    bot = create_bot(project_root)
    bot.run(bot.config_store.token)
