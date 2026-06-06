from types import SimpleNamespace
import unittest

from cartridges.game_data import normalize_game_values, persisted_game_values


class GameDataTest(unittest.TestCase):
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
