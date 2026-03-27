from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML


@dataclass(slots=True)
class ConfigPaths:
    root: Path
    config_dir: Path
    data_dir: Path
    settings_file: Path
    messages_file: Path

    @classmethod
    def from_root(cls, root: Path) -> "ConfigPaths":
        config_dir = root / "config"
        data_dir = root / "data"
        return cls(
            root=root,
            config_dir=config_dir,
            data_dir=data_dir,
            settings_file=config_dir / "settings.yaml",
            messages_file=config_dir / "messages.yaml",
        )


class ConfigStore:
    def __init__(self, root: Path):
        self.paths = ConfigPaths.from_root(root)
        self.yaml = YAML()
        self.yaml.preserve_quotes = True
        self.yaml.indent(mapping=2, sequence=4, offset=2)
        self.settings: Any = None
        self.messages: Any = None
        self.reload()

    def reload(self) -> None:
        self.settings = self._load_yaml(self.paths.settings_file)
        self.messages = self._load_yaml(self.paths.messages_file)

    def save_settings(self) -> None:
        self.paths.config_dir.mkdir(parents=True, exist_ok=True)
        with self.paths.settings_file.open("w", encoding="utf-8") as handle:
            self.yaml.dump(self.settings, handle)

    def _load_yaml(self, path: Path) -> Any:
        source_path = path
        if not source_path.exists():
            example_path = path.with_suffix(".example.yaml")
            if example_path.exists():
                source_path = example_path
            else:
                raise FileNotFoundError(f"配置文件不存在: {path}")
        with source_path.open("r", encoding="utf-8") as handle:
            data = self.yaml.load(handle)
        if data is None:
            raise ValueError(f"配置文件为空: {source_path}")
        return data

    @property
    def token(self) -> str:
        return str(self.settings["discord"]["token"])

    @property
    def guild_id(self) -> int:
        return int(self.settings["discord"]["guild_id"])

    @property
    def admin_channel_id(self) -> int:
        return int(self.settings["admin"]["command_channel_id"])

    def color(self, name: str) -> int:
        raw_value = str(self.settings["appearance"]["colors"][name]).strip()
        if raw_value.startswith("#"):
            raw_value = raw_value[1:]
        return int(raw_value, 16)

    def room_templates(self) -> list[dict[str, Any]]:
        return list(self.settings["rooms"]["templates"])

    def set_room_templates(self, templates: list[dict[str, Any]]) -> None:
        self.settings["rooms"]["templates"] = templates
        self.save_settings()

    def ignored_channel_ids(self) -> list[int]:
        return [int(channel_id) for channel_id in self.settings["teamup"]["ignore_channel_ids"]]

    def set_ignored_channel_ids(self, channel_ids: list[int]) -> None:
        self.settings["teamup"]["ignore_channel_ids"] = channel_ids
        self.save_settings()
