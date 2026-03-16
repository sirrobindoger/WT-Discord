import logging
import os
import socket
import subprocess
import time

import psutil
import servicemanager
import win32event
import win32service
import win32serviceutil

from .constants import (
    SERVICE_DESCRIPTION,
    SERVICE_DISPLAY_NAME,
    SERVICE_NAME,
    WORKER_ARGUMENT,
    WORKER_TASK_NAME,
)


def build_service_logger():
    log_dir = os.path.join(os.environ.get("PROGRAMDATA", os.getcwd()), "WarThunderRPC")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "WarThunderRPC.log")

    logger = logging.getLogger("warthunder_rpc.service")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    file_handler = logging.FileHandler(log_path)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    return logger


class WarThunderRPCService(win32serviceutil.ServiceFramework):
    _svc_name_ = SERVICE_NAME
    _svc_display_name_ = SERVICE_DISPLAY_NAME
    _svc_description_ = SERVICE_DESCRIPTION

    def __init__(self, args):
        if args is not None:
            super().__init__(args)
            self.stop_event = win32event.CreateEvent(None, 0, 0, None)
            socket.setdefaulttimeout(60)
            self.is_running_as_service = True
        else:
            self.stop_event = None
            self.is_running_as_service = False

        self.logger = build_service_logger()
        self.check_interval = 3
        self.idle_check_interval = 10
        self.worker_launch_timeout = 8
        self.worker_task_name = WORKER_TASK_NAME
        self._shutdown_requested = False
        self._worker_launch_logged = False
        self._shutdown_logged = False
        self.logger.info("Service initialized. Running as service: %s", self.is_running_as_service)

    def SvcStop(self):
        self._shutdown_requested = True
        if self.is_running_as_service:
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            win32event.SetEvent(self.stop_event)
        self.logger.info("Service stop requested")

    def SvcDoRun(self):
        try:
            self.logger.info("Service starting...")
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, ""),
            )
            self.ReportServiceStatus(win32service.SERVICE_RUNNING)
            self.run_service()
        except Exception as exc:
            self.logger.error("Service failed: %s", exc)
            servicemanager.LogErrorMsg(f"Service failed: {exc}")

    def should_stop(self):
        if self._shutdown_requested:
            return True
        if not self.is_running_as_service:
            return False
        stopped = win32event.WaitForSingleObject(self.stop_event, 1000) == win32event.WAIT_OBJECT_0
        if stopped:
            self._shutdown_requested = True
        return stopped

    @staticmethod
    def is_worker_running():
        for process in psutil.process_iter(["cmdline"]):
            try:
                cmdline = process.info.get("cmdline") or []
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

            if WORKER_ARGUMENT in cmdline:
                return True
        return False

    def launch_worker(self):
        if self._shutdown_requested:
            return False

        try:
            subprocess.run(
                ["schtasks", "/run", "/tn", self.worker_task_name],
                check=True,
                capture_output=True,
                text=True,
                timeout=self.worker_launch_timeout,
            )
        except subprocess.TimeoutExpired:
            if not self._worker_launch_logged:
                self.logger.error("Worker launch timed out after %s seconds", self.worker_launch_timeout)
                self._worker_launch_logged = True
            return False
        except Exception as exc:
            if not self._worker_launch_logged:
                self.logger.error("Worker launch failure: %s", exc)
                self._worker_launch_logged = True
            return False

        self._worker_launch_logged = False
        self.logger.info("Requested worker start via scheduled task")
        return True

    def supervise_worker(self):
        if self._shutdown_requested:
            if not self._shutdown_logged:
                self.logger.info("Shutdown requested; skipping worker supervision")
                self._shutdown_logged = True
            return 0

        if self.is_worker_running():
            self._worker_launch_logged = False
            return self.check_interval

        launched = self.launch_worker()
        return self.idle_check_interval if launched else self.check_interval

    def _wait(self, seconds):
        if seconds <= 0:
            return
        if self.is_running_as_service:
            win32event.WaitForSingleObject(self.stop_event, int(seconds * 1000))
            return
        time.sleep(seconds)

    def run_service(self):
        try:
            self.logger.info("Starting main service loop")
            while not self.should_stop():
                wait_seconds = self.supervise_worker()
                if self._shutdown_requested:
                    break
                self._wait(wait_seconds)
        finally:
            self.logger.info("Service stopped")
