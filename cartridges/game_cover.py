# game_cover.py
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

from io import BytesIO
from pathlib import Path
from typing import ClassVar, Optional

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gtk", "4.0")

from gi.repository import Gdk, GdkPixbuf, GLib, Gtk
from PIL import Image, ImageFilter, ImageStat, UnidentifiedImageError

from cartridges import shared


class GameCover:
    texture: Optional[Gdk.Texture]
    blurred: Optional[Gdk.Texture]
    luminance: Optional[tuple[float, float]]
    path: Optional[Path]
    animation: Optional[GdkPixbuf.PixbufAnimation]
    anim_iter: Optional[GdkPixbuf.PixbufAnimationIter]
    pending_load: bool = False
    animation_next_frame_at: float = 0

    _placeholder: ClassVar[Optional[Gdk.Texture]] = None
    _placeholder_small: ClassVar[Optional[Gdk.Texture]] = None
    active_animations: ClassVar[set["GameCover"]] = set()
    animation_tick_id: ClassVar[int] = 0

    @classmethod
    def get_placeholder(cls) -> Gdk.Texture:
        if not cls._placeholder:
            cls._placeholder = Gdk.Texture.new_from_resource(
                shared.PREFIX + "/library_placeholder.svg"
            )

        return cls._placeholder

    @classmethod
    def get_placeholder_small(cls) -> Gdk.Texture:
        if not cls._placeholder_small:
            cls._placeholder_small = Gdk.Texture.new_from_resource(
                shared.PREFIX + "/library_placeholder_small.svg"
            )

        return cls._placeholder_small

    def __init__(
        self, pictures: set[Gtk.Picture], path: Optional[Path] = None, lazy: bool = False
    ) -> None:
        self.pictures = pictures
        self.animation = None
        self.anim_iter = None
        self.texture = None
        self.blurred = None
        self.luminance = None
        self.path = None
        self.new_cover(path, lazy)

    def new_cover(self, path: Optional[Path] = None, lazy: bool = False) -> None:
        self.stop_animation(reset=True)
        self.animation = None
        self.texture = None
        self.blurred = None
        self.luminance = None
        self.path = path
        self.pending_load = bool(path and lazy)

        if self.pending_load:
            self.set_texture(None)
            return

        self.load()

    def load(self) -> None:
        if not self.pending_load and (self.texture or self.animation or not self.path):
            if not self.animation:
                self.set_texture(self.texture)
            return

        self.pending_load = False

        if self.path:
            self.migrate_legacy_tiff()
            if self.path.suffix == ".gif":
                self.load_animation_static_frame()
            else:
                self.texture = Gdk.Texture.new_from_filename(str(self.path))

        if not self.animation:
            self.set_texture(self.texture)

    def poster_path(self) -> Optional[Path]:
        if not self.path or self.path.suffix != ".gif":
            return None

        return self.path.with_suffix(".poster.png")

    def load_animation_static_frame(self) -> None:
        if poster_path := self.poster_path():
            if poster_path.is_file():
                self.texture = Gdk.Texture.new_from_filename(str(poster_path))
                return

        self.load_animation(False)

    def migrate_legacy_tiff(self) -> None:
        if not self.path or self.path.suffix != ".tiff":
            return

        png_path = self.path.with_suffix(".png")
        if png_path.is_file():
            self.path = png_path
            return

        try:
            with Image.open(self.path) as image:
                if image.mode not in ("RGB", "RGBA"):
                    image = image.convert("RGBA")
                image.save(png_path, "PNG", optimize=True)
        except (OSError, UnidentifiedImageError):
            return

        self.path = png_path

    def load_animation(self, animate: bool = True) -> None:
        if not self.path:
            return

        self.animation = GdkPixbuf.PixbufAnimation.new_from_file(str(self.path))
        self.anim_iter = self.animation.get_iter()
        static_image = self.animation.get_static_image()

        if animate:
            self.start_animation()
        else:
            self.texture = Gdk.Texture.new_for_pixbuf(static_image)
            if poster_path := self.poster_path():
                try:
                    static_image.savev(str(poster_path), "png")
                except GLib.GError:
                    pass

    def get_texture(self) -> Gdk.Texture:
        self.load()
        return (
            Gdk.Texture.new_for_pixbuf(self.animation.get_static_image())
            if self.animation
            else self.texture
        )

    def get_blurred(self) -> Gdk.Texture:
        self.load()
        if not self.blurred:
            if self.path:
                with Image.open(self.path) as image:
                    image = (
                        image.convert("RGB")
                        .resize((100, 150))
                        .filter(ImageFilter.GaussianBlur(20))
                    )

                    buffer = BytesIO()
                    image.save(buffer, "png")
                    gbytes = GLib.Bytes.new(buffer.getvalue())

                    self.blurred = Gdk.Texture.new_from_bytes(gbytes)

                    stat = ImageStat.Stat(image.convert("L"))

                    # Luminance values for light and dark mode
                    self.luminance = (
                        min((stat.mean[0] + stat.extrema[0][0]) / 510, 0.7),
                        max((stat.mean[0] + stat.extrema[0][1]) / 510, 0.3),
                    )
            else:
                self.blurred = self.get_placeholder_small()
                self.luminance = (0.3, 0.5)

        return self.blurred

    def add_picture(self, picture: Gtk.Picture, load: bool = True) -> None:
        self.pictures.add(picture)
        if not load:
            picture.set_paintable(self.texture or self.get_placeholder())
            return

        self.load()
        if not self.animation:
            self.set_texture(self.texture)

    def set_texture(self, texture: Gdk.Texture) -> None:
        for picture in list(self.pictures):
            if not picture.is_visible():
                self.pictures.discard(picture)

        if not self.pictures:
            self.stop_animation()
        else:
            for picture in self.pictures:
                picture.set_paintable(texture or self.get_placeholder())
                picture.queue_draw()

    def start_animation(self) -> None:
        if self.pending_load:
            self.load()
        if self.path and self.path.suffix == ".gif" and not self.animation:
            self.load_animation(True)
        else:
            self.load()
        if (
            not self.animation
            or not self.anim_iter
            or self.animation.is_static_image()
            or not self.pictures
        ):
            return

        self.active_animations.add(self)
        self.animation_next_frame_at = 0
        self.ensure_animation_tick()

    def stop_animation(self, reset: bool = False) -> None:
        self.active_animations.discard(self)
        self.animation_next_frame_at = 0

        if reset and self.animation:
            self.texture = Gdk.Texture.new_for_pixbuf(self.animation.get_static_image())
            self.set_texture(self.texture)

    @classmethod
    def stop_all_animations(cls) -> None:
        for cover in list(cls.active_animations):
            cover.stop_animation()

    @classmethod
    def ensure_animation_tick(cls) -> None:
        if not cls.animation_tick_id:
            cls.animation_tick_id = GLib.timeout_add(20, cls.animation_tick)

    @classmethod
    def animation_tick(cls) -> bool:
        if not cls.active_animations:
            cls.animation_tick_id = 0
            return False

        now = GLib.get_monotonic_time() / 1000
        for cover in list(cls.active_animations):
            if (
                not cover.animation
                or not cover.anim_iter
                or not cover.pictures
                or cover.animation_next_frame_at > now
            ):
                continue

            cover.anim_iter.advance()
            cover.set_texture(Gdk.Texture.new_for_pixbuf(cover.anim_iter.get_pixbuf()))

            delay_time = cover.anim_iter.get_delay_time()
            cover.animation_next_frame_at = now + (20 if delay_time < 20 else delay_time)

        return True
