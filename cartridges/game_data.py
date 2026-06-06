# game_data.py
#
# Copyright 2026 Aditya Hebballe
#
# SPDX-License-Identifier: GPL-3.0-or-later

import shlex
from typing import Any


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


def normalize_game_values(data: dict[str, Any]) -> dict[str, Any]:
    values = dict(data)

    if isinstance(values.get("executable"), list):
        values["executable"] = shlex.join(values["executable"])

    return values


def persisted_game_values(game: Any) -> dict[str, Any]:
    return {attr: getattr(game, attr) for attr in PERSISTED_GAME_ATTRS}
