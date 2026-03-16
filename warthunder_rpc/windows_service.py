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


WORKER_TASK_NAME = "WarThunderRPCWorker"
WORKER_ARGUMENT = "--worker"


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
    _svc_name_ = "WarThunderRPC"
    _svc_display_name_ = "War Thunder Discord Rich Presence"
    _svc_description_ = "Supervises the War Thunder Discord Rich Presence worker"

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
        self.worker_task_name = WORKER_TASK_NAME
        self._worker_launch_logged = False
        self.logger.info("Service initialized. Running as service: %s", self.is_running_as_service)

    def SvcStop(self):
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
        if not self.is_running_as_service:
            return False
        return win32event.WaitForSingleObject(self.stop_event, 1000) == win32event.WAIT_OBJECT_0

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
        try:
            subprocess.run(
                ["schtasks", "/run", "/tn", self.worker_task_name],
                check=True,
                capture_output=True,
                text=True,
            )
        except Exception as exc:
            if not self._worker_launch_logged:
                self.logger.error("Worker launch failure: %s", exc)
                self._worker_launch_logged = True
            return False

        self._worker_launch_logged = False
        self.logger.info("Requested worker start via scheduled task")
        return True

    def supervise_worker(self):
        if self.is_worker_running():
            self._worker_launch_logged = False
            return self.check_interval

        self.launch_worker()
        return self.idle_check_interval

    def _wait(self, seconds):
        if seconds <= 0:
            return
        if self.is_running_as_service:
            win32event.WaitForSingleObject(self.stop_event, int(seconds * 1000))
            return
        time.sleep(seconds)

    def run_service(self):
        try:
            while not self.should_stop():
                self._wait(self.supervise_worker())
        finally:
            self.logger.info("Service stopped")
