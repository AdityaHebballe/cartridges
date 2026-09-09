# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Zoey Ahmed

import math
from collections.abc import Generator
from typing import TYPE_CHECKING, Any, cast

from gi.repository import Adw, Gio, GLib, GObject, Gtk, Manette

from .ui.collection_details import CollectionDetails
from .ui.game_item import GameItem

if TYPE_CHECKING:
    from .ui.window import Window

STICK_DEADZONE = 0.5
REPEAT_DELAY = 280


class Gamepad(GObject.Object):
    """Data class for gamepad, including UI navigation."""

    __gtype_name__ = __qualname__

    window: "Window"
    device = GObject.Property(type=Manette.Device)

    def __init__(self, device: Manette.Device | None = None, **kwargs: Any):
        super().__init__(**kwargs)

        self._allowed_inputs = {
            Gtk.DirectionType.UP,
            Gtk.DirectionType.DOWN,
            Gtk.DirectionType.LEFT,
            Gtk.DirectionType.RIGHT,
        }

        self._device_signals = GObject.SignalGroup(target_type=Manette.Device)
        self._device_signals.connect_closure(
            "button-press-event", self._on_button_press_event, after=False
        )
        self._device_signals.connect_closure(
            "absolute-axis-event", self._on_analog_axis_event, after=False
        )
        self._device_signals.connect_closure(
            "hat-axis-event", self._on_hat_axis_event, after=False
        )

        self.bind_property("device", self._device_signals, "target")

        self.device = device

    @staticmethod
    def _get_rtl_direction(
        a: Gtk.DirectionType, b: Gtk.DirectionType
    ) -> Gtk.DirectionType:
        return a if Gtk.Widget.get_default_direction() == Gtk.TextDirection.RTL else b

    def _lock_input(self, direction: Gtk.DirectionType):
        self._allowed_inputs.remove(direction)
        GLib.timeout_add(REPEAT_DELAY, lambda *_: self._allowed_inputs.add(direction))

    def _get_active_layout(self) -> str:
        from cartridges import SETTINGS

        try:
            setting = SETTINGS.get_string("gamepad-layout")
        except Exception:
            setting = "auto"

        if setting in ("xbox", "nintendo", "playstation"):
            return setting

        # Automatic detection based on connected device name/guid
        if self.device:
            name = (self.device.get_name() or "").lower()
            guid = (self.device.get_guid() or "").lower()
            if "switch" in name or "nintendo" in name or "057e" in guid:
                return "nintendo"
            if (
                "playstation" in name
                or "dualshock" in name
                or "dualsense" in name
                or "054c" in guid
            ):
                return "playstation"

        return "xbox"

    def _on_button_press_event(self, _device: Manette.Device, event: Manette.Event):
        _success, button = event.get_button()
        if not _success:
            return

        # D-pad buttons (handled identically across all layouts)
        # 544..547 (BTN_DPAD_*), 704..707 (BTN_TRIGGER_HAPPY*)
        if button in (544, 704):
            self._move_vertically(Gtk.DirectionType.UP)
            return
        elif button in (545, 705):
            self._move_vertically(Gtk.DirectionType.DOWN)
            return
        elif button in (546, 706):
            self._move_horizontally(Gtk.DirectionType.LEFT)
            return
        elif button in (547, 707):
            self._move_horizontally(Gtk.DirectionType.RIGHT)
            return

        # Select / Start
        if button == 314:  # Select / Back / -
            self._on_return_button_pressed()
            return
        elif button == 315:  # Start / Menu / +
            self._on_details_button_pressed()
            return

        layout = self._get_active_layout()

        # Face buttons:
        # 304 = BTN_SOUTH (Bottom button)
        # 305 = BTN_EAST  (Right button)
        # 307 = BTN_NORTH (Top button)
        # 308 = BTN_WEST  (Left button)
        if layout == "nintendo":
            # Nintendo layout:
            # A is East (305) -> Play / Confirm
            # B is South (304) -> Back / Return
            # X is North (307) -> Details
            # Y is West (308) -> Search
            match button:
                case 305:  # A (East)
                    self._on_activate_button_pressed()
                case 304:  # B (South)
                    self._on_return_button_pressed()
                case 307:  # X (North)
                    self._on_details_button_pressed()
                case 308:  # Y (West)
                    self.window.search_entry.grab_focus()
        else:
            # Xbox / PlayStation layout:
            # A / Cross is South (304) -> Play / Confirm
            # B / Circle is East (305) -> Back / Return
            # X / Square is West (308) -> Details
            # Y / Triangle is North (307) -> Search
            match button:
                case 304:  # A / Cross (South)
                    self._on_activate_button_pressed()
                case 305:  # B / Circle (East)
                    self._on_return_button_pressed()
                case 308:  # X / Square (West)
                    self._on_details_button_pressed()
                case 307:  # Y / Triangle (North)
                    self.window.search_entry.grab_focus()

    def _on_analog_axis_event(self, _device: Manette.Device, event: Manette.Event):
        _, axis, value = event.get_absolute()
        if abs(value) < STICK_DEADZONE:
            return

        match axis:
            case 0 | 16:  # Left stick X or ABS_HAT0X
                direction = (
                    Gtk.DirectionType.LEFT if value < 0 else Gtk.DirectionType.RIGHT
                )

                if direction in self._allowed_inputs:
                    self._lock_input(direction)
                    self._move_horizontally(direction)
            case 1 | 17:  # Left stick Y or ABS_HAT0Y
                direction = (
                    Gtk.DirectionType.UP if value < 0 else Gtk.DirectionType.DOWN
                )
                if direction in self._allowed_inputs:
                    self._lock_input(direction)
                    self._move_vertically(direction)

    def _on_hat_axis_event(self, _device: Manette.Device, event: Manette.Event):
        _success, axis, value = event.get_hat()
        if not _success or value == 0:
            return

        match axis:
            case 0:
                direction = (
                    Gtk.DirectionType.LEFT if value < 0 else Gtk.DirectionType.RIGHT
                )
                if direction in self._allowed_inputs:
                    self._lock_input(direction)
                    self._move_horizontally(direction)
            case 1:
                direction = (
                    Gtk.DirectionType.UP if value < 0 else Gtk.DirectionType.DOWN
                )
                if direction in self._allowed_inputs:
                    self._lock_input(direction)
                    self._move_vertically(direction)

    def _launch_focused_game(self) -> bool:
        if (game_widget := self._get_focused_game()) and isinstance(
            item := game_widget.get_first_child(), GameItem
        ) and item.game:
            item.activate_action("game.play")
            return True
        return False

    def _on_details_button_pressed(self):
        if self._can_navigate_games_page():
            self.window._show_details(self.window.grid, self._get_current_position())
        elif self.window.navigation_view.props.visible_page_tag == "details":
            if not self.window.details.editing:
                self.window.details.edit()

    def _activate_widget(self, widget: Gtk.Widget):
        if isinstance(widget, Gtk.Button):
            widget.emit("clicked")
        elif isinstance(widget, Gtk.MenuButton):
            widget.set_active(not widget.props.active)
        else:
            widget.activate()

    def _on_activate_button_pressed(self):
        if self.window.props.visible_dialog:
            if focus_widget := self.window.props.focus_widget:
                self._activate_widget(focus_widget)
            return

        if self.window.navigation_view.props.visible_page_tag == "details":
            if focus_widget := self.window.props.focus_widget:
                self._activate_widget(focus_widget)
            return

        if self._is_focused_on_top_bar() and (
            focus_widget := self.window.props.focus_widget
        ):
            self._activate_widget(focus_widget)
            return

        if self.window.sidebar.get_focus_child():
            if focus_widget := self.window.props.focus_widget:
                self._activate_widget(focus_widget)
            return

        if self._can_navigate_games_page():
            if self._launch_focused_game():
                return

        if focus_widget := self.window.props.focus_widget:
            self._activate_widget(focus_widget)

    def _on_return_button_pressed(self):
        if self.window.navigation_view.props.visible_page_tag == "details":
            if self.window.details.editing:
                self.window.details.activate_action("details.cancel")
                return

            if self._is_focused_on_top_bar():
                self.window.sort_button.props.active = False
                return

            self.window.navigation_view.pop_to_tag("games")
            self.window.grid.grab_focus()
            self.window.props.focus_visible = True
            return

        if isinstance(dialog := self.window.props.visible_dialog, CollectionDetails):
            dialog.close()
            return

        open_menu = self._get_active_menu_button()

        if open_menu:
            open_menu.set_active(False)
            open_menu.grab_focus()
            return

        grid_visible = self.window.view_stack.props.visible_child_name == "grid"
        if self._is_focused_on_top_bar():
            focus_widget = self.window.grid if grid_visible else self.window.sidebar
        else:
            focus_widget = (
                self.window.search_entry
                if not grid_visible
                else self.window.grid
                if self.window.sidebar.get_focus_child()
                else self.window.sidebar
            )

        focus_widget.grab_focus()
        self.window.props.focus_visible = True

    def _navigate_to_game_position(self, new_pos: int):
        if new_pos >= 0 and new_pos <= self._n_grid_games() - 1:
            self.window.grid.scroll_to(new_pos, Gtk.ListScrollFlags.FOCUS, None)
            self.window.props.focus_visible = True
        else:
            self.window.props.display.beep()

    def _move_horizontally(self, direction: Gtk.DirectionType):
        if self._is_focused_on_top_bar():
            if self.window.header_bar.child_focus(direction):
                self.window.props.focus_visible = True
                return

            # The usual behaviour of child_focus() on the header bar navigating to the
            # left will result in the above child focus to fail, so
            # we need to manually check if the user is going left to then focus the
            # sidebar.

            if direction is not self._get_rtl_direction(
                Gtk.DirectionType.RIGHT, Gtk.DirectionType.LEFT
            ):
                self.window.header_bar.keynav_failed(direction)
                return

            self.window.sidebar.grab_focus()
            self.window.props.focus_visible = True
            return

        if self.window.sidebar.get_focus_child():
            # The usual behaviour of child_focus() on the sidebar
            # would result in the + button being focused, instead of the grid
            # so we need to grab the focus of the grid if the user inputs the
            # corresponding direction to the grid.

            grid_direction = self._get_rtl_direction(
                Gtk.DirectionType.LEFT, Gtk.DirectionType.RIGHT
            )

            # Focus the first game when re-entering from sidebar
            if direction is grid_direction:
                self.window.grid.scroll_to(0, Gtk.ListScrollFlags.FOCUS, None)
                self.window.grid.grab_focus()
                return

            self.window.sidebar.keynav_failed(direction)
            return

        if self._can_navigate_games_page():
            if not self._get_focused_game():
                return

            new_pos = self._get_current_position() + (
                -1
                if direction
                == self._get_rtl_direction(
                    Gtk.DirectionType.RIGHT, Gtk.DirectionType.LEFT
                )
                else 1
            )

            # If the user is focused on the first game and tries to go
            # back another game, instead of failing, the focus should
            # change to the sidebar.

            if new_pos < 0:
                self.window.sidebar.grab_focus()
                self.window.props.focus_visible = True
                return

            self._navigate_to_game_position(new_pos)
            return

        if self.window.navigation_view.props.visible_page_tag == "details":
            if not self.window.details.editing:
                self._navigate_action_buttons(direction)
                return

            if (
                (focus_widget := self.window.props.focus_widget)
                and (parent := focus_widget.props.parent)
                and not parent.child_focus(direction)
            ):
                parent.keynav_failed(direction)

    def _move_vertically(self, direction: Gtk.DirectionType):
        if self._is_focused_on_top_bar() and direction == Gtk.DirectionType.DOWN:
            self.window.grid.grab_focus()
            return

        if self.window.sidebar.get_focus_child():
            if self.window.sidebar.child_focus(direction):
                self.window.props.focus_visible = True
                return

            self.window.sidebar.keynav_failed(direction)
            return

        if self._can_navigate_games_page():
            if not (game := self._get_focused_game()):
                return

            current_grid_columns = math.floor(
                self.window.grid.get_width() / game.get_width()
            )

            new_pos = self._get_current_position() + (
                -current_grid_columns
                if direction == Gtk.DirectionType.UP
                else current_grid_columns
            )
            if new_pos < 0 and direction == Gtk.DirectionType.UP:
                self.window.search_entry.grab_focus()
                return

            self._navigate_to_game_position(new_pos)
            return

        if self.window.navigation_view.props.visible_page_tag != "details":
            return

        if not self.window.details.editing:
            self._navigate_action_buttons(direction)
            return

        if not (focus_widget := self.window.props.focus_widget):
            return

        if not (
            current_row := (
                focus_widget.get_ancestor(Adw.EntryRow)
                or focus_widget.get_ancestor(Adw.WrapBox)
            )
        ):
            self.window.header_bar.grab_focus()
            if not (focus_widget := self.window.get_focus_child()):
                return

            if focus_widget.child_focus(direction):
                self.window.props.focus_visible = True
                return

            focus_widget.keynav_failed(direction)
            return

        if not (current_box := current_row.get_ancestor(Gtk.Box)):
            return

        if not current_box.child_focus(direction):
            current_box.keynav_failed(direction)

        self.window.props.focus_visible = True

    def _navigate_action_buttons(self, direction: Gtk.DirectionType):
        if not (focus_widget := self.window.props.focus_widget):
            return

        widget = focus_widget
        for _ in range(2):  # Try to focus the actions, then try the play button
            if not (widget := widget.props.parent):
                break

            if widget.child_focus(direction):
                self.window.props.focus_visible = True
                return

        # Focus on header bar if the user goes up/down
        self.window.header_bar.grab_focus()
        if not (focus_widget := self.window.get_focus_child()):
            return

        if focus_widget.child_focus(direction):
            self.window.props.focus_visible = True
            return

        focus_widget.keynav_failed(direction)

    def _get_active_menu_button(self) -> Gtk.MenuButton | None:
        for button in self.window.main_menu_button, self.window.sort_button:
            if button.props.active:
                return button
        return None

    def _get_focused_game(self) -> Gtk.Widget | None:
        self.window.grid.grab_focus()
        if (
            focused_game := self.window.props.focus_widget
        ) and focused_game.get_ancestor(Gtk.GridView):
            return focused_game
        return None

    def _get_current_position(self) -> int:
        if (game_widget := self._get_focused_game()) and isinstance(
            item := game_widget.get_first_child(), GameItem
        ):
            return item.position
        return 0

    def _can_navigate_games_page(self) -> bool:
        return bool(
            self.window.navigation_view.props.visible_page_tag == "games"
            and self._n_grid_games()
            and not self._get_active_menu_button()
        )

    def _is_focused_on_top_bar(self) -> bool:
        return bool(
            self.window.header_bar.get_focus_child()
            and not self._get_active_menu_button()
        )

    def _n_grid_games(self) -> int:
        return cast(Gtk.SingleSelection, self.window.grid.props.model).props.n_items


def _iterate_devices() -> Generator[Gamepad]:
    monitor_iter = monitor.iterate()
    has_next = True
    while has_next:
        has_next, device = monitor_iter.next()
        if device:
            yield Gamepad(device)


def _remove_device(device: Manette.Device):
    pos = next(pos for pos, gamepad in enumerate(model) if gamepad.device == device)
    model.remove(pos)


def _update_window_style(model: Gio.ListStore[Gamepad]):
    if model.props.n_items > 0:
        Gamepad.window.add_css_class("controller-connected")
    else:
        Gamepad.window.remove_css_class("controller-connected")


def setup_monitor():
    """Connect monitor to device connect/disconnect signals."""
    monitor.connect(
        "device-connected",
        lambda _, device: model.append(Gamepad(device)),
    )
    monitor.connect("device-disconnected", lambda _, device: _remove_device(device))
    model.splice(0, 0, tuple(_iterate_devices()))


monitor = Manette.Monitor()
model = Gio.ListStore(item_type=Gamepad)
model.connect("items-changed", lambda model, *_: _update_window_style(model))
