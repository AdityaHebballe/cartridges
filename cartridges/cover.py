# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2026 kramo

from collections import defaultdict
from io import BytesIO
from os import PathLike
from pathlib import Path
from urllib.request import Request, urlopen

import PIL
from gi.repository import Gdk, GLib, GObject, Graphene, Gtk
from PIL import Image

from . import DATA_DIR

COVERS_DIR = DATA_DIR / "covers"

WIDTH = 200
HEIGHT = 300
ICON_SIZE = 128
USER_AGENT = "cartridges/49.0"
SUPPORTED_EXTENSIONS = ("gif", "webp", "png", "jpg", "jpeg", "tiff")


class _PILPaintable(GObject.Object, Gdk.Paintable):
    def __init__(self, im: Image.Image):
        super().__init__()

        self.im = im
        self.needs_update = True
        self.flags = Gdk.PaintableFlags.STATIC_SIZE

        # Cap memory usage for excessively large animations
        max_w, max_h = WIDTH * 2, HEIGHT * 2
        if im.width > max_w or im.height > max_h:
            scale = min(max_w / im.width, max_h / im.height)
            self._target_size = (int(im.width * scale), int(im.height * scale))
        else:
            self._target_size = (im.width, im.height)

        self.frames = defaultdict(self._render_frame)

        if not getattr(self.im, "is_animated", False) or getattr(self.im, "n_frames", 1) <= 1:
            self.needs_update = False
            self.flags |= Gdk.PaintableFlags.STATIC_CONTENTS

    def _render_frame(self) -> Gdk.MemoryTexture:
        frame = self.im
        if self._target_size != (self.im.width, self.im.height):
            frame = frame.resize(self._target_size, Image.Resampling.BILINEAR)
        rgba = frame.convert("RGBA")
        return Gdk.MemoryTexture.new(
            self._target_size[0],
            self._target_size[1],
            Gdk.MemoryFormat.R8G8B8A8,
            GLib.Bytes.new(rgba.tobytes()),
            self._target_size[0] * 4,
        )

    def do_get_current_image(self) -> Gdk.Paintable:
        return self.frames[self.im.tell()]

    def do_get_intrinsic_height(self) -> int:
        return self._target_size[1]

    def do_get_intrinsic_width(self) -> int:
        return self._target_size[0]

    def do_get_flags(self) -> Gdk.PaintableFlags:
        return self.flags

    def do_snapshot(self, snapshot: Gdk.Snapshot, width: int, height: int):
        self.do_get_current_image().snapshot(snapshot, width, height)
        if self.needs_update:
            self.needs_update = False
            duration = self.im.info.get("duration") or 100
            GLib.timeout_add(max(int(duration), 20), self.update_frame)

    def update_frame(self):
        try:
            self.im.seek(self.im.tell() + 1)
        except EOFError:
            self.im.seek(0)

        self.needs_update = True
        self.invalidate_contents()
        return GLib.SOURCE_REMOVE


def at_path(path: PathLike[str] | str) -> Gdk.Paintable | None:
    """Load the cover at `path`."""
    path_str = str(path)
    lower = path_str.lower()

    # If it could be animated, inspect with PIL
    if lower.endswith((".gif", ".webp")):
        try:
            im = Image.open(path_str)
            if getattr(im, "is_animated", False) and getattr(im, "n_frames", 1) > 1:
                return _PILPaintable(im)
            im.close()
        except (FileNotFoundError, PIL.UnidentifiedImageError, OSError):
            return None

    # For static images, use native hardware-accelerated Gdk.Texture directly
    try:
        return Gdk.Texture.new_from_filename(path_str)
    except GLib.Error:
        try:
            return _PILPaintable(Image.open(path_str))
        except Exception:
            return None


def at_url(url: str) -> Gdk.Paintable | None:
    """Load the cover at the remote `url`."""
    req = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req) as response:  # TODO: Rate limiting?
            contents = response.read()
        return _PILPaintable(Image.open(BytesIO(contents)))
    except (OSError, PIL.UnidentifiedImageError):
        return None


def download_and_save(game_id: str, url: str) -> Gdk.Paintable | None:
    """Download cover from URL, persist to disk for game_id, and load it."""
    req = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=15) as resp:
            contents = resp.read()
        if save_cover(game_id, contents):
            return for_game(game_id)
    except Exception:
        pass
    return None


def for_game(game_id: str) -> Gdk.Paintable | None:
    """Load a saved cover for `game_id` from COVERS_DIR."""
    for ext in SUPPORTED_EXTENSIONS:
        path = COVERS_DIR / f"{game_id}.{ext}"
        if path.is_file():
            if p := at_path(path):
                return p
    return None


def save_cover(game_id: str, image_bytes: bytes, ext: str | None = None) -> Path | None:
    """Save cover art bytes for `game_id` to COVERS_DIR, optimizing animations if needed."""
    COVERS_DIR.mkdir(parents=True, exist_ok=True)

    for old_ext in SUPPORTED_EXTENSIONS:
        old_file = COVERS_DIR / f"{game_id}.{old_ext}"
        if old_file.is_file():
            old_file.unlink(missing_ok=True)

    try:
        im = Image.open(BytesIO(image_bytes))
        fmt = (ext or im.format or "png").lower()
        if fmt == "jpeg":
            fmt = "jpg"

        is_anim = getattr(im, "is_animated", False)
        target_path = COVERS_DIR / f"{game_id}.{fmt}"

        if is_anim and (im.width > WIDTH or im.height > HEIGHT):
            from PIL import ImageSequence
            frames = [
                frame.copy().resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
                for frame in ImageSequence.Iterator(im)
            ]
            duration = im.info.get("duration") or 50
            save_fmt = "WEBP" if fmt == "webp" else "GIF"
            frames[0].save(
                target_path,
                format=save_fmt,
                save_all=True,
                append_images=frames[1:],
                duration=duration,
                loop=0,
            )
        else:
            target_path.write_bytes(image_bytes)

        return target_path
    except Exception:
        return None


def from_icon(icon: Gdk.Paintable) -> Gdk.Paintable | None:
    """Pad `icon` to be appropriate for a cover."""
    snapshot = Gtk.Snapshot()
    snapshot.translate(
        Graphene.Point().init(
            (WIDTH - ICON_SIZE) / 2,
            (HEIGHT - ICON_SIZE) / 2,
        )
    )
    icon.snapshot(snapshot, ICON_SIZE, ICON_SIZE)
    return snapshot.to_paintable(Graphene.Size().init(WIDTH, HEIGHT))
