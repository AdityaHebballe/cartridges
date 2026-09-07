# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2023-2026 kramo
# SPDX-FileCopyrightText: Copyright 2026 Jamie Gravendeel

import functools
import itertools
import shlex
import subprocess
from collections.abc import Generator
from contextlib import suppress
from gettext import gettext as _
from pathlib import Path
from typing import cast

from gi.repository import GLib, Gtk

from cartridges import cover, games
from cartridges.games import Game

from . import DATA, SYSTEM_DATA

ID, NAME = "desktop", _("Desktop")

_DATA_PATHS = (DATA, *SYSTEM_DATA)
_ICON_PATHS = tuple(path / "icons" for path in _DATA_PATHS)
_DESKTOP_PATHS = (
    Path(cast(str, GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DESKTOP))),
    *(path / "applications" for path in _DATA_PATHS),
)

_FILE_BLACKLIST = (
    "page.kramo.Cartridges.*",
    "net.lutris.*",
    "lutris.desktop",
    "steam.desktop",
    "com.valvesoftware.Steam.desktop",
    "com.heroicgameslauncher.hgl.desktop",
    "heroic.desktop",
    "io.itch.itch.desktop",
    "*faugus-launcher*",
    "*steamtinkerlaunch*",
    "*goverlay*",
    "*ProtonPlus*",
    "*com.usebottles.bottles*",
)
_EXECUTABLE_BLACKLIST = (
    "steam://rungameid/",
    "heroic://launch/",
    "lutris:rungameid/",
    "lutris:rungame/",
    "itch://caves/",
    "bottles-cli ",
    "faugus-launcher ",
)
_FLATPAK_ID_BLACKLIST = frozenset((
    "hu.kramo.Cartridges",
    "hu.kramo.Cartridges.Devel",
    "page.kramo.Cartridges",
    "page.kramo.Cartridges.Devel",
    "com.heroicgameslauncher.hgl",
    "com.usebottles.bottles",
    "com.valvesoftware.Steam",
    "io.itch.itch",
    "net.lutris.Lutris",
    "org.libretro.RetroArch",
))

_HIDDEN_KEYS = "NoDisplay", "Hidden"

_ICON_FALLBACK = "application-x-executable"


def get_games() -> Generator[Game]:
    """Installed desktop entries."""
    seen = set()
    paths = itertools.chain.from_iterable(p.glob("*.desktop") for p in _DESKTOP_PATHS)
    for path in paths:
        if path.name in seen or any(path.match(pattern) for pattern in _FILE_BLACKLIST):
            continue

        try:
            with path.open("rb") as f:
                data = f.read()
            if b"Game" not in data:
                continue
            game = _game_from(path)
        except (OSError, GLib.Error, ValueError):
            continue

        yield game
        seen.add(path.name)


def _game_from(path: Path) -> Game:
    file = GLib.KeyFile()
    file.load_from_file(str(path), GLib.KeyFileFlags.NONE)

    if "Game" not in file.get_string_list("Desktop Entry", "Categories"):
        raise ValueError

    for key in _HIDDEN_KEYS:
        with suppress(GLib.Error):
            if file.get_boolean("Desktop Entry", key):
                raise ValueError

    exe = file.get_string("Desktop Entry", "Exec")
    if any(cmd in exe for cmd in _EXECUTABLE_BLACKLIST):
        raise ValueError

    with suppress(GLib.Error):
        if file.get_string("Desktop Entry", "X-Flatpak") in _FLATPAK_ID_BLACKLIST:
            raise ValueError

        if not _try_exec(file.get_string("Desktop Entry", "TryExec")):
            raise ValueError

    game_id = f"{ID}_{path.stem}"
    game_cover = cover.for_game(game_id)
    if game_cover is None:
        try:
            icon_name = file.get_string("Desktop Entry", "Icon")
        except GLib.Error:
            icon_name = _ICON_FALLBACK

        icon = _icon_theme().lookup_icon(
            icon_name,
            fallbacks=(_ICON_FALLBACK,),
            size=cover.ICON_SIZE,
            scale=2,
            direction=Gtk.TextDirection.NONE,
            flags=Gtk.IconLookupFlags.NONE,
        )
        game_cover = cover.from_icon(icon)

    try:
        real_path = Path("/", path.relative_to("/run/host"))
    except ValueError:
        real_path = path

    return Game(
        executable=f"gio launch {shlex.quote(str(real_path))}",
        game_id=game_id,
        source=ID,
        name=file.get_string("Desktop Entry", "Name"),
        cover=game_cover,
    )


def _try_exec(executable: str) -> bool:
    if not Path("/.flatpak-info").exists():
        import shutil

        return shutil.which(executable) is not None

    try:
        subprocess.run(  # noqa: S603
            shlex.split(games.format_executable(f"which {executable}")),
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError:
        return False
    else:
        return True


@functools.cache
def _icon_theme() -> Gtk.IconTheme:
    from gi.repository import Gdk

    display = Gdk.Display.get_default()
    icon_theme = Gtk.IconTheme.get_for_display(display) if display else Gtk.IconTheme()
    search_path = list(icon_theme.props.search_path or [])
    for path in _ICON_PATHS:
        p_str = str(path)
        if p_str not in search_path:
            search_path.append(p_str)
    icon_theme.props.search_path = search_path
    return icon_theme
