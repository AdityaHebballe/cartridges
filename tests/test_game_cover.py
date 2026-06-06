from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from cartridges.game_cover import GameCover


class FakePicture:
    def __init__(self):
        self.paintable = None
        self.draws = 0

    def is_visible(self):
        return True

    def set_paintable(self, paintable):
        self.paintable = paintable

    def queue_draw(self):
        self.draws += 1


class FakePixbuf:
    def savev(self, path, _file_type):
        Path(path).write_bytes(b"poster")


class FakeIter:
    def advance(self):
        return True

    def get_pixbuf(self):
        return FakePixbuf()

    def get_delay_time(self):
        return 100


class FakeAnimation:
    def get_static_image(self):
        return FakePixbuf()

    def get_iter(self):
        return FakeIter()

    def is_static_image(self):
        return False


class GameCoverTest(unittest.TestCase):
    def setUp(self):
        self.patches = [
            patch(
                "cartridges.game_cover.GdkPixbuf.PixbufAnimation.new_from_file",
                return_value=FakeAnimation(),
            ),
            patch(
                "cartridges.game_cover.Gdk.Texture.new_for_pixbuf",
                return_value=object(),
            ),
            patch(
                "cartridges.game_cover.Gdk.Texture.new_from_filename",
                return_value=object(),
            ),
        ]
        for patcher in self.patches:
            patcher.start()

    def tearDown(self):
        GameCover.stop_all_animations()
        for patcher in reversed(self.patches):
            patcher.stop()

    def test_gif_static_load_writes_and_reuses_poster(self):
        with TemporaryDirectory() as tmpdir:
            gif_path = Path(tmpdir) / "game.gif"
            poster_path = Path(tmpdir) / "game.poster.png"
            gif_path.write_bytes(b"gif")

            first_cover = GameCover(set(), gif_path)
            self.assertIsNotNone(first_cover.texture)
            self.assertTrue(poster_path.is_file())

            second_cover = GameCover(set(), gif_path)
            self.assertIsNotNone(second_cover.texture)
            self.assertIsNone(second_cover.animation)

    def test_animation_uses_shared_active_set_and_can_stop_all(self):
        with TemporaryDirectory() as tmpdir:
            gif_path = Path(tmpdir) / "game.gif"
            gif_path.write_bytes(b"gif")

            picture = FakePicture()
            cover = GameCover({picture}, gif_path)
            cover.start_animation()

            self.assertIn(cover, GameCover.active_animations)
            GameCover.stop_all_animations()
            self.assertNotIn(cover, GameCover.active_animations)


if __name__ == "__main__":
    unittest.main()
