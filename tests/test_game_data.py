from types import SimpleNamespace
import unittest

from cartridges.game_data import GameObject, normalize_game_values, persisted_game_values
from gi.repository import GObject


class FakeGame(GObject.Object):
    def __init__(self):
        super().__init__()
        self.added = 1
        self.executable = "run"
        self.game_id = "game_1"
        self.source = "steam_1"
        self.base_source = "steam"
        self.hidden = False
        self.last_played = 2
        self.name = "Game"
        self.developer = None
        self.removed = False
        self.blacklisted = False
        self.version = 1

    @GObject.Signal(name="update-ready", arg_types=[object])
    def update_ready(self, _additional_data):  # type: ignore
        """Signal emitted when the game needs updating"""


class GameDataTest(unittest.TestCase):
    def test_game_object_exposes_game_properties(self):
        game = FakeGame()
        game_object = GameObject(game)

        self.assertEqual(game_object.game, game)
        self.assertEqual(game_object.game_id, "game_1")
        self.assertEqual(game_object.source, "steam_1")
        self.assertEqual(game_object.base_source, "steam")
        self.assertEqual(game_object.name, "Game")
        self.assertEqual(game_object.developer, "")
        self.assertFalse(game_object.hidden)
        self.assertFalse(game_object.removed)
        self.assertFalse(game_object.blacklisted)
        self.assertEqual(game_object.added, 1)
        self.assertEqual(game_object.last_played, 2)

    def test_game_object_notifies_when_game_updates(self):
        game = FakeGame()
        game_object = GameObject(game)
        notified = []

        game_object.connect("notify::name", lambda *_args: notified.append("name"))
        game.name = "Updated"
        game.emit("update-ready", {})

        self.assertEqual(game_object.name, "Updated")
        self.assertEqual(notified, ["name"])

    def test_normalizes_executable_lists(self):
        values = normalize_game_values({"executable": ["foo bar", "--flag"]})

        self.assertEqual(values["executable"], "'foo bar' --flag")

    def test_persisted_values_contains_only_saved_fields(self):
        game = SimpleNamespace(
            added=1,
            executable="run",
            game_id="game_1",
            source="steam",
            hidden=False,
            last_played=2,
            name="Game",
            developer=None,
            removed=False,
            blacklisted=False,
            version=1.5,
            widget_only="ignore",
        )

        self.assertEqual(
            persisted_game_values(game),
            {
                "added": 1,
                "executable": "run",
                "game_id": "game_1",
                "source": "steam",
                "hidden": False,
                "last_played": 2,
                "name": "Game",
                "developer": None,
                "removed": False,
                "blacklisted": False,
                "version": 1.5,
            },
        )


if __name__ == "__main__":
    unittest.main()
