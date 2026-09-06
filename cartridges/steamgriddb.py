# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2026 kramo

import json
import logging
import threading
from collections.abc import Callable, Iterable
from urllib.parse import quote
from urllib.request import Request, urlopen

from gi.repository import GLib

from cartridges import SETTINGS
from cartridges.cover import COVERS_DIR, SUPPORTED_EXTENSIONS, USER_AGENT, for_game, has_cover, save_cover
from cartridges.games import Game

_logger = logging.getLogger(__name__)
API_BASE = "https://www.steamgriddb.com/api/v2"


def get_api_key() -> str:
    """Get the configured SteamGridDB API key."""
    return SETTINGS.get_string("sgdb-key").strip()


def is_enabled() -> bool:
    """Check if SteamGridDB is enabled and configured."""
    return SETTINGS.get_boolean("sgdb") and bool(get_api_key())


def _api_get(endpoint: str, api_key: str) -> dict | None:
    url = f"{API_BASE}/{endpoint}"
    req = Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        _logger.debug("SteamGridDB request failed for %s: %s", url, e)
        return None


def search_game(name: str, api_key: str) -> int | None:
    """Search for a game by name and return its SteamGridDB ID."""
    clean_name = name.split("(")[0].split("[")[0].strip()
    data = _api_get(f"search/autocomplete/{quote(clean_name)}", api_key)
    if data and data.get("success") and data.get("data"):
        return data["data"][0]["id"]
    return None


def get_grid_url(sgdb_id: int, api_key: str, *, animated: bool = False) -> str | None:
    """Fetch the best grid URL for a SteamGridDB game ID."""
    endpoints = []
    if animated:
        endpoints.extend((
            f"grids/game/{sgdb_id}?dimensions=600x900&types=animated",
            f"grids/game/{sgdb_id}?types=animated",
        ))
    endpoints.extend((
        f"grids/game/{sgdb_id}?dimensions=600x900&types=static",
        f"grids/game/{sgdb_id}?dimensions=600x900",
        f"grids/game/{sgdb_id}",
    ))

    for ep in endpoints:
        data = _api_get(ep, api_key)
        if data and data.get("success") and data.get("data"):
            return data["data"][0]["url"]
    return None


def get_grid_url_for_steam(steam_app_id: str, api_key: str, *, animated: bool = False) -> str | None:
    """Fetch the best grid URL directly using a Steam App ID."""
    endpoints = []
    if animated:
        endpoints.extend((
            f"grids/steam/{steam_app_id}?dimensions=600x900&types=animated",
            f"grids/steam/{steam_app_id}?types=animated",
        ))
    endpoints.extend((
        f"grids/steam/{steam_app_id}?dimensions=600x900&types=static",
        f"grids/steam/{steam_app_id}?dimensions=600x900",
        f"grids/steam/{steam_app_id}",
    ))

    for ep in endpoints:
        data = _api_get(ep, api_key)
        if data and data.get("success") and data.get("data"):
            return data["data"][0]["url"]
    return None


def download_grid(url: str) -> tuple[bytes, str] | None:
    """Download grid image bytes and guess the file extension."""
    req = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=15) as resp:
            content = resp.read()
            ext = url.split("?")[0].rsplit(".", 1)[-1].lower()
            if ext not in ("gif", "webp", "png", "jpg", "jpeg"):
                ext = "png"
            return content, ext
    except Exception as e:
        _logger.debug("Failed to download grid image %s: %s", url, e)
        return None


def fetch_cover_for_game(game: Game, *, force: bool = False) -> bool:
    """Fetch artwork from SteamGridDB for a game and update its cover."""
    if not is_enabled():
        return False

    api_key = get_api_key()
    prefer_sgdb = SETTINGS.get_boolean("sgdb-prefer")
    prefer_animated = SETTINGS.get_boolean("sgdb-animated")

    # If we already have a saved cover and neither force nor prefer is set, skip
    if has_cover(game.game_id) and not (force or prefer_sgdb):
        return False

    grid_url = None

    # Try Steam AppID lookup first if applicable
    if game.source == "steam" and game.game_id.startswith("steam_"):
        steam_app_id = game.game_id.removeprefix("steam_")
        if steam_app_id.isdigit():
            grid_url = get_grid_url_for_steam(
                steam_app_id, api_key, animated=prefer_animated
            )

    # Search by game title
    if not grid_url:
        sgdb_id = search_game(game.name, api_key)
        if sgdb_id:
            grid_url = get_grid_url(sgdb_id, api_key, animated=prefer_animated)

    if not grid_url:
        return False

    downloaded = download_grid(grid_url)
    if not downloaded:
        return False

    img_bytes, ext = downloaded
    saved_path = save_cover(game.game_id, img_bytes, ext)
    if not saved_path:
        return False

    def _apply():
        if new_cover := for_game(game.game_id):
            game.cover = new_cover

    GLib.idle_add(_apply)
    return True


def fetch_all_covers_async(
    games: Iterable[Game],
    *,
    force: bool = False,
    on_progress: Callable[[int, int], None] | None = None,
    on_done: Callable[[int, int], None] | None = None,
):
    """Fetch covers for games concurrently in background worker threads."""
    games_list = list(games)
    if not games_list:
        if on_done:
            GLib.idle_add(on_done, 0, 0)
        return

    def worker():
        from concurrent.futures import ThreadPoolExecutor, as_completed

        total = len(games_list)
        updated = 0
        completed = 0

        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_game = {
                executor.submit(fetch_cover_for_game, game, force=force): game
                for game in games_list
            }
            for future in as_completed(future_to_game):
                completed += 1
                try:
                    if future.result():
                        updated += 1
                except Exception as e:
                    _logger.debug("Error fetching cover: %s", e)

                if on_progress:
                    GLib.idle_add(on_progress, completed, total)

        if on_done:
            GLib.idle_add(on_done, updated, total)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()


def search_covers(game: Game, search_term: str | None = None) -> list[dict]:
    """Fetch all available grids (both animated and static) for a game."""
    if not is_enabled():
        return []

    api_key = get_api_key()
    covers: list[dict] = []
    seen_ids: set[int] = set()

    def _add_grids(raw_grids: list[dict]):
        for g in raw_grids:
            gid = g.get("id")
            if gid and gid not in seen_ids:
                seen_ids.add(gid)
                mime = g.get("mime", "")
                thumb = g.get("thumb", "")
                url = g.get("url", "")
                is_anim = "webp" in mime or "gif" in mime or "webm" in thumb
                author_name = ""
                if isinstance(g.get("author"), dict):
                    author_name = g["author"].get("name", "")
                covers.append({
                    "id": gid,
                    "url": url,
                    "thumb": thumb,
                    "is_animated": is_anim,
                    "mime": mime,
                    "width": g.get("width", 600),
                    "height": g.get("height", 900),
                    "author": author_name,
                    "score": g.get("score", 0),
                })

    if search_term:
        clean_name = search_term.strip()
        data = _api_get(f"search/autocomplete/{quote(clean_name)}", api_key)
        if data and data.get("success") and data.get("data"):
            sgdb_id = data["data"][0]["id"]
            for t in ("animated", "static"):
                d = _api_get(f"grids/game/{sgdb_id}?dimensions=600x900&types={t}", api_key)
                if d and d.get("success") and d.get("data"):
                    _add_grids(d["data"])
            if not covers:
                d = _api_get(f"grids/game/{sgdb_id}", api_key)
                if d and d.get("success") and d.get("data"):
                    _add_grids(d["data"])
        return covers

    if game.source == "steam" and game.game_id.startswith("steam_"):
        steam_app_id = game.game_id.removeprefix("steam_")
        if steam_app_id.isdigit():
            for t in ("animated", "static"):
                d = _api_get(f"grids/steam/{steam_app_id}?dimensions=600x900&types={t}", api_key)
                if d and d.get("success") and d.get("data"):
                    _add_grids(d["data"])
            if not covers:
                d = _api_get(f"grids/steam/{steam_app_id}", api_key)
                if d and d.get("success") and d.get("data"):
                    _add_grids(d["data"])

    if not covers and game.name:
        clean_name = game.name.split("(")[0].split("[")[0].strip()
        data = _api_get(f"search/autocomplete/{quote(clean_name)}", api_key)
        if data and data.get("success") and data.get("data"):
            sgdb_id = data["data"][0]["id"]
            for t in ("animated", "static"):
                d = _api_get(f"grids/game/{sgdb_id}?dimensions=600x900&types={t}", api_key)
                if d and d.get("success") and d.get("data"):
                    _add_grids(d["data"])
            if not covers:
                d = _api_get(f"grids/game/{sgdb_id}", api_key)
                if d and d.get("success") and d.get("data"):
                    _add_grids(d["data"])

    return covers


def download_and_apply_cover(game: Game, grid_url: str) -> bool:
    """Download a specific grid URL, save it, and apply it to the game."""
    res = download_grid(grid_url)
    if not res:
        return False
    data, ext = res
    if save_cover(game.game_id, data, ext):
        new_cover = for_game(game.game_id)
        if new_cover:
            GLib.idle_add(setattr, game, "cover", new_cover)
            return True
    return False


def remove_custom_cover(game: Game) -> bool:
    """Remove any custom downloaded cover for the game and restore source cover."""
    for ext in SUPPORTED_EXTENSIONS:
        path = COVERS_DIR / f"{game.game_id}.{ext}"
        if path.is_file():
            path.unlink(missing_ok=True)

    default_c = None
    if game.source == "steam" and game.game_id.startswith("steam_"):
        steam_app_id = game.game_id.removeprefix("steam_")
        from cartridges.sources import steam
        try:
            libcache = steam._data_dir() / "appcache" / "librarycache" / steam_app_id
            default_c = steam._find_cover(libcache)
        except Exception:
            pass

    GLib.idle_add(setattr, game, "cover", default_c)
    return True

