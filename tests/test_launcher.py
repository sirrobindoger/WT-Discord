import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from warthunder_rpc.launcher import main
from warthunder_rpc.service_manager import InstallSummary
from warthunder_rpc.service_manager import ServiceManagerError


class LauncherJsonOutputTests(unittest.TestCase):
    def test_status_json_reports_machine_readable_status(self):
        with patch("warthunder_rpc.launcher.get_service_status", return_value={"service_installed": True, "service_state": "RUNNING", "service_start_type": "AUTO_START", "service_running": True, "task_exists": True}):
            with patch("warthunder_rpc.launcher.controller_autostart_enabled", return_value=True):
                with patch("warthunder_rpc.launcher.read_username", return_value="Pilot"):
                    output = io.StringIO()
                    with redirect_stdout(output):
                        with self.assertRaises(SystemExit) as exc:
                            main(["--status-json"])

        self.assertEqual(exc.exception.code, 0)
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["service_running"])
        self.assertTrue(payload["task_exists"])
        self.assertEqual(payload["username"], "Pilot")

    def test_install_service_outputs_json_success(self):
        summary = InstallSummary(
            runtime_path="C:\\Program Files\\WarThunderRPC\\WarThunderRPC.exe",
            service_user="DESKTOP\\Pilot",
            service_created=True,
            service_running=True,
            task_created=True,
            task_exists=True,
            warnings=["Recovered from existing service state"],
        )
        with patch("warthunder_rpc.launcher.read_username", return_value="Pilot"):
            with patch("warthunder_rpc.launcher.get_current_user", return_value="DESKTOP\\Pilot"):
                with patch("warthunder_rpc.launcher.install_runtime_service", return_value=summary):
                    with patch("warthunder_rpc.launcher.get_service_status", return_value={"service_installed": True, "service_state": "RUNNING", "service_start_type": "AUTO_START", "service_running": True, "task_exists": True}):
                        with patch("warthunder_rpc.launcher.controller_autostart_enabled", return_value=True):
                            output = io.StringIO()
                            with redirect_stdout(output):
                                with self.assertRaises(SystemExit) as exc:
                                    main(["--install-service", "--runtime-path", "C:\\Program Files\\WarThunderRPC\\WarThunderRPC.exe"])

        self.assertEqual(exc.exception.code, 0)
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["success"])
        self.assertTrue(payload["result"]["service_running"])
        self.assertTrue(payload["status"]["task_exists"])

    def test_install_service_outputs_json_failure(self):
        with patch("warthunder_rpc.launcher.read_username", return_value="Pilot"):
            with patch("warthunder_rpc.launcher.get_current_user", return_value="DESKTOP\\Pilot"):
                with patch("warthunder_rpc.launcher.install_runtime_service", side_effect=ServiceManagerError("failed")):
                    with patch("warthunder_rpc.launcher.get_service_status", return_value={"service_installed": True, "service_state": "RUNNING", "service_start_type": "AUTO_START", "service_running": True, "task_exists": True}):
                        with patch("warthunder_rpc.launcher.controller_autostart_enabled", return_value=False):
                            output = io.StringIO()
                            with redirect_stdout(output):
                                with self.assertRaises(SystemExit) as exc:
                                    main(["--install-service", "--runtime-path", "C:\\Program Files\\WarThunderRPC\\WarThunderRPC.exe"])

        self.assertEqual(exc.exception.code, 1)
        payload = json.loads(output.getvalue())
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"], "failed")

    def test_status_json_exits_0_on_service_manager_error(self):
        with patch("warthunder_rpc.launcher.get_service_status", side_effect=ServiceManagerError("sc query failed")):
            output = io.StringIO()
            with redirect_stdout(output):
                with self.assertRaises(SystemExit) as exc:
                    main(["--status-json"])

        self.assertEqual(exc.exception.code, 0)
        payload = json.loads(output.getvalue())
        self.assertFalse(payload["service_running"])
        self.assertFalse(payload["task_exists"])
        self.assertIn("status_error", payload)


if __name__ == "__main__":
    unittest.main()
