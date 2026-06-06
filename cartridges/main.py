# main.py
#
# Copyright 2022-2024 kramo
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
import lzma
import os
import shlex
import sys
from pathlib import Path
from time import perf_counter, time
from typing import Any, Optional
from urllib.parse import quote

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

# pylint: disable=wrong-import-position
from gi.repository import Adw, Gio, GLib, Gtk

from cartridges import shared
from cartridges.game import Game
from cartridges.logging.setup import log_system_info, setup_logging
from cartridges.store.managers.cover_manager import CoverManager
from cartridges.store.managers.display_manager import DisplayManager
from cartridges.store.managers.file_manager import FileManager
from cartridges.store.managers.sgdb_manager import SgdbManager
from cartridges.store.managers.steam_api_manager import SteamAPIManager
from cartridges.store.store import Store
from cartridges.utils.run_executable import run_executable
from cartridges.window import CartridgesWindow


class CartridgesApplication(Adw.Application):
    startup_load_batch_size = 50
    source_names = {
        "bottles": _("Bottles"),
        "desktop": _("Desktop Entries"),
        "flatpak": _("Flatpak"),
        "heroic": _("Heroic"),
        "itch": _("itch"),
        "legendary": _("Legendary"),
        "lutris": _("Lutris"),
        "retroarch": _("RetroArch"),
        "steam": _("Steam"),
    }
    state = shared.AppState.DEFAULT
    win: CartridgesWindow
    init_search_term: Optional[str] = None
    startup_game_files: list[Path]
    startup_load_index: int = 0
    startup_profile_enabled: bool
    startup_profile_started_at: float
    startup_profile_last_mark: float
    startup_profile_totals: dict[str, float]
    startup_profile_counts: dict[str, int]

    def __init__(self) -> None:
        self.startup_profile_enabled = bool(os.getenv("CARTRIDGES_PROFILE_STARTUP"))
        self.startup_profile_started_at = perf_counter()
        self.startup_profile_last_mark = self.startup_profile_started_at
        self.startup_profile_totals = {}
        self.startup_profile_counts = {}
        self.profile_mark("application init start")

        shared.store = Store()
        super().__init__(application_id=shared.APP_ID)

        search = GLib.OptionEntry()
        search.long_name = "search"
        search.short_name = ord("s")
        search.flags = 0
        search.arg = int(GLib.OptionArg.STRING)
        search.arg_data = None
        search.description = "Open the app with this term in the search entry"
        search.arg_description = "TERM"

        launch = GLib.OptionEntry()
        launch.long_name = "launch"
        launch.short_name = ord("l")
        launch.flags = int(GLib.OptionFlags.NONE)
        launch.arg = int(GLib.OptionArg.STRING)
        launch.arg_data = None
        launch.description = "Run a game with the given game_id"
        launch.arg_description = "GAME_ID"

        self.add_main_option_entries((search, launch))

        if sys.platform.startswith("darwin"):
            if settings := Gtk.Settings.get_default():
                settings.props.gtk_decoration_layout = "close,minimize,maximize:"

        self.profile_mark("application init done")

    def profile_add(self, name: str, elapsed: float) -> None:
        if not self.startup_profile_enabled:
            return

        self.startup_profile_totals[name] = (
            self.startup_profile_totals.get(name, 0) + elapsed
        )
        self.startup_profile_counts[name] = self.startup_profile_counts.get(name, 0) + 1

    def profile_mark(self, name: str) -> None:
        if not self.startup_profile_enabled:
            return

        now = perf_counter()
        print(
            "[startup] "
            f"{name}: +{(now - self.startup_profile_last_mark) * 1000:.1f} ms "
            f"({(now - self.startup_profile_started_at) * 1000:.1f} ms total)",
            file=sys.stderr,
        )
        self.startup_profile_last_mark = now

    def profile_report(self) -> None:
        if not self.startup_profile_enabled:
            return

        print("[startup] totals:", file=sys.stderr)
        for name, elapsed in sorted(
            self.startup_profile_totals.items(), key=lambda item: item[1], reverse=True
        ):
            count = self.startup_profile_counts[name]
            print(
                "[startup] "
                f"  {name}: {elapsed * 1000:.1f} ms "
                f"across {count} call{'s' if count != 1 else ''}",
                file=sys.stderr,
            )

    def do_activate(self) -> None:  # pylint: disable=arguments-differ
        """Called on app creation"""
        self.profile_mark("activation start")
        try:
            setup_logging()
        except ValueError:
            pass
        self.profile_mark("logging ready")

        log_system_info()

        # Create the main window
        win = self.props.active_window  # pylint: disable=no-member
        if not win:
            shared.win = win = CartridgesWindow(application=self)
        self.profile_mark("window ready")

        # Save window geometry
        shared.state_schema.bind(
            "width", shared.win, "default-width", Gio.SettingsBindFlags.DEFAULT
        )
        shared.state_schema.bind(
            "height", shared.win, "default-height", Gio.SettingsBindFlags.DEFAULT
        )
        shared.state_schema.bind(
            "is-maximized", shared.win, "maximized", Gio.SettingsBindFlags.DEFAULT
        )

        # Prepare the store for startup loading
        shared.store.add_manager(FileManager(), False)
        shared.store.add_manager(DisplayManager())

        # Create actions
        self.create_actions(
            {
                ("quit", ("<primary>q",)),
                ("about",),
                ("preferences", ("<primary>comma",)),
                ("launch_game",),
                ("hide_game",),
                ("edit_game",),
                ("add_game", ("<primary>n",)),
                ("import", ("<primary>i",)),
                ("remove_game_details_view", ("Delete",)),
                ("remove_game",),
                ("igdb_search",),
                ("sgdb_search",),
                ("protondb_search",),
                ("pcgw_search",),
                ("lutris_search",),
                ("hltb_search",),
                ("show_sidebar", ("F9",), shared.win),
                ("show_hidden", ("<primary>h",), shared.win),
                ("go_to_parent", ("<alt>Up",), shared.win),
                ("go_home", ("<alt>Home",), shared.win),
                ("toggle_search", ("<primary>f",), shared.win),
                ("undo", ("<primary>z",), shared.win),
                ("open_menu", ("F10",), shared.win),
                ("close", ("<primary>w",), shared.win),
            }
        )
        self.profile_mark("actions ready")

        sort_action = Gio.SimpleAction.new_stateful(
            "sort_by",
            GLib.VariantType.new("s"),
            sort_mode := GLib.Variant("s", shared.state_schema.get_string("sort-mode")),
        )
        sort_action.connect("activate", shared.win.on_sort_action)
        shared.win.add_action(sort_action)
        shared.win.on_sort_action(sort_action, sort_mode)

        if self.init_search_term:  # For command line activation
            shared.win.search_bar.set_search_mode(True)
            shared.win.search_entry.set_text(self.init_search_term)
            shared.win.search_entry.set_position(-1)

        shared.win.present()
        self.profile_mark("window presented")
        self.start_load_games_from_disk()

    def do_handle_local_options(self, options: GLib.VariantDict) -> int:
        if search := options.lookup_value("search"):
            self.init_search_term = search.get_string()
        elif game_id := options.lookup_value("launch"):
            try:
                data = json.load(
                    (path := shared.games_dir / (game_id.get_string() + ".json")).open(
                        "r", encoding="utf-8"
                    )
                )
                executable = (
                    shlex.join(data["executable"])
                    if isinstance(data["executable"], list)
                    else data["executable"]
                )
                name = data["name"]

                run_executable(executable)

                data["last_played"] = int(time())
                json.dump(data, path.open("w", encoding="utf-8"))

            except (IndexError, KeyError, OSError, json.decoder.JSONDecodeError):
                return 1

            self.register()
            self.send_notification(
                "launch", Gio.Notification.new(_("{} launched").format(name))
            )

            # Sleep for 6 seconds before withdrawing the notification
            # The amount a notification stays up is ~5, so leave an extra second for the animation
            GLib.usleep(6000000)
            self.withdraw_notification("launch")

            return 0
        return -1

    def start_load_games_from_disk(self) -> None:
        started_at = perf_counter()
        self.startup_game_files = (
            sorted(shared.games_dir.iterdir()) if shared.games_dir.is_dir() else []
        )
        self.profile_add("enumerate game files", perf_counter() - started_at)
        self.profile_mark(f"found {len(self.startup_game_files)} game files")
        self.startup_load_index = 0
        self.state = shared.AppState.LOAD_FROM_DISK
        GLib.idle_add(self.load_games_from_disk_batch)

    def load_games_from_disk_batch(self) -> bool:
        batch_started_at = perf_counter()
        end_index = min(
            self.startup_load_index + self.startup_load_batch_size,
            len(self.startup_game_files),
        )

        while self.startup_load_index < end_index:
            self.load_game_file(self.startup_game_files[self.startup_load_index])
            self.startup_load_index += 1

        self.profile_add("load game batches", perf_counter() - batch_started_at)

        if self.startup_load_index < len(self.startup_game_files):
            return True

        self.profile_mark(f"loaded {len(shared.store)} games from disk")
        self.finish_startup_load()
        return False

    def load_game_file(self, game_file: Path) -> None:
        started_at = perf_counter()
        try:
            data = json.load(game_file.open())
        except (OSError, json.decoder.JSONDecodeError):
            return
        self.profile_add("read game json", perf_counter() - started_at)

        started_at = perf_counter()
        game = Game(data)
        self.profile_add("create game widget", perf_counter() - started_at)

        started_at = perf_counter()
        shared.store.add_game(game, {"skip_save": True})
        self.profile_add("store/display game", perf_counter() - started_at)

    def finish_startup_load(self) -> None:
        started_at = perf_counter()
        self.state = shared.AppState.DEFAULT
        shared.win.set_library_child()
        shared.win.create_source_rows()
        self.profile_add("final library/sidebar refresh", perf_counter() - started_at)
        self.profile_mark("library/sidebar ready")

        # Add rest of the managers for game imports
        shared.store.add_manager(CoverManager())
        shared.store.add_manager(SteamAPIManager())
        shared.store.add_manager(SgdbManager())
        shared.store.toggle_manager_in_pipelines(FileManager, True)

        GLib.idle_add(self.finish_startup_ready, priority=GLib.PRIORITY_LOW)

    def finish_startup_ready(self) -> bool:
        started_at = perf_counter()
        visible_covers = shared.win.load_visible_covers()
        self.profile_add("load visible startup covers", perf_counter() - started_at)
        self.profile_mark(f"loaded {visible_covers} visible startup covers")
        self.profile_report()
        self.maybe_auto_import()
        return False

    def maybe_auto_import(self) -> None:
        if not shared.schema.get_boolean("auto-import"):
            return

        try:
            delay = int(os.getenv("CARTRIDGES_AUTO_IMPORT_DELAY_SECONDS", "8"))
        except ValueError:
            delay = 8

        self.profile_mark(f"auto-import scheduled in {delay} seconds")
        if delay <= 0:
            GLib.idle_add(self.run_scheduled_auto_import, priority=GLib.PRIORITY_LOW)
        else:
            GLib.timeout_add_seconds(delay, self.run_scheduled_auto_import)

    def run_scheduled_auto_import(self) -> bool:
        if self.state != shared.AppState.DEFAULT:
            return True

        self.profile_mark("auto-import starting")
        self.on_import_action()
        return False

    def get_source_name(self, source_id: str) -> Any:
        if source_id == "all":
            name = _("All Games")
        elif source_id == "imported":
            name = _("Added")
        else:
            name = self.source_names.get(source_id.split("_")[0], source_id)
        return name

    def on_about_action(self, *_args: Any) -> None:
        # Get the debug info from the log files
        debug_str = ""
        for index, path in enumerate(shared.log_files):
            # Add a horizontal line between runs
            if index > 0:
                debug_str += "─" * 37 + "\n"
            # Add the run's logs
            log_file = (
                lzma.open(path, "rt", encoding="utf-8")
                if path.name.endswith(".xz")
                else open(path, "r", encoding="utf-8")
            )
            debug_str += log_file.read()
            log_file.close()

        about = Adw.AboutDialog.new_from_appdata(
            shared.PREFIX + "/" + shared.APP_ID + ".metainfo.xml", shared.VERSION
        )
        about.set_developers(
            (
                "kramo https://kramo.page",
                "Geoffrey Coulaud https://geoffrey-coulaud.fr",
                "Rilic https://rilic.red",
                "Arcitec https://github.com/Arcitec",
                "Paweł Lidwin https://github.com/imLinguin",
                "Domenico https://github.com/Domefemia",
                "Rafael Mardojai CM https://mardojai.com",
                "Clara Hobbs https://github.com/Ratfink",
                "Sabri Ünal https://github.com/sabriunal",
            )
        )
        about.set_designers(("kramo https://kramo.page",))
        about.set_copyright("© 2022-2024 kramo")
        # Translators: Replace this with Your Name, Your Name <your.email@example.com>, or Your Name https://your-site.com for it to show up in the About dialog.
        about.set_translator_credits(_("translator-credits"))
        about.set_debug_info(debug_str)
        about.set_debug_info_filename("cartridges.log")
        about.add_legal_section(
            "Steam Branding",
            "© 2023 Valve Corporation",
            Gtk.License.CUSTOM,
            "Steam and the Steam logo are trademarks and/or registered trademarks of Valve Corporation in the U.S. and/or other countries.",  # pylint: disable=line-too-long
        )
        about.present(shared.win)

    def on_preferences_action(
        self,
        _action: Any = None,
        _parameter: Any = None,
        page_name: Optional[str] = None,
        expander_row: Optional[str] = None,
    ) -> Optional[Any]:
        from cartridges.preferences import CartridgesPreferences

        if CartridgesPreferences.is_open:
            return

        win = CartridgesPreferences()
        if page_name:
            win.set_visible_page_name(page_name)
        if expander_row:
            getattr(win, expander_row).set_expanded(True)
        win.present(shared.win)

        return win

    def on_launch_game_action(self, *_args: Any) -> None:
        shared.win.active_game.launch()

    def on_hide_game_action(self, *_args: Any) -> None:
        shared.win.active_game.toggle_hidden()

    def on_edit_game_action(self, *_args: Any) -> None:
        from cartridges.details_dialog import DetailsDialog

        DetailsDialog(shared.win.active_game).present(shared.win)

    def on_add_game_action(self, *_args: Any) -> None:
        from cartridges.details_dialog import DetailsDialog

        if DetailsDialog.is_open:
            return

        DetailsDialog().present(shared.win)

    def on_import_action(self, *_args: Any) -> None:
        from cartridges.importer.bottles_source import BottlesSource
        from cartridges.importer.desktop_source import DesktopSource
        from cartridges.importer.flatpak_source import FlatpakSource
        from cartridges.importer.heroic_source import HeroicSource
        from cartridges.importer.importer import Importer  # yo dawg
        from cartridges.importer.itch_source import ItchSource
        from cartridges.importer.legendary_source import LegendarySource
        from cartridges.importer.lutris_source import LutrisSource
        from cartridges.importer.retroarch_source import RetroarchSource
        from cartridges.importer.steam_source import SteamSource

        shared.importer = Importer()

        if shared.schema.get_boolean("lutris"):
            shared.importer.add_source(LutrisSource())

        if shared.schema.get_boolean("steam"):
            shared.importer.add_source(SteamSource())

        if shared.schema.get_boolean("heroic"):
            shared.importer.add_source(HeroicSource())

        if shared.schema.get_boolean("bottles"):
            shared.importer.add_source(BottlesSource())

        if shared.schema.get_boolean("flatpak"):
            shared.importer.add_source(FlatpakSource())

        if shared.schema.get_boolean("desktop"):
            shared.importer.add_source(DesktopSource())

        if shared.schema.get_boolean("itch"):
            shared.importer.add_source(ItchSource())

        if shared.schema.get_boolean("legendary"):
            shared.importer.add_source(LegendarySource())

        if shared.schema.get_boolean("retroarch"):
            shared.importer.add_source(RetroarchSource())

        shared.importer.run()

    def on_remove_game_action(self, *_args: Any) -> None:
        shared.win.active_game.remove_game()

    def on_remove_game_details_view_action(self, *_args: Any) -> None:
        if shared.win.navigation_view.get_visible_page() == shared.win.details_page:
            self.on_remove_game_action()

    def search(self, uri: str) -> None:
        Gio.AppInfo.launch_default_for_uri(f"{uri}{quote(shared.win.active_game.name)}")

    def on_igdb_search_action(self, *_args: Any) -> None:
        self.search("https://www.igdb.com/search?type=1&q=")

    def on_sgdb_search_action(self, *_args: Any) -> None:
        self.search("https://www.steamgriddb.com/search/grids?term=")

    def on_protondb_search_action(self, *_args: Any) -> None:
        self.search("https://www.protondb.com/search?q=")

    def on_pcgw_search_action(self, *_args: Any) -> None:
        self.search("https://www.pcgamingwiki.com/w/index.php?search=")

    def on_lutris_search_action(self, *_args: Any) -> None:
        self.search("https://lutris.net/games?q=")

    def on_hltb_search_action(self, *_args: Any) -> None:
        self.search("https://howlongtobeat.com/?q=")

    def on_quit_action(self, *_args: Any) -> None:
        self.quit()

    def create_actions(self, actions: set) -> None:
        for action in actions:
            simple_action = Gio.SimpleAction.new(action[0], None)

            scope = action[2] if action[2:3] else self
            simple_action.connect("activate", getattr(scope, f"on_{action[0]}_action"))

            if action[1:2]:
                self.set_accels_for_action(
                    f"app.{action[0]}" if scope == self else f"win.{action[0]}",
                    (
                        tuple(s.replace("<primary>", "<meta>") for s in action[1])
                        if sys.platform.startswith("darwin")
                        else action[1]
                    ),
                )

            scope.add_action(simple_action)


def main(_version: int) -> Any:
    """App entry point"""
    app = CartridgesApplication()
    return app.run(sys.argv)
