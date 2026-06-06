# game_data.py
#
# Copyright 2026 Aditya Hebballe
#
# SPDX-License-Identifier: GPL-3.0-or-later

import shlex
from typing import Any

from gi.repository import GObject


PERSISTED_GAME_ATTRS = (
    "added",
    "executable",
    "game_id",
    "source",
    "hidden",
    "last_played",
    "name",
    "developer",
    "removed",
    "blacklisted",
    "version",
)


class GameObject(GObject.Object):
    """GObject wrapper for game data, suitable for Gio.ListStore models."""

    __gtype_name__ = "CartridgesGameObject"

    game = GObject.Property(type=object)

    def __init__(self, game: Any) -> None:
        super().__init__(game=game)
        game.connect("update-ready", self.sync_from_game)

    @GObject.Property(type=str)
    def game_id(self) -> str:
        return self.game.game_id

    @GObject.Property(type=str)
    def source(self) -> str:
        return self.game.source

    @GObject.Property(type=str)
    def base_source(self) -> str:
        return self.game.base_source

    @GObject.Property(type=str)
    def name(self) -> str:
        return self.game.name

    @GObject.Property(type=str)
    def developer(self) -> str:
        return self.game.developer or ""

    @GObject.Property(type=bool, default=False)
    def hidden(self) -> bool:
        return self.game.hidden

    @GObject.Property(type=bool, default=False)
    def removed(self) -> bool:
        return self.game.removed

    @GObject.Property(type=bool, default=False)
    def blacklisted(self) -> bool:
        return self.game.blacklisted

    @GObject.Property(type=int, default=0)
    def added(self) -> int:
        return self.game.added

    @GObject.Property(type=int, default=0)
    def last_played(self) -> int:
        return self.game.last_played

    def sync_from_game(self, *_args: Any) -> None:
        for attr in PERSISTED_GAME_ATTRS:
            if attr == "executable" or attr == "version":
                continue
            self.notify(attr.replace("_", "-"))


def normalize_game_values(data: dict[str, Any]) -> dict[str, Any]:
    values = dict(data)

    if isinstance(values.get("executable"), list):
        values["executable"] = shlex.join(values["executable"])

    return values


def persisted_game_values(game: Any) -> dict[str, Any]:
    return {attr: getattr(game, attr) for attr in PERSISTED_GAME_ATTRS}
