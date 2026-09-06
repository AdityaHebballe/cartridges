# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2026 kramo

from gettext import gettext as _
from typing import Any

from gi.repository import Adw, Gio, Gtk

from cartridges import SETTINGS, sources, steamgriddb
from cartridges.config import PREFIX


@Gtk.Template(resource_path=f"{PREFIX}/preferences.ui")
class Preferences(Adw.PreferencesDialog):
    """Preferences dialog."""

    __gtype_name__ = __qualname__

    steam_switch: Adw.SwitchRow = Gtk.Template.Child()
    faugus_switch: Adw.SwitchRow = Gtk.Template.Child()
    lutris_switch: Adw.SwitchRow = Gtk.Template.Child()
    heroic_switch: Adw.SwitchRow = Gtk.Template.Child()
    desktop_switch: Adw.SwitchRow = Gtk.Template.Child()
    itch_switch: Adw.SwitchRow = Gtk.Template.Child()
    legendary_switch: Adw.SwitchRow = Gtk.Template.Child()

    key_entry: Adw.PasswordEntryRow = Gtk.Template.Child()
    sgdb_switch: Adw.SwitchRow = Gtk.Template.Child()
    sgdb_prefer_switch: Adw.SwitchRow = Gtk.Template.Child()
    sgdb_animated_switch: Adw.SwitchRow = Gtk.Template.Child()
    update_button: Gtk.Button = Gtk.Template.Child()
    spinner: Adw.Spinner = Gtk.Template.Child()

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)

        self._source_switches = {
            "steam": self.steam_switch,
            "faugus": self.faugus_switch,
            "lutris": self.lutris_switch,
            "heroic": self.heroic_switch,
            "desktop": self.desktop_switch,
            "itch": self.itch_switch,
            "legendary": self.legendary_switch,
        }

        disabled = set(SETTINGS.get_strv("disabled-sources"))
        for source_id, switch in self._source_switches.items():
            switch.set_active(source_id not in disabled)
            switch.connect("notify::active", self._on_source_switch_toggled, source_id)

        flags = Gio.SettingsBindFlags.DEFAULT
        SETTINGS.bind("sgdb", self.sgdb_switch, "active", flags)
        SETTINGS.bind("sgdb-prefer", self.sgdb_prefer_switch, "active", flags)
        SETTINGS.bind("sgdb-animated", self.sgdb_animated_switch, "active", flags)

        self.key_entry.props.text = SETTINGS.get_string("sgdb-key")

    def _on_source_switch_toggled(self, switch: Adw.SwitchRow, _param, source_id: str):
        disabled = set(SETTINGS.get_strv("disabled-sources"))
        if switch.get_active():
            disabled.discard(source_id)
        else:
            disabled.add(source_id)
        SETTINGS.set_strv("disabled-sources", sorted(disabled))

    @Gtk.Template.Callback()
    def _key_applied(self, entry: Adw.PasswordEntryRow, *_args):
        SETTINGS.set_string("sgdb-key", entry.props.text.strip())

    @Gtk.Template.Callback()
    def _open_api_key_page(self, *_args):
        Gio.AppInfo.launch_default_for_uri(
            "https://www.steamgriddb.com/profile/preferences/api"
        )

    @Gtk.Template.Callback()
    def _update_covers(self, *_args):
        if key := self.key_entry.props.text.strip():
            SETTINGS.set_string("sgdb-key", key)

        if not steamgriddb.get_api_key():
            self._send_toast(_("Please enter a SteamGridDB API key"))
            return

        self.update_button.props.visible = False
        self.spinner.props.visible = True

        all_games = []
        for src in sources.model:
            for i in range(src.get_n_items()):
                if g := src.get_item(i):
                    all_games.append(g)

        def on_done(updated: int, total: int):
            self.spinner.props.visible = False
            self.update_button.props.visible = True
            self._send_toast(
                _("Updated {}/{} covers from SteamGridDB").format(updated, total)
            )

        steamgriddb.fetch_all_covers_async(
            all_games,
            force=SETTINGS.get_boolean("sgdb-prefer"),
            on_done=on_done,
        )

    def _send_toast(self, message: str):
        self.add_toast(Adw.Toast(title=message))
