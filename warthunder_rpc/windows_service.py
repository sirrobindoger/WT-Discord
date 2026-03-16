import logging
import os
import socket

import psutil
import servicemanager
import win32event
import win32service
import win32serviceutil

from .runtime import RuntimeOptions, WarThunderRPCApp


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
    _svc_description_ = "Provides Discord Rich Presence integration for War Thunder"

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
    def is_aces_running():
        for process in psutil.process_iter(["name"]):
            try:
                if (process.info.get("name") or "").lower() == "aces.exe":
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        return False

    def run_service(self):
        app = WarThunderRPCApp(
            RuntimeOptions(
                mode="service",
                prompt_for_username=False,
                check_process_running=self.is_aces_running,
                logger=self.logger,
                stop_requested=self.should_stop,
                active_interval=self.check_interval,
                idle_interval=self.idle_check_interval,
            )
        )

        try:
            app.run_forever()
        finally:
            app.disconnect_rpc()
            self.logger.info("Service stopped")
