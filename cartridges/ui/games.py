# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Zoey Ahmed
# SPDX-FileCopyrightText: Copyright 2025 kramo
# SPDX-FileCopyrightText: Copyright 2025 Jamie Gravendeel

import functools
import locale
from gettext import gettext as _
from typing import TYPE_CHECKING, Any, cast

from gi.repository import Gio, GObject, Gtk

from cartridges import SETTINGS, STATE_SETTINGS, sources
from cartridges.games import Game
from cartridges.sources import imported

from . import closures

if TYPE_CHECKING:
    from .window import Window

_SORT_MODES = {
    "last_played": ("last-played", True),
    "a-z": ("name", False),
    "z-a": ("name", True),
    "newest": ("added", True),
    "oldest": ("added", False),
}


class GameActions(Gio.SimpleActionGroup):
    """Action group for game actions."""

    __gtype_name__ = __qualname__

    game = GObject.Property(type=Game)

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)

        self.add_action_entries((
            ("add", lambda *_: add()),
            ("edit", lambda *_: edit(self.game)),
            ("change-cover", lambda *_: change_cover(self.game)),
            ("play", lambda *_: self._play()),
            ("hide", lambda *_: hide(self.game)),
            ("unhide", lambda *_: unhide(self.game)),
            ("remove", lambda *_: remove(self.game)),
        ))

        game = Gtk.PropertyExpression.new(GameActions, None, "game")
        has_game = Gtk.ClosureExpression.new(bool, closures.bool_, (game,))
        hidden = Gtk.PropertyExpression.new(Game, game, "hidden")
        not_hidden = Gtk.ClosureExpression.new(bool, closures.not_, (hidden,))
        removed = Gtk.PropertyExpression.new(Game, game, "removed")
        not_removed = Gtk.ClosureExpression.new(bool, closures.not_, (removed,))
        false = Gtk.ConstantExpression.new_for_value(False)

        edit_action = cast(Gio.SimpleAction, self.lookup_action("edit"))
        change_cover_action = cast(Gio.SimpleAction, self.lookup_action("change-cover"))
        play_action = cast(Gio.SimpleAction, self.lookup_action("play"))
        hide_action = cast(Gio.SimpleAction, self.lookup_action("hide"))
        unhide_action = cast(Gio.SimpleAction, self.lookup_action("unhide"))
        remove_action = cast(Gio.SimpleAction, self.lookup_action("remove"))

        has_game.bind(edit_action, "enabled", self)
        has_game.bind(change_cover_action, "enabled", self)
        has_game.bind(play_action, "enabled", self)
        Gtk.TryExpression.new((hidden, false)).bind(unhide_action, "enabled", self)
        Gtk.TryExpression.new((not_hidden, false)).bind(hide_action, "enabled", self)
        Gtk.TryExpression.new((not_removed, false)).bind(remove_action, "enabled", self)

    def _play(self):
        if not self.game:
            return
        self.game.play()
        sorter.changed(Gtk.SorterChange.DIFFERENT)


class GameEditable(GObject.Object):
    """A helper object for editing a game."""

    __gtype_name__ = __qualname__

    game = GObject.Property(type=Game)

    valid = GObject.Property(type=bool, default=False)

    executable = GObject.Property(type=str)
    name = GObject.Property(type=str)
    developer = GObject.Property(type=str)

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)

        executable = Gtk.PropertyExpression.new(GameEditable, None, "executable")
        name = Gtk.PropertyExpression.new(GameEditable, None, "name")
        valid = Gtk.ClosureExpression.new(bool, closures.all_, (executable, name))
        valid.bind(self, "valid", self)

    def apply(self):
        """Apply the changes."""
        if not self.valid:
            return

        if not self.game:
            self.game = imported.new()
            sources.get(imported.ID).append(self.game)

        self.game.executable = self.executable
        if self.game.name != self.name:
            self.game.name = self.name
            sorter.changed(Gtk.SorterChange.DIFFERENT)
        self.game.developer = self.developer
        self.game.save()


def add():
    """Add a new game."""
    window = _window()
    if window.navigation_view.props.visible_page_tag != "details":
        window.navigation_view.push_by_tag("details")
    window.details.add()


def edit(game: Game):
    """Edit `game`."""
    window = _window()
    window.details.game = game
    window.navigation_view.push_by_tag("details")
    window.details.edit()


def change_cover(game: Game):
    """Open cover chooser dialog for `game`."""
    from .cover_chooser import CoverChooserDialog

    CoverChooserDialog(game=game).present(_window())


def hide(game: Game):
    """Hide `game` and notify the user with a toast."""
    game.hidden = True
    hidden = set(SETTINGS.get_strv("hidden-games"))
    unhidden = set(SETTINGS.get_strv("unhidden-games"))
    hidden.add(game.game_id)
    unhidden.discard(game.game_id)
    SETTINGS.set_strv("hidden-games", sorted(hidden))
    SETTINGS.set_strv("unhidden-games", sorted(unhidden))
    _window().send_toast(
        _("{} hidden").format(game.name),
        undo=lambda: unhide(game),
    )


def unhide(game: Game):
    """Unhide `game` and notify the user with a toast."""
    game.hidden = False
    hidden = set(SETTINGS.get_strv("hidden-games"))
    unhidden = set(SETTINGS.get_strv("unhidden-games"))
    hidden.discard(game.game_id)
    unhidden.add(game.game_id)
    SETTINGS.set_strv("hidden-games", sorted(hidden))
    SETTINGS.set_strv("unhidden-games", sorted(unhidden))
    _window().send_toast(
        _("{} unhidden").format(game.name),
        undo=lambda: hide(game),
    )


def remove(game: Game):
    """Remove `game` and notify the user with a toast."""
    game.removed = True
    _window().send_toast(
        _("{} removed").format(game.name),
        undo=lambda: setattr(game, "removed", False),
    )


def _window() -> "Window":
    app = cast(Gtk.Application, Gio.Application.get_default())
    return cast("Window", app.props.active_window)


_current_sort_mode = STATE_SETTINGS.get_string("sort-mode")


def _sort(game1: Game, game2: Game) -> int:
    prop, invert = _SORT_MODES.get(_current_sort_mode, ("last-played", True))
    a = (game2 if invert else game1).get_property(prop)
    b = (game1 if invert else game2).get_property(prop)

    return (
        _name_cmp(a, b)
        if isinstance(a, str)
        else ((a > b) - (a < b)) or _name_cmp(game1.name, game2.name)
    )


@functools.cache
def _normalize_name(name: str) -> str:
    s = name.lower()
    return s[4:] if s.startswith("the ") else s


def _name_cmp(a: str, b: str) -> int:
    return locale.strcoll(_normalize_name(a), _normalize_name(b))


def _on_sort_mode_changed(*_args):
    global _current_sort_mode
    _current_sort_mode = STATE_SETTINGS.get_string("sort-mode")
    sorter.changed(Gtk.SorterChange.DIFFERENT)


filter_ = Gtk.EveryFilter()
filter_.append(
    Gtk.BoolFilter(
        expression=Gtk.PropertyExpression.new(Game, None, "removed"),
        invert=True,
    )
)
filter_.append(
    Gtk.BoolFilter(
        expression=Gtk.PropertyExpression.new(Game, None, "blacklisted"),
        invert=True,
    )
)

sorter = Gtk.CustomSorter.new(lambda game1, game2, _: _sort(game1, game2))
STATE_SETTINGS.connect("changed::sort-mode", _on_sort_mode_changed)

model = Gtk.SortListModel(
    model=Gtk.FilterListModel(
        model=Gtk.FlattenListModel(model=sources.model),
        filter=filter_,
        watch_items=True,
    ),
    sorter=sorter,
)
