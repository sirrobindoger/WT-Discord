import subprocess
import unittest
from unittest.mock import Mock, patch

from warthunder_rpc.windows_service import WarThunderRPCService


class WindowsServiceTests(unittest.TestCase):
    def _build_service(self):
        logger = Mock()
        with patch("warthunder_rpc.windows_service.build_service_logger", return_value=logger):
            service = WarThunderRPCService(None)
        return service, logger

    def test_svc_stop_marks_shutdown_requested(self):
        service, logger = self._build_service()

        service.SvcStop()

        self.assertTrue(service._shutdown_requested)
        logger.info.assert_any_call("Service stop requested")

    def test_supervise_worker_skips_launch_during_shutdown(self):
        service, _logger = self._build_service()
        service._shutdown_requested = True

        with patch.object(service, "launch_worker") as launch_worker:
            wait_seconds = service.supervise_worker()

        self.assertEqual(wait_seconds, 0)
        launch_worker.assert_not_called()

    def test_launch_worker_handles_timeout(self):
        service, logger = self._build_service()

        with patch(
            "warthunder_rpc.windows_service.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["schtasks"], timeout=service.worker_launch_timeout),
        ):
            launched = service.launch_worker()

        self.assertFalse(launched)
        logger.error.assert_any_call("Worker launch timed out after %s seconds", service.worker_launch_timeout)

    def test_run_service_logs_stopped_after_stop_request(self):
        service, logger = self._build_service()

        service.SvcStop()
        service.run_service()

        logger.info.assert_any_call("Service stop requested")
        logger.info.assert_any_call("Service stopped")


if __name__ == "__main__":
    unittest.main()
