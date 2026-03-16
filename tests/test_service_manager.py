import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from warthunder_rpc.service_manager import (
    ServiceManagerError,
    _service_query_state,
    _service_start_type,
    controller_autostart_enabled,
    disable_service,
    enable_service,
    install_runtime_service,
    set_controller_autostart,
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

    def test_service_start_type_parses_sc_qc_output(self):
        output = """
SERVICE_NAME: WarThunderRPC
        TYPE               : 10  WIN32_OWN_PROCESS
        START_TYPE         : 2   AUTO_START
"""
        self.assertEqual(_service_start_type(output), "AUTO_START")

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
        def fake_run(*args, **kwargs):
            return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        with patch("warthunder_rpc.service_manager.query_service_state", return_value="RUNNING"):
            with patch("warthunder_rpc.service_manager.wait_for_condition", return_value=False):
                with self.assertRaises(ServiceManagerError):
                    stop_service(runner=fake_run, sleep=lambda _: None)

    def test_disable_service_stops_then_sets_disabled(self):
        with patch("warthunder_rpc.service_manager.stop_service") as stop_mock:
            with patch("warthunder_rpc.service_manager.set_service_start_type") as config_mock:
                disable_service()

        stop_mock.assert_called_once()
        config_mock.assert_called_once_with("disabled", runner=unittest.mock.ANY)

    def test_enable_service_sets_auto_start(self):
        with patch("warthunder_rpc.service_manager.set_service_start_type") as config_mock:
            enable_service()

        config_mock.assert_called_once_with("auto", runner=unittest.mock.ANY)

    def test_start_service_tolerates_already_running_response(self):
        completed = type("Completed", (), {"returncode": 1, "stdout": "", "stderr": "service is already running"})()

        def fake_run(*args, **kwargs):
            return completed

        with patch("warthunder_rpc.service_manager.query_service_state", return_value="RUNNING"):
            from warthunder_rpc.service_manager import start_service

            start_service(runner=fake_run, sleep=lambda _: None)


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
                with patch("warthunder_rpc.service_manager.terminate_runtime_processes", return_value=[]):
                    with patch(
                        "warthunder_rpc.service_manager.get_service_status",
                        return_value={
                            "service_installed": True,
                            "service_state": "RUNNING",
                            "service_start_type": "AUTO_START",
                            "service_running": True,
                            "task_exists": True,
                        },
                    ):
                        with patch("warthunder_rpc.service_manager.stop_and_delete_service") as stop_delete_service:
                            with patch("warthunder_rpc.service_manager.delete_task") as delete_task:
                                with patch("warthunder_rpc.service_manager.create_worker_task") as create_worker_task:
                                    with patch("warthunder_rpc.service_manager.create_service") as create_service:
                                        with patch("warthunder_rpc.service_manager.start_service") as start_service:
                                            summary = install_runtime_service(str(runtime_path), "DESKTOP\\Pilot")

            self.assertEqual(summary.runtime_path, str(runtime_path))
            self.assertEqual(summary.service_user, "DESKTOP\\Pilot")
            self.assertTrue(summary.service_running)
            self.assertTrue(summary.task_exists)
            stop_delete_service.assert_called_once()
            delete_task.assert_called_once()
            create_worker_task.assert_called_once()
            create_service.assert_called_once()
            start_service.assert_called_once()


class ControllerAutostartTests(unittest.TestCase):
    def test_controller_autostart_can_be_enabled_and_disabled(self):
        fake_registry = {}

        class FakeKey:
            pass

        def create_key(*args, **kwargs):
            return FakeKey()

        def set_value(_key, name, _reserved, _kind, value):
            fake_registry[name] = value

        def delete_value(_key, name):
            if name not in fake_registry:
                raise FileNotFoundError(name)
            del fake_registry[name]

        def query_value(_key, name):
            if name not in fake_registry:
                raise FileNotFoundError(name)
            return fake_registry[name], None

        with patch("warthunder_rpc.service_manager.winreg.CreateKey", side_effect=create_key):
            with patch("warthunder_rpc.service_manager.winreg.SetValueEx", side_effect=set_value):
                with patch("warthunder_rpc.service_manager.winreg.DeleteValue", side_effect=delete_value):
                    with patch("warthunder_rpc.service_manager.winreg.OpenKey", side_effect=create_key):
                        with patch("warthunder_rpc.service_manager.winreg.QueryValueEx", side_effect=query_value):
                            with patch("warthunder_rpc.service_manager.winreg.CloseKey"):
                                set_controller_autostart(True, command='"C:\\WarThunderRPC.exe" --controller')
                                self.assertTrue(controller_autostart_enabled())
                                set_controller_autostart(False)
                                self.assertFalse(controller_autostart_enabled())


if __name__ == "__main__":
    unittest.main()
