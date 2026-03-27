from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite


def utc_now_string() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class LiteRepository:
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def initialize(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS temp_rooms (
                    channel_id INTEGER PRIMARY KEY,
                    creator_id INTEGER NOT NULL,
                    template_channel_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    control_panel_message_id INTEGER,
                    control_panel_channel_id INTEGER,
                    soundboard_enabled INTEGER DEFAULT 1,
                    room_visibility TEXT DEFAULT 'public'
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS user_signatures (
                    user_id INTEGER PRIMARY KEY,
                    signature TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_disabled INTEGER DEFAULT 0
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS teamup_boards (
                    channel_id INTEGER PRIMARY KEY,
                    message_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS teamup_game_types (
                    channel_id INTEGER PRIMARY KEY,
                    game_type TEXT NOT NULL,
                    display_order INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS teamup_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    source_channel_id INTEGER NOT NULL,
                    voice_channel_id INTEGER NOT NULL,
                    message_content TEXT NOT NULL,
                    player_count INTEGER DEFAULT 1,
                    game_type TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP NOT NULL,
                    invitation_message_id INTEGER,
                    invitation_channel_id INTEGER
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_teamup_posts_voice_channel ON teamup_posts (voice_channel_id)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_teamup_posts_expires_at ON teamup_posts (expires_at)"
            )
            await db.commit()

    async def add_temp_room(
        self,
        channel_id: int,
        creator_id: int,
        template_channel_id: int,
        room_visibility: str,
    ) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO temp_rooms
                    (channel_id, creator_id, template_channel_id, soundboard_enabled, room_visibility)
                VALUES (?, ?, ?, 1, ?)
                """,
                (channel_id, creator_id, template_channel_id, room_visibility),
            )
            await db.commit()

    async def update_temp_room_visibility(self, channel_id: int, room_visibility: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE temp_rooms SET room_visibility = ? WHERE channel_id = ?",
                (room_visibility, channel_id),
            )
            await db.commit()

    async def update_temp_room_soundboard(self, channel_id: int, enabled: bool) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE temp_rooms SET soundboard_enabled = ? WHERE channel_id = ?",
                (1 if enabled else 0, channel_id),
            )
            await db.commit()

    async def update_control_panel_message(self, channel_id: int, message_id: int, message_channel_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE temp_rooms
                SET control_panel_message_id = ?, control_panel_channel_id = ?
                WHERE channel_id = ?
                """,
                (message_id, message_channel_id, channel_id),
            )
            await db.commit()

    async def clear_control_panel_message(self, channel_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE temp_rooms
                SET control_panel_message_id = NULL, control_panel_channel_id = NULL
                WHERE channel_id = ?
                """,
                (channel_id,),
            )
            await db.commit()

    async def remove_temp_room(self, channel_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM temp_rooms WHERE channel_id = ?", (channel_id,))
            await db.commit()

    async def list_temp_rooms(self) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT channel_id, creator_id, template_channel_id, created_at,
                       control_panel_message_id, control_panel_channel_id,
                       soundboard_enabled, room_visibility
                FROM temp_rooms
                ORDER BY created_at DESC
                """
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def list_temp_room_records(self, limit: int) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT channel_id, creator_id, created_at
                FROM temp_rooms
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def create_teamup_post(
        self,
        user_id: int,
        source_channel_id: int,
        voice_channel_id: int,
        message_content: str,
        player_count: int,
        game_type: str | None,
        expire_minutes: int,
    ) -> int:
        expires_at = (
            datetime.now(timezone.utc) + timedelta(minutes=expire_minutes)
        ).strftime("%Y-%m-%d %H:%M:%S")
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE teamup_posts SET expires_at = CURRENT_TIMESTAMP WHERE voice_channel_id = ?",
                (voice_channel_id,),
            )
            cursor = await db.execute(
                """
                INSERT INTO teamup_posts
                    (user_id, source_channel_id, voice_channel_id, message_content, player_count, game_type, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    source_channel_id,
                    voice_channel_id,
                    message_content,
                    player_count,
                    game_type,
                    expires_at,
                ),
            )
            await db.commit()
            return int(cursor.lastrowid)

    async def save_teamup_message(self, post_id: int, message_id: int, channel_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE teamup_posts
                SET invitation_message_id = ?, invitation_channel_id = ?
                WHERE id = ?
                """,
                (message_id, channel_id, post_id),
            )
            await db.commit()

    async def get_last_teamup_post(self, voice_channel_id: int) -> dict[str, Any] | None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT id, user_id, source_channel_id, voice_channel_id, message_content,
                       player_count, game_type, created_at, expires_at,
                       invitation_message_id, invitation_channel_id
                FROM teamup_posts
                WHERE voice_channel_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (voice_channel_id,),
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_active_teamup_posts(self) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT id, user_id, source_channel_id, voice_channel_id, message_content,
                       player_count, game_type, created_at, expires_at,
                       invitation_message_id, invitation_channel_id
                FROM teamup_posts
                WHERE expires_at > CURRENT_TIMESTAMP
                ORDER BY created_at DESC
                """
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def remove_teamup_posts_by_voice_channel(self, voice_channel_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM teamup_posts WHERE voice_channel_id = ?", (voice_channel_id,))
            await db.commit()

    async def cleanup_expired_teamup_posts(self) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM teamup_posts WHERE expires_at <= CURRENT_TIMESTAMP"
            )
            await db.commit()
            return cursor.rowcount

    async def save_board(self, channel_id: int, message_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO teamup_boards (channel_id, message_id, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                """,
                (channel_id, message_id),
            )
            await db.commit()

    async def remove_board(self, channel_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM teamup_boards WHERE channel_id = ?", (channel_id,))
            await db.commit()

    async def list_boards(self) -> list[tuple[int, int]]:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT channel_id, message_id FROM teamup_boards")
            rows = await cursor.fetchall()
            return [(int(channel_id), int(message_id)) for channel_id, message_id in rows]

    async def add_game_type(self, channel_id: int, game_type: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT MAX(display_order) FROM teamup_game_types")
            row = await cursor.fetchone()
            next_order = int(row[0] or 0) + 1
            await db.execute(
                """
                INSERT OR REPLACE INTO teamup_game_types (channel_id, game_type, display_order)
                VALUES (?, ?, ?)
                """,
                (channel_id, game_type, next_order),
            )
            await db.commit()

    async def remove_game_type(self, channel_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM teamup_game_types WHERE channel_id = ?", (channel_id,))
            await db.commit()

    async def get_game_type(self, channel_id: int) -> str | None:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT game_type FROM teamup_game_types WHERE channel_id = ?",
                (channel_id,),
            )
            row = await cursor.fetchone()
            return str(row[0]) if row else None

    async def list_game_types(self) -> dict[int, str]:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT channel_id, game_type FROM teamup_game_types ORDER BY display_order"
            )
            rows = await cursor.fetchall()
            return {int(channel_id): str(game_type) for channel_id, game_type in rows}

    async def get_signature(self, user_id: int) -> dict[str, Any] | None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT user_id, signature, updated_at, is_disabled
                FROM user_signatures
                WHERE user_id = ?
                """,
                (user_id,),
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def set_signature(self, user_id: int, signature: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO user_signatures (user_id, signature, updated_at, is_disabled)
                VALUES (?, ?, ?, 0)
                ON CONFLICT(user_id) DO UPDATE SET
                    signature = excluded.signature,
                    updated_at = excluded.updated_at
                """,
                (user_id, signature, utc_now_string()),
            )
            await db.commit()

    async def clear_signature(self, user_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO user_signatures (user_id, signature, updated_at, is_disabled)
                VALUES (?, NULL, ?, 0)
                ON CONFLICT(user_id) DO UPDATE SET
                    signature = NULL,
                    updated_at = excluded.updated_at
                """,
                (user_id, utc_now_string()),
            )
            await db.commit()

    async def set_signature_disabled(self, user_id: int, disabled: bool) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO user_signatures (user_id, signature, updated_at, is_disabled)
                VALUES (?, NULL, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    is_disabled = excluded.is_disabled,
                    updated_at = excluded.updated_at
                """,
                (user_id, utc_now_string(), 1 if disabled else 0),
            )
            await db.commit()
