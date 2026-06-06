from types import SimpleNamespace
import unittest

from cartridges.game_sort_filter import (
    compare_games,
    game_is_visible,
    normalized_title,
)


def game(name, developer="", source="steam", added=0, last_played=0):
    return SimpleNamespace(
        name=name,
        developer=developer,
        base_source=source,
        added=added,
        last_played=last_played,
    )


class GameSortFilterTest(unittest.TestCase):
    def test_normalized_title_ignores_the_prefix(self):
        self.assertEqual(normalized_title("The Talos Principle"), "talos principle")

    def test_search_matches_name_or_developer(self):
        item = game("Half-Life", "Valve")

        self.assertTrue(game_is_visible(item, "half", "all"))
        self.assertTrue(game_is_visible(item, "valve", "all"))
        self.assertFalse(game_is_visible(item, "portal", "all"))

    def test_source_filter_matches_base_source(self):
        item = game("Half-Life", source="steam")

        self.assertTrue(game_is_visible(item, "", "all"))
        self.assertTrue(game_is_visible(item, "", "steam"))
        self.assertFalse(game_is_visible(item, "", "heroic"))

    def test_a_to_z_sort_uses_normalized_title(self):
        self.assertLess(compare_games(game("The Alpha"), game("Beta"), "a-z"), 0)

    def test_last_played_sort_falls_back_to_name(self):
        self.assertLess(
            compare_games(
                game("Alpha", last_played=100),
                game("Beta", last_played=100),
                "last_played",
            ),
            0,
        )


if __name__ == "__main__":
    unittest.main()
