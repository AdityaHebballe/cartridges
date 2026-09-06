# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2026 kramo

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from gettext import gettext as _
from pathlib import Path
from typing import Any, cast
from urllib.request import Request, urlopen

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from cartridges import cover, steamgriddb
from cartridges.config import PREFIX
from cartridges.games import Game

from .cover import Cover

_logger = logging.getLogger(__name__)


@Gtk.Template(resource_path=f"{PREFIX}/cover-chooser.ui")
class CoverChooserDialog(Adw.Dialog):
    """Dialog for browsing and picking game covers from SteamGridDB."""

    __gtype_name__ = __qualname__

    search_entry: Gtk.SearchEntry = Gtk.Template.Child()
    all_filter_btn: Gtk.ToggleButton = Gtk.Template.Child()
    anim_filter_btn: Gtk.ToggleButton = Gtk.Template.Child()
    static_filter_btn: Gtk.ToggleButton = Gtk.Template.Child()
    toast_overlay: Adw.ToastOverlay = Gtk.Template.Child()
    stack: Adw.ViewStack = Gtk.Template.Child()
    flow_box: Gtk.FlowBox = Gtk.Template.Child()

    def __init__(self, game: Game, **kwargs: Any):
        super().__init__(**kwargs)

        self.game = game
        self._all_covers: list[dict] = []
        self._search_timeout_id: int | None = None
        self._thumb_executor = ThreadPoolExecutor(max_workers=4)
        self._media_files: list[Gtk.MediaFile] = []
        self._is_active = True

        self.props.title = _("Choose Cover - {}").format(game.name)
        self.search_entry.props.text = game.name

        self.connect("closed", self._on_closed)

        self._start_search(query=None)

    def _on_closed(self, *_args):
        self._is_active = False
        for mf in self._media_files:
            try:
                mf.pause()
            except Exception:
                pass
        self._media_files.clear()
        self._thumb_executor.shutdown(wait=False, cancel_futures=True)

    def _start_search(self, query: str | None):
        self.stack.props.visible_child_name = "loading"

        def worker():
            covers = steamgriddb.search_covers(self.game, search_term=query)
            if self._is_active:
                GLib.idle_add(self._on_search_completed, covers)

        threading.Thread(target=worker, daemon=True).start()

    def _on_search_completed(self, covers: list[dict]):
        if not self._is_active:
            return
        self._all_covers = covers
        self._render_cards()

    def _render_cards(self):
        # Stop existing media files
        for mf in self._media_files:
            try:
                mf.pause()
            except Exception:
                pass
        self._media_files.clear()

        # Clear existing flow_box children
        child = self.flow_box.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.flow_box.remove(child)
            child = next_child

        filter_mode = "all"
        if self.anim_filter_btn.props.active:
            filter_mode = "animated"
        elif self.static_filter_btn.props.active:
            filter_mode = "static"

        filtered = [
            c
            for c in self._all_covers
            if filter_mode == "all"
            or (filter_mode == "animated" and c["is_animated"])
            or (filter_mode == "static" and not c["is_animated"])
        ]

        if not filtered:
            self.stack.props.visible_child_name = "empty"
            return

        self.stack.props.visible_child_name = "grid"

        for cover_item in filtered:
            card = self._create_card(cover_item)
            self.flow_box.append(card)

    def _create_card(self, cover_item: dict) -> Gtk.Widget:
        overlay = Gtk.Overlay()
        overlay.add_css_class("cover-card")

        cover_widget = Cover()
        overlay.set_child(cover_widget)

        # Loading placeholder / spinner
        spin = Adw.Spinner()
        spin.set_size_request(32, 32)
        spin.props.halign = Gtk.Align.CENTER
        spin.props.valign = Gtk.Align.CENTER
        overlay.add_overlay(spin)

        if cover_item.get("is_animated"):
            badge = Gtk.Label(label=_("ANIMATED"))
            badge.add_css_class("badge-animated")
            badge.props.halign = Gtk.Align.END
            badge.props.valign = Gtk.Align.START
            badge.props.margin_top = 8
            badge.props.margin_end = 8
            overlay.add_overlay(badge)

        btn = Gtk.Button()
        btn.add_css_class("cover-button")
        btn.props.cursor = Gdk.Cursor.new_from_name("pointer")
        btn.set_child(overlay)
        btn.connect("clicked", lambda *_: self._select_cover(cover_item, btn, spin))

        # Submit thumbnail task
        thumb_url = cover_item.get("thumb") or cover_item.get("url")
        if thumb_url:
            self._thumb_executor.submit(
                self._load_thumbnail, thumb_url, cover_widget, spin, cover_item.get("is_animated")
            )

        return btn

    def _load_thumbnail(self, url: str, cover_widget: Cover, spin: Gtk.Widget, is_animated: bool):
        if not self._is_active:
            return

        try:
            if is_animated and url.endswith(".webm"):
                # Use native GStreamer media stream for webm
                f = Gio.File.new_for_uri(url)
                mf = Gtk.MediaFile.new_for_file(f)
                mf.set_loop(True)
                mf.play()
                self._media_files.append(mf)

                def update_anim():
                    if self._is_active:
                        spin.props.visible = False
                        cover_widget.props.paintable = mf

                GLib.idle_add(update_anim)
            else:
                req = Request(url, headers={"User-Agent": cover.USER_AGENT})
                with urlopen(req, timeout=10) as resp:
                    data = resp.read()

                tex = Gdk.Texture.new_from_bytes(GLib.Bytes.new(data))

                def update_static():
                    if self._is_active:
                        spin.props.visible = False
                        cover_widget.props.paintable = tex

                GLib.idle_add(update_static)
        except Exception as e:
            _logger.debug("Failed to load thumbnail %s: %s", url, e)
            GLib.idle_add(lambda: setattr(spin.props, "visible", False))

    def _select_cover(self, cover_item: dict, btn: Gtk.Button, spin: Gtk.Widget | None = None):
        btn.props.sensitive = False
        if spin:
            spin.props.visible = True
        self.toast_overlay.add_toast(Adw.Toast(title=_("Downloading cover...")))

        def worker():
            success = steamgriddb.download_and_apply_cover(self.game, cover_item["url"])

            def done():
                if success:
                    from cartridges.ui.games import _window

                    _window().send_toast(_("Updated cover for {}").format(self.game.name))
                    self.close()
                else:
                    btn.props.sensitive = True
                    if spin:
                        spin.props.visible = False
                    self.toast_overlay.add_toast(
                        Adw.Toast(title=_("Failed to download cover"))
                    )

            GLib.idle_add(done)

        threading.Thread(target=worker, daemon=True).start()

    @Gtk.Template.Callback()
    def _choose_file(self, *_args):
        file_dialog = Gtk.FileDialog()
        file_dialog.props.title = _("Choose Cover Image")

        filters = Gio.ListStore(item_type=Gtk.FileFilter)
        image_filter = Gtk.FileFilter()
        image_filter.set_name(_("Image Files"))
        for mime in ("image/png", "image/jpeg", "image/webp", "image/gif"):
            image_filter.add_mime_type(mime)
        filters.append(image_filter)
        file_dialog.props.filters = filters

        def on_open_finished(dialog, result):
            try:
                gfile = dialog.open_finish(result)
                if gfile:
                    path = gfile.get_path()
                    if path:
                        data = Path(path).read_bytes()
                        ext = Path(path).suffix.lstrip(".").lower()
                        cover.save_cover(self.game.game_id, data, ext)
                        self.game.cover = cover.for_game(self.game.game_id)
                        from cartridges.ui.games import _window

                        _window().send_toast(
                            _("Updated cover for {}").format(self.game.name)
                        )
                        self.close()
            except Exception as e:
                _logger.debug("File chooser cancelled or failed: %s", e)

        file_dialog.open(self.get_root(), None, on_open_finished)

    @Gtk.Template.Callback()
    def _reset_cover(self, *_args):
        steamgriddb.remove_custom_cover(self.game)
        from cartridges.ui.games import _window

        _window().send_toast(_("Reset cover for {}").format(self.game.name))
        self.close()

    @Gtk.Template.Callback()
    def _on_search_changed(self, entry: Gtk.SearchEntry):
        if self._search_timeout_id:
            GLib.source_remove(self._search_timeout_id)

        query = entry.props.text.strip()
        self._search_timeout_id = GLib.timeout_add(
            500, self._trigger_debounced_search, query
        )

    def _trigger_debounced_search(self, query: str):
        self._search_timeout_id = None
        self._start_search(query)
        return GLib.SOURCE_REMOVE

    @Gtk.Template.Callback()
    def _on_filter_changed(self, *_args):
        self._render_cards()

    @Gtk.Template.Callback()
    def _on_card_activated(self, _box, child):
        pass
