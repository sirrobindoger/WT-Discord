from __future__ import annotations

import ctypes
import os
import subprocess
import time
from dataclasses import asdict
from dataclasses import dataclass
from typing import Callable

import psutil
import winreg

from .constants import (
    AUTOSTART_VALUE_NAME,
    RUNTIME_EXE_NAME,
    SERVICE_DESCRIPTION,
    SERVICE_DISPLAY_NAME,
    SERVICE_NAME,
    WORKER_ARGUMENT,
    WORKER_TASK_NAME,
)


CommandRunner = Callable[..., subprocess.CompletedProcess]
AUTOSTART_REGISTRY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


class ServiceManagerError(RuntimeError):
    pass


@dataclass(slots=True)
class InstallSummary:
    runtime_path: str
    service_user: str
    service_name: str = SERVICE_NAME
    task_name: str = WORKER_TASK_NAME
    service_created: bool = False
    service_running: bool = False
    task_created: bool = False
    task_exists: bool = False
    warnings: list[str] | None = None

    def to_dict(self):
        data = asdict(self)
        data["warnings"] = list(self.warnings or [])
        return data


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _run_command(
    command,
    *,
    check=True,
    runner: CommandRunner = subprocess.run,
):
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    completed = runner(command, capture_output=True, text=True, check=False, creationflags=creationflags)
    if check and completed.returncode != 0:
        raise ServiceManagerError(_format_command_error(command, completed))
    return completed


def _format_command_error(command, completed):
    stderr = (completed.stderr or "").strip()
    stdout = (completed.stdout or "").strip()
    details = stderr or stdout or f"exit code {completed.returncode}"
    rendered = " ".join(command)
    return f"{rendered} failed: {details}"


def _command_output(completed):
    return f"{completed.stdout}\n{completed.stderr}".lower()


def _service_query_state(output):
    for raw_line in (output or "").splitlines():
        line = raw_line.strip()
        if not line.startswith("STATE"):
            continue

        parts = line.split()
        if len(parts) >= 4:
            return parts[3]
    return None


def _service_start_type(output):
    for raw_line in (output or "").splitlines():
        line = raw_line.strip()
        if not line.startswith("START_TYPE"):
            continue

        parts = line.split()
        if len(parts) >= 4:
            return parts[3]
    return None


def query_service_state(service_name=SERVICE_NAME, *, runner: CommandRunner = subprocess.run):
    completed = _run_command(["sc", "query", service_name], check=False, runner=runner)
    if completed.returncode != 0:
        missing_tokens = ("does not exist", "1060")
        combined = _command_output(completed)
        if any(token in combined for token in missing_tokens):
            return None
        raise ServiceManagerError(_format_command_error(["sc", "query", service_name], completed))
    return _service_query_state(completed.stdout)


def query_service_start_type(service_name=SERVICE_NAME, *, runner: CommandRunner = subprocess.run):
    completed = _run_command(["sc", "qc", service_name], check=False, runner=runner)
    if completed.returncode != 0:
        combined = _command_output(completed)
        if "does not exist" in combined or "1060" in combined:
            return None
        raise ServiceManagerError(_format_command_error(["sc", "qc", service_name], completed))
    return _service_start_type(completed.stdout)


def query_task_exists(task_name=WORKER_TASK_NAME, *, runner: CommandRunner = subprocess.run):
    completed = _run_command(
        ["schtasks", "/query", "/tn", task_name],
        check=False,
        runner=runner,
    )
    if completed.returncode == 0:
        return True

    combined = _command_output(completed)
    if "cannot find the file" in combined or "cannot find the task" in combined:
        return False
    raise ServiceManagerError(_format_command_error(["schtasks", "/query", "/tn", task_name], completed))


def get_service_status(*, runner: CommandRunner = subprocess.run):
    try:
        state = query_service_state(runner=runner)
    except ServiceManagerError:
        state = None

    try:
        start_type = query_service_start_type(runner=runner)
    except ServiceManagerError:
        start_type = None

    try:
        task_exists = query_task_exists(runner=runner)
    except ServiceManagerError:
        task_exists = False

    return {
        "service_installed": state is not None,
        "service_state": state or "NOT_INSTALLED",
        "service_start_type": start_type or "UNKNOWN",
        "service_running": state == "RUNNING",
        "task_exists": task_exists,
    }


def wait_for_condition(predicate, *, timeout_seconds=30, interval_seconds=0.5, sleep=time.sleep):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        sleep(interval_seconds)
    return predicate()


def stop_service(service_name=SERVICE_NAME, *, runner: CommandRunner = subprocess.run, sleep=time.sleep):
    state = query_service_state(service_name, runner=runner)
    if state is None or state == "STOPPED":
        return

    completed = _run_command(["sc", "stop", service_name], check=False, runner=runner)
    combined = _command_output(completed)
    if completed.returncode != 0 and "service has not been started" not in combined:
        current_state = query_service_state(service_name, runner=runner)
        if current_state not in (None, "STOPPED", "STOP_PENDING"):
            raise ServiceManagerError(_format_command_error(["sc", "stop", service_name], completed))

    stopped = wait_for_condition(
        lambda: query_service_state(service_name, runner=runner) in (None, "STOPPED"),
        timeout_seconds=60,
        sleep=sleep,
    )
    if not stopped:
        raise ServiceManagerError(f"Timed out waiting for service {service_name} to stop")


def set_service_start_type(start_type, service_name=SERVICE_NAME, *, runner: CommandRunner = subprocess.run):
    _run_command(["sc", "config", service_name, "start=", start_type], runner=runner)


def disable_service(*, runner: CommandRunner = subprocess.run, sleep=time.sleep):
    stop_service(runner=runner, sleep=sleep)
    set_service_start_type("disabled", runner=runner)


def enable_service(*, runner: CommandRunner = subprocess.run):
    set_service_start_type("auto", runner=runner)


def delete_service(service_name=SERVICE_NAME, *, runner: CommandRunner = subprocess.run, sleep=time.sleep):
    state = query_service_state(service_name, runner=runner)
    if state is None:
        return

    completed = _run_command(["sc", "delete", service_name], check=False, runner=runner)
    combined = _command_output(completed)
    if completed.returncode != 0 and "marked for deletion" not in combined:
        current_state = query_service_state(service_name, runner=runner)
        if current_state is not None:
            raise ServiceManagerError(_format_command_error(["sc", "delete", service_name], completed))

    deleted = wait_for_condition(
        lambda: query_service_state(service_name, runner=runner) is None,
        timeout_seconds=90,
        sleep=sleep,
    )
    if not deleted:
        raise ServiceManagerError(f"Timed out waiting for service {service_name} to be deleted")


def stop_and_delete_service(service_name=SERVICE_NAME, *, runner: CommandRunner = subprocess.run, sleep=time.sleep):
    stop_service(service_name, runner=runner, sleep=sleep)
    delete_service(service_name, runner=runner, sleep=sleep)


def delete_task(task_name=WORKER_TASK_NAME, *, runner: CommandRunner = subprocess.run, sleep=time.sleep):
    exists = query_task_exists(task_name, runner=runner)
    if not exists:
        return

    _run_command(["schtasks", "/end", "/tn", task_name], check=False, runner=runner)
    _run_command(["schtasks", "/delete", "/f", "/tn", task_name], check=False, runner=runner)
    deleted = wait_for_condition(
        lambda: not query_task_exists(task_name, runner=runner),
        sleep=sleep,
    )
    if not deleted:
        raise ServiceManagerError(f"Timed out waiting for task {task_name} to be deleted")


def create_worker_task(
    runtime_path,
    service_user,
    *,
    task_name=WORKER_TASK_NAME,
    runner: CommandRunner = subprocess.run,
):
    worker_cmd = f'"{runtime_path}" {WORKER_ARGUMENT}'
    _run_command(
        [
            "schtasks",
            "/create",
            "/f",
            "/tn",
            task_name,
            "/sc",
            "ONLOGON",
            "/tr",
            worker_cmd,
            "/ru",
            service_user,
            "/rl",
            "HIGHEST",
        ],
        runner=runner,
    )


def create_service(runtime_path, *, service_name=SERVICE_NAME, runner: CommandRunner = subprocess.run):
    service_cmd = f'"{runtime_path}" --service'
    _run_command(
        [
            "sc",
            "create",
            service_name,
            "type=",
            "own",
            "start=",
            "auto",
            "binPath=",
            service_cmd,
            "DisplayName=",
            SERVICE_DISPLAY_NAME,
            "error=",
            "normal",
        ],
        runner=runner,
    )
    _run_command(["sc", "description", service_name, SERVICE_DESCRIPTION], runner=runner)
    _run_command(
        [
            "sc",
            "failure",
            service_name,
            "reset=",
            "86400",
            "actions=",
            "restart/60000/restart/60000/restart/60000",
        ],
        runner=runner,
    )


def start_service(service_name=SERVICE_NAME, *, runner: CommandRunner = subprocess.run, sleep=time.sleep):
    completed = _run_command(["sc", "start", service_name], check=False, runner=runner)
    combined = _command_output(completed)
    if completed.returncode != 0 and "already running" not in combined:
        current_state = query_service_state(service_name, runner=runner)
        if current_state not in ("RUNNING", "START_PENDING"):
            raise ServiceManagerError(_format_command_error(["sc", "start", service_name], completed))

    running = wait_for_condition(
        lambda: query_service_state(service_name, runner=runner) == "RUNNING",
        timeout_seconds=60,
        sleep=sleep,
    )
    if not running:
        raise ServiceManagerError(f"Timed out waiting for service {service_name} to start")


def get_runtime_processes():
    current_pid = os.getpid()
    matches = []
    for process in psutil.process_iter(["pid", "name", "exe", "cmdline"]):
        try:
            exe = process.info.get("exe") or ""
            name = process.info.get("name") or ""
            cmdline = process.info.get("cmdline") or []
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

        exe_name = os.path.basename(exe).lower() if exe else ""
        if exe_name != RUNTIME_EXE_NAME.lower() and name.lower() != RUNTIME_EXE_NAME.lower():
            continue

        if process.pid == current_pid:
            continue

        if "--service" in cmdline:
            continue

        matches.append(process)
    return matches


def terminate_runtime_processes(*, wait_seconds=10):
    processes = get_runtime_processes()
    if not processes:
        return []

    for process in processes:
        try:
            process.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    gone, alive = psutil.wait_procs(processes, timeout=wait_seconds)
    for process in alive:
        try:
            process.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    psutil.wait_procs(alive, timeout=3)
    return [process.pid for process in gone + alive]


def get_controller_autostart_command():
    runtime_path = resolve_runtime_path(os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "WarThunderRPC", RUNTIME_EXE_NAME))
    return f'"{runtime_path}" --controller'


def set_controller_autostart(enabled, command=None):
    registry_key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, AUTOSTART_REGISTRY_PATH)
    try:
        if enabled:
            winreg.SetValueEx(
                registry_key,
                AUTOSTART_VALUE_NAME,
                0,
                winreg.REG_SZ,
                command or get_controller_autostart_command(),
            )
        else:
            try:
                winreg.DeleteValue(registry_key, AUTOSTART_VALUE_NAME)
            except FileNotFoundError:
                pass
    finally:
        winreg.CloseKey(registry_key)


def controller_autostart_enabled():
    try:
        registry_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_REGISTRY_PATH, 0, winreg.KEY_READ)
        value, _ = winreg.QueryValueEx(registry_key, AUTOSTART_VALUE_NAME)
        winreg.CloseKey(registry_key)
        return bool(str(value).strip())
    except FileNotFoundError:
        return False
    except OSError:
        return False


def start_worker_task(task_name=WORKER_TASK_NAME, *, runner: CommandRunner = subprocess.run):
    _run_command(["schtasks", "/run", "/tn", task_name], runner=runner)


def get_current_user(*, runner: CommandRunner = subprocess.run):
    try:
        completed = _run_command(["whoami"], runner=runner)
        return completed.stdout.strip()
    except Exception:
        return os.environ.get("USERNAME", "").strip()


def resolve_runtime_path(executable_path=None):
    candidate = executable_path or os.path.abspath(RUNTIME_EXE_NAME)
    return os.path.abspath(candidate)


def install_runtime_service(
    runtime_path,
    service_user,
    *,
    runner: CommandRunner = subprocess.run,
    sleep=time.sleep,
):
    if not is_admin():
        raise ServiceManagerError(
            "Administrator privileges are required because this install creates a Windows service and scheduled task."
        )

    runtime_path = resolve_runtime_path(runtime_path)
    if not os.path.exists(runtime_path):
        raise ServiceManagerError(f"Runtime executable not found: {runtime_path}")

    warnings = []

    terminated_pids = terminate_runtime_processes()
    if terminated_pids:
        warnings.append(f"Terminated stray runtime processes: {', '.join(str(pid) for pid in terminated_pids)}")

    try:
        stop_and_delete_service(runner=runner, sleep=sleep)
    except ServiceManagerError as exc:
        warnings.append(str(exc))

    try:
        delete_task(runner=runner, sleep=sleep)
    except ServiceManagerError as exc:
        warnings.append(str(exc))

    task_created = False
    try:
        create_worker_task(runtime_path, service_user, runner=runner)
        task_created = True
    except ServiceManagerError as exc:
        warnings.append(str(exc))

    service_created = False
    try:
        create_service(runtime_path, runner=runner)
        service_created = True
    except ServiceManagerError as exc:
        warnings.append(str(exc))

    try:
        start_service(runner=runner, sleep=sleep)
    except ServiceManagerError as exc:
        warnings.append(str(exc))

    status = get_service_status(runner=runner)
    service_running = bool(status["service_running"])
    task_exists = bool(status["task_exists"])

    if not service_running or not task_exists:
        details = (
            f"Failed to verify final install state: "
            f"service_state={status['service_state']}, task_exists={task_exists}."
        )
        if warnings:
            details = f"{details} Warnings: {' | '.join(warnings)}"
        raise ServiceManagerError(details)

    return InstallSummary(
        runtime_path=runtime_path,
        service_user=service_user,
        service_created=service_created,
        service_running=service_running,
        task_created=task_created,
        task_exists=task_exists,
        warnings=warnings,
    )


def uninstall_runtime_service(
    *,
    runner: CommandRunner = subprocess.run,
    sleep=time.sleep,
):
    if not is_admin():
        raise ServiceManagerError(
            "Administrator privileges are required because uninstall removes a Windows service and scheduled task."
        )

    terminate_runtime_processes()
    stop_and_delete_service(runner=runner, sleep=sleep)
    delete_task(runner=runner, sleep=sleep)
    set_controller_autostart(False)


__all__ = [
    "InstallSummary",
    "ServiceManagerError",
    "controller_autostart_enabled",
    "create_service",
    "create_worker_task",
    "delete_service",
    "delete_task",
    "disable_service",
    "enable_service",
    "get_current_user",
    "get_controller_autostart_command",
    "get_runtime_processes",
    "get_service_status",
    "install_runtime_service",
    "is_admin",
    "query_service_state",
    "query_service_start_type",
    "query_task_exists",
    "resolve_runtime_path",
    "set_controller_autostart",
    "set_service_start_type",
    "start_service",
    "start_worker_task",
    "stop_and_delete_service",
    "stop_service",
    "terminate_runtime_processes",
    "uninstall_runtime_service",
    "wait_for_condition",
]
