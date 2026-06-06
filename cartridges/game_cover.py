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
from typing import Optional

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk
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

    placeholder = Gdk.Texture.new_from_resource(
        shared.PREFIX + "/library_placeholder.svg"
    )
    placeholder_small = Gdk.Texture.new_from_resource(
        shared.PREFIX + "/library_placeholder_small.svg"
    )

    def __init__(
        self, pictures: set[Gtk.Picture], path: Optional[Path] = None, lazy: bool = False
    ) -> None:
        self.pictures = pictures
        self.new_cover(path, lazy)

    def new_cover(self, path: Optional[Path] = None, lazy: bool = False) -> None:
        self.animation = None
        self.texture = None
        self.blurred = None
        self.luminance = None
        self.path = path
        self.pending_load = bool(path and lazy)
        if hasattr(self, "task"):
            del self.task

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
                self.load_animation(False)
            else:
                self.texture = Gdk.Texture.new_from_filename(str(self.path))

        if not self.animation or not hasattr(self, "task"):
            self.set_texture(self.texture)

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

        if animate:
            self.task = Gio.Task.new()
            self.task.run_in_thread(
                lambda *_: self.update_animation((self.task, self.animation))
            )
        else:
            self.texture = Gdk.Texture.new_for_pixbuf(self.animation.get_static_image())

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
                self.blurred = self.placeholder_small
                self.luminance = (0.3, 0.5)

        return self.blurred

    def add_picture(self, picture: Gtk.Picture) -> None:
        self.pictures.add(picture)
        self.load()
        if not self.animation:
            self.set_texture(self.texture)
        elif hasattr(self, "task"):
            self.update_animation((self.task, self.animation))

    def set_texture(self, texture: Gdk.Texture) -> None:
        self.pictures.discard(
            picture for picture in self.pictures if not picture.is_visible()
        )
        if not self.pictures:
            self.animation = None
        else:
            for picture in self.pictures:
                picture.set_paintable(texture or self.placeholder)
                picture.queue_draw()

    def update_animation(self, data: GdkPixbuf.PixbufAnimation) -> None:
        if self.animation == data[1]:
            self.anim_iter.advance()  # type: ignore

            self.set_texture(Gdk.Texture.new_for_pixbuf(self.anim_iter.get_pixbuf()))  # type: ignore

            delay_time = self.anim_iter.get_delay_time()  # type: ignore
            GLib.timeout_add(
                20 if delay_time < 20 else delay_time,
                self.update_animation,
                data,
            )
