# window.py
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

# pyright: reportAssignmentType=none

from sys import platform
from time import perf_counter
from typing import Any, Optional

from cartridges import shared
from cartridges.game import Game, GameWidget
from cartridges.game_cover import GameCover
from cartridges.game_data import GameObject
from cartridges.game_sort_filter import compare_games, game_is_visible
from cartridges.utils.relative_date import relative_date
from gi.repository import Adw, Gio, GLib, Gtk, Pango


@Gtk.Template(resource_path=shared.PREFIX + "/gtk/window.ui")
class CartridgesWindow(Adw.ApplicationWindow):
    __gtype_name__ = "CartridgesWindow"

    overlay_split_view: Adw.OverlaySplitView = Gtk.Template.Child()
    navigation_view: Adw.NavigationView = Gtk.Template.Child()
    sidebar_navigation_page: Adw.NavigationPage = Gtk.Template.Child()
    sidebar: Gtk.ListBox = Gtk.Template.Child()
    all_games_row_box: Gtk.Box = Gtk.Template.Child()
    all_games_no_label: Gtk.Label = Gtk.Template.Child()
    added_row_box: Gtk.Box = Gtk.Template.Child()
    added_games_no_label: Gtk.Label = Gtk.Template.Child()
    toast_overlay: Adw.ToastOverlay = Gtk.Template.Child()
    primary_menu_button: Gtk.MenuButton = Gtk.Template.Child()
    show_sidebar_button: Gtk.Button = Gtk.Template.Child()
    details_view: Gtk.Overlay = Gtk.Template.Child()
    library_page: Adw.NavigationPage = Gtk.Template.Child()
    library_view: Adw.ToolbarView = Gtk.Template.Child()
    library: Gtk.FlowBox = Gtk.Template.Child()
    scrolledwindow: Gtk.ScrolledWindow = Gtk.Template.Child()
    library_overlay: Gtk.Overlay = Gtk.Template.Child()
    notice_empty: Adw.StatusPage = Gtk.Template.Child()
    notice_no_results: Adw.StatusPage = Gtk.Template.Child()
    search_bar: Gtk.SearchBar = Gtk.Template.Child()
    search_entry: Gtk.SearchEntry = Gtk.Template.Child()
    search_button: Gtk.ToggleButton = Gtk.Template.Child()

    details_page: Adw.NavigationPage = Gtk.Template.Child()
    details_view_toolbar_view: Adw.ToolbarView = Gtk.Template.Child()
    details_view_cover: Gtk.Picture = Gtk.Template.Child()
    details_view_spinner: Adw.Spinner = Gtk.Template.Child()
    details_view_title: Gtk.Label = Gtk.Template.Child()
    details_view_blurred_cover: Gtk.Picture = Gtk.Template.Child()
    details_view_play_button: Gtk.Button = Gtk.Template.Child()
    details_view_developer: Gtk.Label = Gtk.Template.Child()
    details_view_added: Gtk.ShortcutLabel = Gtk.Template.Child()
    details_view_last_played: Gtk.Label = Gtk.Template.Child()
    details_view_hide_button: Gtk.Button = Gtk.Template.Child()

    hidden_library_page: Adw.NavigationPage = Gtk.Template.Child()
    hidden_primary_menu_button: Gtk.MenuButton = Gtk.Template.Child()
    hidden_library: Gtk.FlowBox = Gtk.Template.Child()
    hidden_library_view: Adw.ToolbarView = Gtk.Template.Child()
    hidden_scrolledwindow: Gtk.ScrolledWindow = Gtk.Template.Child()
    hidden_library_overlay: Gtk.Overlay = Gtk.Template.Child()
    hidden_notice_empty: Adw.StatusPage = Gtk.Template.Child()
    hidden_notice_no_results: Adw.StatusPage = Gtk.Template.Child()
    hidden_search_bar: Gtk.SearchBar = Gtk.Template.Child()
    hidden_search_entry: Gtk.SearchEntry = Gtk.Template.Child()
    hidden_search_button: Gtk.ToggleButton = Gtk.Template.Child()

    game_covers: dict = {}
    toasts: dict = {}
    active_game: Game
    details_view_game_cover: Optional[GameCover] = None
    sort_state: str = "last_played"
    filter_state: str = "all"
    source_rows: dict = {}
    library_filter: Gtk.CustomFilter
    hidden_library_filter: Gtk.CustomFilter
    library_sorter: Gtk.CustomSorter
    hidden_library_sorter: Gtk.CustomSorter
    library_sort_model: Gtk.SortListModel
    hidden_library_sort_model: Gtk.SortListModel

    def create_source_rows(self) -> None:
        def get_removed(source_id: str) -> Any:
            removed = tuple(
                game.removed or game.hidden or game.blacklisted
                for game in shared.store.source_games[source_id].values()
            )
            return (
                (count,) if (count := sum(removed)) != len(removed) else False
            )  # Return a tuple because 0 == False and 1 == True

        total_games_no = 0
        restored = False

        selected_id = (
            self.source_rows[selected_row][0]
            if (selected_row := self.sidebar.get_selected_row()) in self.source_rows
            else None
        )

        if selected_row == self.added_row_box.get_parent():
            self.sidebar.select_row(self.added_row_box.get_parent())
            restored = True

        if added_missing := (
            not shared.store.source_games.get("imported")
            or not (removed := get_removed("imported"))
        ):
            self.sidebar.select_row(self.all_games_row_box.get_parent())
        else:
            games_no = len(shared.store.source_games["imported"]) - removed[0]
            self.added_games_no_label.set_label(str(games_no))
            total_games_no += games_no
        self.added_row_box.get_parent().set_visible(not added_missing)

        self.sidebar.get_row_at_index(2).set_visible(False)

        while row := self.sidebar.get_row_at_index(3):
            self.sidebar.remove(row)

        for source_id in shared.store.source_games:
            if source_id == "imported":
                continue
            if not (removed := get_removed(source_id)):
                continue

            row = Gtk.Box(
                margin_top=12,
                margin_bottom=12,
                margin_start=6,
                margin_end=6,
                spacing=12,
            )
            games_no = len(shared.store.source_games[source_id]) - removed[0]
            total_games_no += games_no

            row.append(
                Gtk.Image.new_from_icon_name(
                    "user-desktop-symbolic"
                    if (split_id := source_id.split("_")[0]) == "desktop"
                    else f"{split_id}-source-symbolic"
                )
            )

            row.append(
                Gtk.Label(
                    label=self.get_application().get_source_name(source_id),
                    halign=Gtk.Align.START,
                    wrap=True,
                    wrap_mode=Pango.WrapMode.CHAR,
                )
            )

            row.append(
                games_no_label := Gtk.Label(
                    label=str(games_no),
                    hexpand=True,
                    halign=Gtk.Align.END,
                )
            )

            games_no_label.add_css_class("dim-label")

            # Order rows based on the number of games in them
            index = 3
            while source_row := self.sidebar.get_row_at_index(index):
                if self.source_rows[source_row][1] < games_no:
                    self.sidebar.insert(row, index)
                    break
                index += 1
            if not row.get_parent():
                self.sidebar.append(row)

            self.source_rows[row.get_parent()] = (
                source_id,
                games_no,
            )

            if source_id == selected_id:
                self.sidebar.select_row(row.get_parent())
                restored = True

            self.sidebar.get_row_at_index(2).set_visible(True)

        self.all_games_no_label.set_label(str(total_games_no))

        if not restored:
            self.sidebar.select_row(self.all_games_row_box.get_parent())

    def row_selected(self, _widget: Any, row: Gtk.ListBoxRow | None) -> None:
        if not row:
            return
        match row.get_child():
            case self.all_games_row_box:
                value = "all"
            case self.added_row_box:
                value = "imported"
            case _:
                value = self.source_rows[row][0]

        self.library_page.set_title(self.get_application().get_source_name(value))

        self.filter_state = value
        self.invalidate_library_models()
        self.queue_visible_cover_load()

        if self.overlay_split_view.get_collapsed():
            self.overlay_split_view.set_show_sidebar(False)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        if platform == "darwin":
            self.sidebar_navigation_page.set_title("")

        self.details_view.set_measure_overlay(self.details_view_toolbar_view, True)
        self.details_view.set_clip_overlay(self.details_view_toolbar_view, False)

        self.setup_library_models()

        self.set_library_child()

        self.notice_empty.set_icon_name(shared.APP_ID + "-symbolic")

        self.overlay_split_view.set_show_sidebar(
            shared.state_schema.get_boolean("show-sidebar")
        )

        self.sidebar.select_row(self.all_games_row_box.get_parent())

        if shared.PROFILE == "development":
            self.add_css_class("devel")

        # Connect search entries
        self.search_bar.connect_entry(self.search_entry)
        self.hidden_search_bar.connect_entry(self.hidden_search_entry)

        # Connect signals
        self.search_entry.connect("search-changed", self.search_changed, False)
        self.hidden_search_entry.connect("search-changed", self.search_changed, True)

        self.search_entry.connect("activate", self.show_details_page_search)
        self.hidden_search_entry.connect("activate", self.show_details_page_search)

        self.scrolledwindow.get_vadjustment().connect(
            "value-changed", lambda *_: self.load_visible_covers()
        )
        self.hidden_scrolledwindow.get_vadjustment().connect(
            "value-changed", lambda *_: self.load_visible_covers(True)
        )

        self.navigation_view.connect("popped", self.set_show_hidden)
        self.navigation_view.connect("pushed", self.set_show_hidden)

        self.sidebar.connect("row-selected", self.row_selected)

        style_manager = Adw.StyleManager.get_default()
        style_manager.connect("notify::dark", self.set_details_view_opacity)
        style_manager.connect("notify::high-contrast", self.set_details_view_opacity)

        # Allow for a custom number of rows for the library
        if shared.schema.get_uint("library-rows"):
            shared.schema.bind(
                "library-rows",
                self.library,
                "max-children-per-line",
                Gio.SettingsBindFlags.DEFAULT,
            )
            shared.schema.bind(
                "library-rows",
                self.hidden_library,
                "max-children-per-line",
                Gio.SettingsBindFlags.DEFAULT,
            )
        else:
            self.library.set_max_children_per_line(10)
            self.hidden_library.set_max_children_per_line(10)

    def setup_library_models(self) -> None:
        self.library_filter = Gtk.CustomFilter.new(
            lambda item: self.filter_model_item(item, False)
        )
        self.hidden_library_filter = Gtk.CustomFilter.new(
            lambda item: self.filter_model_item(item, True)
        )
        self.library_sorter = Gtk.CustomSorter.new(self.sort_model_items)
        self.hidden_library_sorter = Gtk.CustomSorter.new(self.sort_model_items)

        library_filter_model = Gtk.FilterListModel.new(
            shared.store.game_model, self.library_filter
        )
        hidden_library_filter_model = Gtk.FilterListModel.new(
            shared.store.game_model, self.hidden_library_filter
        )
        self.library_sort_model = Gtk.SortListModel.new(
            library_filter_model, self.library_sorter
        )
        self.hidden_library_sort_model = Gtk.SortListModel.new(
            hidden_library_filter_model, self.hidden_library_sorter
        )

        self.library.bind_model(self.library_sort_model, self.create_game_widget)
        self.hidden_library.bind_model(
            self.hidden_library_sort_model, self.create_game_widget
        )

    def create_game_widget(self, item: GameObject, *_args: Any) -> Gtk.Widget:
        if not isinstance(item, GameObject):
            return Gtk.Box()

        started_at = perf_counter()
        game_widget = GameWidget(item.game)
        game_widget.set_size_request(200, -1)
        self.get_application().profile_add(
            "bind game widget", perf_counter() - started_at
        )
        return game_widget

    def invalidate_library_models(self) -> None:
        self.library_filter.changed(Gtk.FilterChange.DIFFERENT)
        self.hidden_library_filter.changed(Gtk.FilterChange.DIFFERENT)
        self.library_sorter.changed(Gtk.SorterChange.DIFFERENT)
        self.hidden_library_sorter.changed(Gtk.SorterChange.DIFFERENT)

    def filter_model_item(self, item: GameObject, hidden: bool) -> bool:
        if not isinstance(item, GameObject):
            return False

        game = item.game
        text = (
            self.hidden_search_entry if hidden else self.search_entry
        ).get_text().lower()
        visible = game_is_visible(game, text, self.filter_state)

        game.filtered = not visible
        if game.removed or game.blacklisted:
            return False
        return visible and game.hidden == hidden

    def sort_model_items(
        self, item1: GameObject, item2: GameObject, *_args: Any
    ) -> int:
        return compare_games(item1.game, item2.game, self.sort_state)

    def load_visible_covers(self, hidden: bool = False) -> int:
        library = self.hidden_library if hidden else self.library
        scrolledwindow = self.hidden_scrolledwindow if hidden else self.scrolledwindow
        adjustment = scrolledwindow.get_vadjustment()
        viewport_top = adjustment.get_value() - adjustment.get_page_size()
        viewport_bottom = (
            adjustment.get_value() + adjustment.get_page_size() * 2
        )
        loaded = 0
        for child in self.iter_game_widgets(library):
            success, bounds = child.compute_bounds(library)
            if not success:
                continue

            child_top = bounds.get_y()
            child_bottom = child_top + bounds.get_height()
            if child_bottom < viewport_top or child_top > viewport_bottom:
                child.game.game_cover.stop_animation()
                continue

            child.game.game_cover.load()
            child.game.game_cover.start_animation()
            loaded += 1

        return loaded

    def iter_game_widgets(self, widget: Gtk.Widget) -> list[GameWidget]:
        games = []
        child = widget.get_first_child()

        while child:
            if isinstance(child, GameWidget):
                games.append(child)
            games.extend(self.iter_game_widgets(child))
            child = child.get_next_sibling()

        return games

    def queue_visible_cover_load(self, hidden: bool = False) -> None:
        GLib.idle_add(
            lambda: (self.load_visible_covers(hidden), False)[1],
            priority=GLib.PRIORITY_LOW,
        )

    def search_changed(self, _widget: Any, hidden: bool) -> None:
        # Refresh search filter on keystroke in search box
        self.invalidate_library_models()
        self.queue_visible_cover_load(hidden)

    def set_library_child(self) -> None:
        if self.get_application().state == shared.AppState.LOAD_FROM_DISK:
            return

        child, hidden_child = self.notice_empty, self.hidden_notice_empty

        for game in shared.store:
            if game.removed or game.blacklisted:
                continue
            if game.hidden:
                if game.filtered and hidden_child:
                    hidden_child = self.hidden_notice_no_results
                    continue
                hidden_child = None
            else:
                if game.filtered and child:
                    child = self.notice_no_results
                    continue
                child = None

        def remove_from_overlay(widget: Gtk.Widget) -> None:
            if isinstance(widget.get_parent(), Gtk.Overlay):
                widget.get_parent().remove_overlay(widget)

        if child:
            self.library_overlay.add_overlay(child)
        else:
            remove_from_overlay(self.notice_empty)
            remove_from_overlay(self.notice_no_results)

        if hidden_child:
            self.hidden_library_overlay.add_overlay(hidden_child)
        else:
            remove_from_overlay(self.hidden_notice_empty)
            remove_from_overlay(self.hidden_notice_no_results)

    def set_active_game(self, _widget: Any, _pspec: Any, game: Game) -> None:
        self.active_game = game

    def show_details_page(self, game: Game) -> None:
        self.active_game = game

        self.details_view_cover.set_opacity(int(not game.loading))
        self.details_view_spinner.set_visible(game.loading)

        self.details_view_developer.set_label(game.developer or "")
        self.details_view_developer.set_visible(bool(game.developer))

        icon, text = "view-conceal-symbolic", _("Hide")
        if game.hidden:
            icon, text = "view-reveal-symbolic", _("Unhide")

        self.details_view_hide_button.set_icon_name(icon)
        self.details_view_hide_button.set_tooltip_text(text)

        if self.details_view_game_cover:
            self.details_view_game_cover.pictures.remove(self.details_view_cover)

        self.details_view_game_cover = game.game_cover
        self.details_view_game_cover.add_picture(self.details_view_cover)
        self.details_view_game_cover.start_animation()

        self.details_view_blurred_cover.set_paintable(
            self.details_view_game_cover.get_blurred()
        )

        self.details_view_title.set_label(game.name)
        self.details_page.set_title(game.name)

        date = relative_date(game.added)
        self.details_view_added.set_label(
            # The variable is the date when the game was added
            _("Added: {}").format(date)
        )
        last_played_date = (
            relative_date(game.last_played) if game.last_played else _("Never")
        )
        self.details_view_last_played.set_label(
            # The variable is the date when the game was last played
            _("Last played: {}").format(last_played_date)
        )

        if self.navigation_view.get_visible_page() != self.details_page:
            self.navigation_view.push(self.details_page)
            self.set_focus(self.details_view_play_button)

        self.set_details_view_opacity()

    def set_details_view_opacity(self, *_args: Any) -> None:
        if self.navigation_view.get_visible_page() != self.details_page:
            return

        if (
            style_manager := Adw.StyleManager.get_default()
        ).get_high_contrast() or not style_manager.get_system_supports_color_schemes():
            self.details_view_blurred_cover.set_opacity(0.3)
            return

        self.details_view_blurred_cover.set_opacity(
            1 - self.details_view_game_cover.luminance[0]  # type: ignore
            if style_manager.get_dark()
            else self.details_view_game_cover.luminance[1]  # type: ignore
        )

    def set_show_hidden(self, navigation_view: Adw.NavigationView, *_args: Any) -> None:
        self.lookup_action("show_hidden").set_enabled(
            navigation_view.get_visible_page() == self.library_page
        )

    def on_show_sidebar_action(self, *_args: Any) -> None:
        shared.state_schema.set_boolean(
            "show-sidebar", (value := not self.overlay_split_view.get_show_sidebar())
        )
        self.overlay_split_view.set_show_sidebar(value)

    def on_go_to_parent_action(self, *_args: Any) -> None:
        if self.navigation_view.get_visible_page() == self.details_page:
            self.navigation_view.pop()

    def on_go_home_action(self, *_args: Any) -> None:
        self.navigation_view.pop_to_page(self.library_page)

    def on_show_hidden_action(self, *_args: Any) -> None:
        if self.navigation_view.get_visible_page() == self.hidden_library_page:
            return

        self.navigation_view.push(self.hidden_library_page)
        self.queue_visible_cover_load(True)

    def on_sort_action(self, action: Gio.SimpleAction, state: GLib.Variant) -> None:
        action.set_state(state)
        self.sort_state = str(state).strip("'")
        self.invalidate_library_models()
        self.queue_visible_cover_load()

        shared.state_schema.set_string("sort-mode", self.sort_state)

    def on_toggle_search_action(self, *_args: Any) -> None:
        if self.navigation_view.get_visible_page() == self.library_page:
            search_bar = self.search_bar
            search_entry = self.search_entry
        elif self.navigation_view.get_visible_page() == self.hidden_library_page:
            search_bar = self.hidden_search_bar
            search_entry = self.hidden_search_entry
        else:
            return

        search_bar.set_search_mode(not (search_mode := search_bar.get_search_mode()))

        if not search_mode:
            self.set_focus(search_entry)

        search_entry.set_text("")

    def show_details_page_search(self, widget: Gtk.Widget) -> None:
        hidden = widget == self.hidden_search_entry

        for game in shared.store:
            game_object = shared.store.get_game_object(game.game_id)
            if self.filter_model_item(game_object, hidden):
                self.show_details_page(game)
                break

    def on_undo_action(
        self, _widget: Any, game: Optional[Game] = None, undo: Optional[str] = None
    ) -> None:
        if not game:  # If the action was activated via Ctrl + Z
            if shared.importer and (
                shared.importer.imported_game_ids or shared.importer.removed_game_ids
            ):
                shared.importer.undo_import()
                return

            try:
                game = tuple(self.toasts.keys())[-1][0]
                undo = tuple(self.toasts.keys())[-1][1]
            except IndexError:
                return

        if game:
            if undo == "hide":
                game.toggle_hidden(False)

            elif undo == "remove":
                game.removed = False
                game.save()
                game.update()

            self.toasts[(game, undo)].dismiss()
            self.toasts.pop((game, undo))

    def on_open_menu_action(self, *_args: Any) -> None:
        if self.navigation_view.get_visible_page() == self.library_page:
            self.primary_menu_button.popup()
        elif self.navigation_view.get_visible_page() == self.hidden_library_page:
            self.hidden_primary_menu_button.popup()

    def on_close_action(self, *_args: Any) -> None:
        self.close()
