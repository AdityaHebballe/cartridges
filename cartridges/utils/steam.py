# steam.py
#
# Copyright 2022-2023 kramo
# Copyright 2023 Geoffrey Coulaud
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import logging
import re
import struct
from pathlib import Path
from typing import TypedDict

import requests
from requests.exceptions import HTTPError

from cartridges import shared
from cartridges.utils.rate_limiter import RateLimiter


class SteamError(Exception):
    pass


class SteamGameNotFoundError(SteamError):
    pass


class SteamNotAGameError(SteamError):
    pass


class SteamInvalidManifestError(SteamError):
    pass


class SteamManifestData(TypedDict):
    """Dict returned by SteamFileHelper.get_manifest_data"""

    name: str
    appid: str
    stateflags: str


class SteamShortcutData(TypedDict):
    """Dict returned by SteamFileHelper.get_shortcut_data"""

    appid: str
    shortcut_appid: str
    name: str
    executable: str
    hidden: bool
    grid_dir: Path


class SteamAPIData(TypedDict):
    """Dict returned by SteamAPIHelper.get_api_data"""

    developer: str


class SteamRateLimiter(RateLimiter):
    """Rate limiter for the Steam web API"""

    # Steam web API limit
    # 200 requests per 5 min seems to be the limit
    # https://stackoverflow.com/questions/76047820/how-am-i-exceeding-steam-apis-rate-limit
    # https://stackoverflow.com/questions/51795457/avoiding-error-429-too-many-requests-steam-web-api
    refill_period_seconds = 5 * 60
    refill_period_tokens = 200
    burst_tokens = 100

    def _init_pick_history(self) -> None:
        """
        Load the pick history from schema.

        Allows remembering API limits through restarts of Cartridges.
        """
        super()._init_pick_history()
        timestamps_str = shared.state_schema.get_string("steam-limiter-tokens-history")
        self.pick_history.add(*json.loads(timestamps_str))
        self.pick_history.remove_old_entries()

    def acquire(self) -> None:
        """Get a token from the bucket and store the pick history in the schema"""
        super().acquire()
        timestamps_str = json.dumps(self.pick_history.copy_timestamps())
        shared.state_schema.set_string("steam-limiter-tokens-history", timestamps_str)


class SteamFileHelper:
    """Helper for Steam file formats"""

    def get_manifest_data(self, manifest_path: Path) -> SteamManifestData:
        """Get local data for a game from its manifest"""

        with open(manifest_path, "r", encoding="utf-8") as file:
            contents = file.read()

        data = {}

        for key in SteamManifestData.__required_keys__:  # pylint: disable=no-member
            regex = f'"{key}"\\s+"(.*)"\n'
            if (match := re.search(regex, contents, re.IGNORECASE)) is None:
                raise SteamInvalidManifestError()
            data[key] = match.group(1)

        return SteamManifestData(
            name=data["name"],
            appid=data["appid"],
            stateflags=data["stateflags"],
        )

    def get_shortcut_data(self, shortcut_path: Path) -> list[SteamShortcutData]:
        """Get local non-Steam shortcut data from Steam's binary VDF file."""

        data = shortcut_path.read_bytes()
        offset = 0
        shortcuts = []

        def read_cstring() -> str:
            nonlocal offset
            end = data.index(b"\x00", offset)
            value = data[offset:end].decode("utf-8", errors="replace")
            offset = end + 1
            return value

        def read_object() -> dict:
            nonlocal offset
            values = {}
            while offset < len(data):
                value_type = data[offset]
                offset += 1
                if value_type == 8:
                    break

                key = read_cstring()
                if value_type == 0:
                    values[key] = read_object()
                elif value_type == 1:
                    values[key] = read_cstring()
                elif value_type == 2:
                    values[key] = struct.unpack_from("<i", data, offset)[0]
                    offset += 4
                else:
                    raise SteamInvalidManifestError()

            return values

        parsed = read_object().get("shortcuts", {})
        grid_dir = shortcut_path.parent / "grid"
        for shortcut in parsed.values():
            if not all(key in shortcut for key in ("appid", "AppName")):
                continue

            appid = int(shortcut["appid"]) & 0xFFFFFFFF
            shortcut_appid = str((appid << 32) | 0x02000000)
            shortcuts.append(
                SteamShortcutData(
                    appid=str(appid),
                    shortcut_appid=shortcut_appid,
                    name=shortcut["AppName"],
                    executable=shortcut.get("Exe", "").strip('"'),
                    hidden=bool(shortcut.get("IsHidden", 0)),
                    grid_dir=grid_dir,
                )
            )

        return shortcuts


class SteamAPIHelper:
    """Helper around the Steam API"""

    base_url = "https://store.steampowered.com/api"
    rate_limiter: RateLimiter

    def __init__(self, rate_limiter: RateLimiter) -> None:
        self.rate_limiter = rate_limiter

    def get_api_data(self, appid: str) -> SteamAPIData:
        """
        Get online data for a game from its appid.
        May block to satisfy the Steam web API limitations.

        See https://wiki.teamfortress.com/wiki/User:RJackson/StorefrontAPI#appdetails
        """

        # Get data from the API (way block to satisfy its limits)
        with self.rate_limiter:
            try:
                with requests.get(
                    f"{self.base_url}/appdetails?appids={appid}", timeout=5
                ) as response:
                    response.raise_for_status()
                    data = response.json()[appid]
            except HTTPError as error:
                logging.warning("Steam API HTTP error for %s", appid, exc_info=error)
                raise error

        # Handle not found
        if not data["success"]:
            logging.debug("Appid %s not found", appid)
            raise SteamGameNotFoundError()

        # Handle appid is not a game
        if data["data"]["type"] not in {"game", "demo", "mod"}:
            logging.debug("Appid %s is not a game", appid)
            raise SteamNotAGameError()

        # Return API values we're interested in
        values = SteamAPIData(developer=", ".join(data["data"]["developers"]))
        return values
