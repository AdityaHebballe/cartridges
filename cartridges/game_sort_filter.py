# game_sort_filter.py
#
# Copyright 2026 Aditya Hebballe
#
# SPDX-License-Identifier: GPL-3.0-or-later

from typing import Any


def normalized_title(title: str) -> str:
    return title.lower().removeprefix("the ")


def game_matches_search(game: Any, text: str) -> bool:
    text = text.lower()
    if not text:
        return True

    return text in game.name.lower() or (
        text in game.developer.lower() if game.developer else False
    )


def game_matches_source(game: Any, source: str) -> bool:
    return source == "all" or game.base_source == source


def game_is_visible(game: Any, search_text: str, source: str) -> bool:
    return game_matches_search(game, search_text) and game_matches_source(game, source)


def game_sort_value(game: Any, sort_state: str, fallback_to_name: bool = False) -> str:
    var = "name"

    if sort_state in ("newest", "oldest"):
        var = "added"
    elif sort_state == "last_played":
        var = "last_played"

    if fallback_to_name:
        var = "name"

    value = getattr(game, var)
    return normalized_title(value) if var == "name" else str(value).lower()


def compare_games(game1: Any, game2: Any, sort_state: str) -> int:
    descending = sort_state not in ("oldest", "a-z")
    primary_is_name = sort_state not in ("newest", "oldest", "last_played")
    value1 = game_sort_value(game1, sort_state)
    value2 = game_sort_value(game2, sort_state)

    if not primary_is_name and value1 == value2:
        value1 = game_sort_value(game1, sort_state, True)
        value2 = game_sort_value(game2, sort_state, True)
        descending = False

    return ((value1 > value2) ^ descending) * 2 - 1
