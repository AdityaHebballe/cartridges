# game.py
#
# Copyright 2022-2023 kramo
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

from pathlib import Path
from time import time
from typing import Any, Optional

from gi.repository import Adw, GObject, Gtk

from cartridges import shared
from cartridges.game_data import normalize_game_values
from cartridges.utils.run_executable import run_executable


# pylint: disable=too-many-instance-attributes
class Game(GObject.Object):
    __gtype_name__ = "CartridgesGame"

    loading: int = 0
    filtered: bool = False

    added: int
    executable: str
    game_id: str
    source: str
    hidden: bool = False
    last_played: int = 0
    name: str
    developer: Optional[str] = None
    removed: bool = False
    blacklisted: bool = False
    game_cover = None
    version: int = 0

    def __init__(self, data: dict[str, Any], **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.app = shared.win.get_application()
        self.version = shared.SPEC_VERSION

        self.update_values(data)
        self.base_source = self.source.split("_")[0]

    def update_values(self, data: dict[str, Any]) -> None:
        for key, value in normalize_game_values(data).items():
            setattr(self, key, value)

    def update(self) -> None:
        self.emit("update-ready", {})

    def save(self) -> None:
        self.emit("save-ready", {})

    def create_toast(self, title: str, action: Optional[str] = None) -> None:
        toast = Adw.Toast.new(title.format(self.name))
        toast.set_priority(Adw.ToastPriority.HIGH)
        toast.set_use_markup(False)

        if action:
            toast.set_button_label(_("Undo"))
            toast.connect("button-clicked", shared.win.on_undo_action, self, action)

            if (self, action) in shared.win.toasts.keys():
                # Dismiss the toast if there already is one
                shared.win.toasts[(self, action)].dismiss()

            shared.win.toasts[(self, action)] = toast

        shared.win.toast_overlay.add_toast(toast)

    def launch(self) -> None:
        self.last_played = int(time())
        self.save()
        self.update()

        run_executable(self.executable)

        if shared.schema.get_boolean("exit-after-launch"):
            self.app.quit()

        # The variable is the title of the game
        self.create_toast(_("{} launched"))

    def toggle_hidden(self, toast: bool = True) -> None:
        self.hidden = not self.hidden
        self.save()

        if shared.win.navigation_view.get_visible_page() == shared.win.details_page:
            shared.win.navigation_view.pop()

        self.update()

        if toast:
            self.create_toast(
                # The variable is the title of the game
                (_("{} hidden") if self.hidden else _("{} unhidden")).format(self.name),
                "hide",
            )

    def remove_game(self) -> None:
        # Add "removed=True" to the game properties so it can be deleted on next init
        self.removed = True
        self.save()
        self.update()

        if shared.win.navigation_view.get_visible_page() == shared.win.details_page:
            shared.win.navigation_view.pop()

        # The variable is the title of the game
        self.create_toast(_("{} removed").format(self.name), "remove")

    def set_loading(self, state: int) -> None:
        self.loading += state
        self.update()

    def get_cover_path(self) -> Optional[Path]:
        cover_path = shared.covers_dir / f"{self.game_id}.gif"
        if cover_path.is_file():
            return cover_path  # type: ignore

        cover_path = shared.covers_dir / f"{self.game_id}.png"
        if cover_path.is_file():
            return cover_path  # type: ignore

        cover_path = shared.covers_dir / f"{self.game_id}.tiff"
        if cover_path.is_file():
            return cover_path  # type: ignore

        return None

    @GObject.Signal(name="update-ready", arg_types=[object])
    def update_ready(self, _additional_data):  # type: ignore
        """Signal emitted when the game needs updating"""

    @GObject.Signal(name="save-ready", arg_types=[object])
    def save_ready(self, _additional_data):  # type: ignore
        """Signal emitted when the game needs saving"""


@Gtk.Template(resource_path=shared.PREFIX + "/gtk/game.ui")
class GameWidget(Gtk.Box):
    __gtype_name__ = "GameWidget"

    title = Gtk.Template.Child()
    play_button = Gtk.Template.Child()
    cover = Gtk.Template.Child()
    spinner = Gtk.Template.Child()
    cover_button = Gtk.Template.Child()
    menu_button = Gtk.Template.Child()
    play_revealer = Gtk.Template.Child()
    menu_revealer = Gtk.Template.Child()
    game_options = Gtk.Template.Child()
    hidden_game_options = Gtk.Template.Child()

    game: Game
    update_signal_id: int
    schema_signal_id: int

    def __init__(self, game: Game, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.game = game

        self.update_from_game()

        self.event_contoller_motion = Gtk.EventControllerMotion.new()
        self.add_controller(self.event_contoller_motion)
        self.event_contoller_motion.connect("enter", self.toggle_play, False)
        self.event_contoller_motion.connect("leave", self.toggle_play, None, None)
        self.cover_button.connect("clicked", self.main_button_clicked, False)
        self.play_button.connect("clicked", self.main_button_clicked, True)
        self.menu_button.get_popover().connect(
            "notify::visible", self.toggle_play, None
        )
        self.menu_button.get_popover().connect(
            "notify::visible", shared.win.set_active_game, game
        )

        self.update_signal_id = game.connect("update-ready", self.update_from_game)
        self.schema_signal_id = shared.schema.connect("changed", self.schema_changed)
        game.game_cover.add_picture(self.cover, load=not game.game_cover.pending_load)

    def unbind(self) -> None:
        if self.update_signal_id:
            self.game.disconnect(self.update_signal_id)
            self.update_signal_id = 0
        if self.schema_signal_id:
            shared.schema.disconnect(self.schema_signal_id)
            self.schema_signal_id = 0
        self.game.game_cover.pictures.discard(self.cover)

    def update_from_game(self, *_args: Any) -> None:
        self.menu_button.set_menu_model(
            self.hidden_game_options if self.game.hidden else self.game_options
        )
        self.title.set_label(self.game.name)
        self.set_play_icon()

        loading = self.game.loading > 0
        self.cover.set_opacity(int(not loading))
        self.spinner.set_visible(loading)

    def toggle_play(
        self, _widget: Any, _prop1: Any, _prop2: Any, state: bool = True
    ) -> None:
        if state is False:
            self.game.game_cover.start_animation()

        if not self.menu_button.get_active():
            self.play_revealer.set_reveal_child(not state)
            self.menu_revealer.set_reveal_child(not state)

    def main_button_clicked(self, _widget: Any, button: bool) -> None:
        if shared.schema.get_boolean("cover-launches-game") ^ button:
            self.game.launch()
        else:
            shared.win.show_details_page(self.game)

    def set_play_icon(self) -> None:
        self.play_button.set_icon_name(
            "help-about-symbolic"
            if shared.schema.get_boolean("cover-launches-game")
            else "media-playback-start-symbolic"
        )

    def schema_changed(self, _settings: Any, key: str) -> None:
        if key == "cover-launches-game":
            self.set_play_icon()
