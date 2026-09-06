# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025-2026 kramo

# pyright: reportConstantRedefinition=false

import importlib
import os
import pkgutil
import sys
import threading
import time
from collections.abc import Callable, Generator
from functools import cache
from pathlib import Path
from typing import Final, Protocol, cast

from gi.repository import Gio, GLib, GObject

from cartridges.games import Game

if Path("/.flatpak-info").exists():
    DATA = Path(os.getenv("HOST_XDG_DATA_HOME", Path.home() / ".local" / "share"))
    SYSTEM_DATA = (
        Path("/run", "host", "usr", "share"),
        Path("/run", "host", "usr", "local", "share"),
        Path("/var", "lib", "flatpak", "exports", "share"),
        DATA / "flatpak" / "exports" / "share",
    )
    CONFIG = Path(os.getenv("HOST_XDG_CONFIG_HOME", Path.home() / ".config"))
    CACHE = Path(os.getenv("HOST_XDG_CACHE_HOME", Path.home() / ".cache"))
else:
    DATA = Path(GLib.get_user_data_dir())
    SYSTEM_DATA = tuple(Path(path) for path in GLib.get_system_data_dirs())
    CONFIG = Path(GLib.get_user_config_dir())
    CACHE = Path(GLib.get_user_cache_dir())

FLATPAK = Path.home() / ".var" / "app"

PROGRAM_FILES_X86 = Path(os.getenv("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
APPDATA = Path(os.getenv("APPDATA", r"C:\Users\Default\AppData\Roaming"))
LOCAL_APPDATA = Path(
    os.getenv("CSIDL_LOCAL_APPDATA", r"C:\Users\Default\AppData\Local")
)

APPLICATION_SUPPORT = Path.home() / "Library" / "Application Support"

OPEN = (
    "open"
    if sys.platform.startswith("darwin")
    else "start"
    if sys.platform.startswith("win32")
    else "xdg-open"
)


class _SourceModule(Protocol):
    ID: Final[str]
    NAME: Final[str]

    @staticmethod
    def get_games() -> Generator[Game]:
        """Installed games."""
        ...


class Source(GObject.Object, Gio.ListModel[Game]):
    """A source of games to import."""

    __gtype_name__ = __qualname__

    id = GObject.Property(type=str)
    name = GObject.Property(type=str)
    icon_name = GObject.Property(type=str)

    _module: _SourceModule

    def __init__(self, module: _SourceModule, added: int):
        super().__init__()

        self.id, self.name, self._module = module.ID, module.NAME, module
        self.bind_property(
            "id",
            self,
            "icon-name",
            GObject.BindingFlags.SYNC_CREATE,
            lambda _, ident: f"{ident}-symbolic",
        )

        try:
            self._games = list(self._get_games(added))
        except OSError:
            self._games = []

    def do_get_item(self, position: int) -> Game | None:
        """Get the item at `position`."""
        try:
            return self._games[position]
        except IndexError:
            return None

    def do_get_item_type(self) -> type[Game]:
        """Get the type of the items in `self`."""
        return Game

    def do_get_n_items(self) -> int:
        """Get the number of items in `self`."""
        return len(self._games)

    def append(self, game: Game):
        """Append `game` to `self`."""
        pos = len(self._games)
        self._games.append(game)
        self.items_changed(pos, 0, 1)

    def _get_games(self, added: int) -> Generator[Game]:
        from cartridges import SETTINGS

        hidden_games = set(SETTINGS.get_strv("hidden-games"))
        unhidden_games = set(SETTINGS.get_strv("unhidden-games"))

        for game in self._module.get_games():
            game.added = game.added or added
            if game.game_id in hidden_games:
                game.hidden = True
            elif game.game_id in unhidden_games:
                game.hidden = False
            yield game


_SOURCE_ORDER = (
    "steam",
    "faugus",
    "lutris",
    "heroic",
    "desktop",
    "itch",
    "legendary",
    "imported",
)

all_sources: dict[str, Source] = {}
model = Gio.ListStore(item_type=Source)


def load():
    """Populate `all_sources` and initialize `sources.model`."""
    from cartridges import SETTINGS

    global all_sources
    added = int(time.time())
    all_sources.clear()
    for info in pkgutil.iter_modules(__path__, prefix="."):
        module = cast(_SourceModule, importlib.import_module(info.name, __package__))
        all_sources[module.ID] = Source(module, added)

    SETTINGS.connect("changed::disabled-sources", lambda *_: update_model())
    update_model()


def update_model():
    """Sync sources.model with current disabled-sources settings."""
    from cartridges import SETTINGS

    disabled = set(SETTINGS.get_strv("disabled-sources"))

    def sort_key(s: Source) -> int:
        try:
            return _SOURCE_ORDER.index(s.id)
        except ValueError:
            return len(_SOURCE_ORDER)

    enabled = [
        source
        for ident, source in all_sources.items()
        if ident not in disabled
    ]
    enabled.sort(key=sort_key)
    model.splice(0, model.get_n_items(), enabled)


def get(ident: str) -> Source:
    """Get the source with `ident`."""
    return all_sources[ident]


def reload_async(on_done: Callable[[list[Game], set[str], set[str]], None] | None = None):
    """Reload all sources asynchronously in a worker thread."""

    def worker():
        try:
            added = int(time.time())
            new_sources: dict[str, Source] = {}
            for info in pkgutil.iter_modules(__path__, prefix="."):
                try:
                    module = cast(_SourceModule, importlib.import_module(info.name, __package__))
                    new_sources[module.ID] = Source(module, added)
                except Exception:
                    pass

            def apply():
                try:
                    old_game_ids = set()
                    for s in all_sources.values():
                        for i in range(s.get_n_items()):
                            if g := s.get_item(i):
                                old_game_ids.add(g.game_id)

                    all_sources.clear()
                    all_sources.update(new_sources)
                    update_model()

                    all_games: list[Game] = []
                    for s in all_sources.values():
                        for i in range(s.get_n_items()):
                            if g := s.get_item(i):
                                all_games.append(g)

                    new_game_ids = {g.game_id for g in all_games}
                    added_ids = new_game_ids - old_game_ids
                    removed_ids = old_game_ids - new_game_ids

                    if on_done:
                        on_done(all_games, added_ids, removed_ids)
                except Exception:
                    if on_done:
                        on_done([], set(), set())
                return GLib.SOURCE_REMOVE

            GLib.idle_add(apply)
        except Exception:
            if on_done:
                GLib.idle_add(on_done, [], set(), set())

    threading.Thread(target=worker, daemon=True).start()


