import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from warthunder_rpc import user_config


class UserConfigTests(unittest.TestCase):
    def test_write_and_read_username_use_per_user_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            appdata = Path(temp_dir) / "AppData" / "Roaming"
            with patch.dict("os.environ", {"APPDATA": str(appdata)}, clear=False):
                user_config.write_username("PilotOne")
                self.assertEqual(user_config.read_username(), "PilotOne")

                config_path = user_config.get_config_path()
                self.assertTrue(config_path.exists())
                payload = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertEqual(payload["username"], "PilotOne")

    def test_read_username_migrates_legacy_registry_value(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            appdata = Path(temp_dir) / "AppData" / "Roaming"
            with patch.dict("os.environ", {"APPDATA": str(appdata)}, clear=False):
                with patch("warthunder_rpc.user_config.read_legacy_username", return_value="LegacyPilot"):
                    self.assertEqual(user_config.read_username(), "LegacyPilot")
                    self.assertEqual(user_config.read_username(migrate_legacy=False), "LegacyPilot")

    def test_write_username_rejects_blank_values(self):
        with self.assertRaises(ValueError):
            user_config.write_username("   ")


if __name__ == "__main__":
    unittest.main()
