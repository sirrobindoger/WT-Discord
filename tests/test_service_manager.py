import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from warthunder_rpc.service_manager import (
    ServiceManagerError,
    _service_query_state,
    install_runtime_service,
    stop_service,
)


class ServiceManagerHelpersTests(unittest.TestCase):
    def test_service_query_state_parses_sc_output(self):
        output = """
SERVICE_NAME: WarThunderRPC
        TYPE               : 10  WIN32_OWN_PROCESS
        STATE              : 4  RUNNING
                                (STOPPABLE, NOT_PAUSABLE, ACCEPTS_SHUTDOWN)
"""
        self.assertEqual(_service_query_state(output), "RUNNING")

    def test_stop_service_polls_until_service_stops(self):
        states = iter(["RUNNING", "STOP_PENDING", "STOPPED"])
        run_calls = []

        def fake_run(command, **kwargs):
            run_calls.append(command)
            return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        with patch("warthunder_rpc.service_manager.query_service_state", side_effect=lambda *args, **kwargs: next(states)):
            stop_service(runner=fake_run, sleep=lambda _: None)

        self.assertEqual(run_calls, [["sc", "stop", "WarThunderRPC"]])

    def test_stop_service_raises_on_timeout(self):
        with patch("warthunder_rpc.service_manager.query_service_state", return_value="RUNNING"):
            with patch("warthunder_rpc.service_manager.wait_for_condition", return_value=False):
                with self.assertRaises(ServiceManagerError):
                    stop_service(runner=lambda *args, **kwargs: None, sleep=lambda _: None)


class InstallRuntimeServiceTests(unittest.TestCase):
    def test_install_runtime_service_requires_admin(self):
        with self.assertRaises(ServiceManagerError):
            with patch("warthunder_rpc.service_manager.is_admin", return_value=False):
                install_runtime_service("C:\\WarThunderRPC.exe", "DESKTOP\\Pilot")

    def test_install_runtime_service_recreates_components(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_path = Path(temp_dir) / "WarThunderRPC.exe"
            runtime_path.write_text("binary", encoding="utf-8")

            with patch("warthunder_rpc.service_manager.is_admin", return_value=True):
                with patch("warthunder_rpc.service_manager.stop_and_delete_service") as stop_delete_service:
                    with patch("warthunder_rpc.service_manager.delete_task") as delete_task:
                        with patch("warthunder_rpc.service_manager.create_worker_task") as create_worker_task:
                            with patch("warthunder_rpc.service_manager.create_service") as create_service:
                                with patch("warthunder_rpc.service_manager.start_service") as start_service:
                                    with patch("warthunder_rpc.service_manager.start_worker_task") as start_worker_task:
                                        summary = install_runtime_service(str(runtime_path), "DESKTOP\\Pilot")

            self.assertEqual(summary.runtime_path, str(runtime_path))
            self.assertEqual(summary.service_user, "DESKTOP\\Pilot")
            stop_delete_service.assert_called_once()
            delete_task.assert_called_once()
            create_worker_task.assert_called_once()
            create_service.assert_called_once()
            start_service.assert_called_once()
            start_worker_task.assert_called_once()


if __name__ == "__main__":
    unittest.main()
