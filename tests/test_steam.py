from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cartridges.utils.steam import SteamFileHelper


def field(value_type: int, key: str, value=b"") -> bytes:
    return bytes([value_type]) + key.encode() + b"\x00" + value


class SteamFileHelperTest(unittest.TestCase):
    def test_get_shortcut_data_reads_binary_vdf(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "shortcuts.vdf"
            path.write_bytes(
                field(
                    0,
                    "shortcuts",
                    field(
                        0,
                        "0",
                        field(2, "appid", (3117560295).to_bytes(4, "little"))
                        + field(1, "AppName", b"Tainted Grail Fall of Avalon\x00")
                        + field(1, "Exe", b"/games/Tainted Grail.exe\x00")
                        + field(2, "IsHidden", (0).to_bytes(4, "little"))
                        + b"\x08",
                    )
                    + b"\x08",
                )
                + b"\x08"
            )

            shortcuts = SteamFileHelper().get_shortcut_data(path)

        self.assertEqual(
            shortcuts,
            [
                {
                    "appid": "3117560295",
                    "shortcut_appid": "13389819510366666752",
                    "name": "Tainted Grail Fall of Avalon",
                    "executable": "/games/Tainted Grail.exe",
                    "hidden": False,
                    "grid_dir": path.parent / "grid",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
