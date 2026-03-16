import unittest
from unittest.mock import patch

from warthunder_rpc.controller import ControllerApp


class FakeVar:
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = value


class FakeRoot:
    def __init__(self):
        self.calls = []

    def after(self, delay, callback):
        self.calls.append((delay, callback))


class ControllerAppTests(unittest.TestCase):
    def _build_app(self):
        app = object.__new__(ControllerApp)
        app.message_value = FakeVar()
        app.root = FakeRoot()
        app._pending_action = None
        app._pending_action_deadline = None
        return app

    def test_run_elevated_suppresses_duplicate_pending_action(self):
        app = self._build_app()

        with patch("warthunder_rpc.controller.ctypes.windll.shell32.ShellExecuteW", return_value=33) as shell_execute:
            app.run_elevated("--service-action", "stop")
            app.run_elevated("--service-action", "stop")

        self.assertEqual(shell_execute.call_count, 1)
        self.assertEqual(app._pending_action, "stop")
        self.assertIn("already in progress", app.message_value.value)
        self.assertEqual(len(app.root.calls), 1)


if __name__ == "__main__":
    unittest.main()
