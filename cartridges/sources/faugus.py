# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2026 kramo

import json
import shlex
from collections.abc import Generator
from gettext import gettext as _
from json import JSONDecodeError
from pathlib import Path

from cartridges import cover
from cartridges.games import Game

from . import CONFIG, DATA

ID, NAME = "faugus", _("Faugus")

_DATA_PATHS = (
    DATA / "faugus-launcher",
    CONFIG / "faugus-launcher",
)


def get_games() -> Generator[Game]:
    """Installed Faugus games."""
    data_dir = _data_dir()
    if not data_dir:
        return

    json_path = data_dir / "games.json"
    if not json_path.is_file():
        return

    try:
        with json_path.open(encoding="utf-8") as f:
            games_data = json.load(f)
    except (OSError, JSONDecodeError):
        return

    if not isinstance(games_data, list):
        return

    for entry in games_data:
        if not isinstance(entry, dict):
            continue

        gameid = entry.get("gameid")
        if not gameid:
            continue

        title = entry.get("title") or gameid
        game_id = f"{ID}_{gameid}"

        cover_path = Path(entry.get("cover") or "")
        icon_path = Path(entry.get("icon") or "")
        fallback_cover = data_dir / "covers" / f"{gameid}.png"

        game_cover = (
            cover.for_game(game_id)
            or (cover.at_path(cover_path) if cover_path.is_file() else None)
            or (cover.at_path(fallback_cover) if fallback_cover.is_file() else None)
            or (cover.at_path(icon_path) if icon_path.is_file() else None)
        )

        executable = f"faugus-launcher --game {shlex.quote(gameid)}"

        prefix = entry.get("prefix")
        last_played = int(entry.get("last_played", 0)) if isinstance(entry.get("last_played"), (int, float)) else 0
        if prefix:
            reg = Path(prefix) / "user.reg"
            if not reg.is_file():
                reg = Path(prefix) / "system.reg"
            if reg.is_file():
                try:
                    last_played = max(last_played, int(reg.stat().st_mtime))
                except OSError:
                    pass

        yield Game(
            executable=executable,
            game_id=game_id,
            source=ID,
            hidden=bool(entry.get("hidden", False)),
            last_played=last_played,
            name=title,
            cover=game_cover,
        )


def _data_dir() -> Path | None:
    for path in _DATA_PATHS:
        if path.is_dir():
            return path
    return None
