from __future__ import annotations

import ctypes
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Callable, Optional

from .constants import (
    RUNTIME_EXE_NAME,
    SERVICE_DESCRIPTION,
    SERVICE_DISPLAY_NAME,
    SERVICE_NAME,
    WORKER_ARGUMENT,
    WORKER_TASK_NAME,
)


CommandRunner = Callable[..., subprocess.CompletedProcess]


class ServiceManagerError(RuntimeError):
    pass


@dataclass(slots=True)
class InstallSummary:
    runtime_path: str
    service_user: str
    service_name: str = SERVICE_NAME
    task_name: str = WORKER_TASK_NAME


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
    completed = runner(command, capture_output=True, text=True, check=False)
    if check and completed.returncode != 0:
        raise ServiceManagerError(_format_command_error(command, completed))
    return completed


def _format_command_error(command, completed):
    stderr = (completed.stderr or "").strip()
    stdout = (completed.stdout or "").strip()
    details = stderr or stdout or f"exit code {completed.returncode}"
    rendered = " ".join(command)
    return f"{rendered} failed: {details}"


def _service_query_state(output):
    for raw_line in (output or "").splitlines():
        line = raw_line.strip()
        if not line.startswith("STATE"):
            continue

        parts = line.split()
        if len(parts) >= 4:
            return parts[3]
    return None


def query_service_state(service_name=SERVICE_NAME, *, runner: CommandRunner = subprocess.run):
    completed = _run_command(["sc", "query", service_name], check=False, runner=runner)
    if completed.returncode != 0:
        missing_tokens = ("does not exist", "1060")
        combined = f"{completed.stdout}\n{completed.stderr}".lower()
        if any(token in combined for token in missing_tokens):
            return None
        raise ServiceManagerError(_format_command_error(["sc", "query", service_name], completed))
    return _service_query_state(completed.stdout)


def query_task_exists(task_name=WORKER_TASK_NAME, *, runner: CommandRunner = subprocess.run):
    completed = _run_command(
        ["schtasks", "/query", "/tn", task_name],
        check=False,
        runner=runner,
    )
    if completed.returncode == 0:
        return True

    combined = f"{completed.stdout}\n{completed.stderr}".lower()
    if "cannot find the file" in combined or "cannot find the task" in combined:
        return False
    raise ServiceManagerError(_format_command_error(["schtasks", "/query", "/tn", task_name], completed))


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

    _run_command(["sc", "stop", service_name], check=False, runner=runner)
    stopped = wait_for_condition(
        lambda: query_service_state(service_name, runner=runner) in (None, "STOPPED"),
        sleep=sleep,
    )
    if not stopped:
        raise ServiceManagerError(f"Timed out waiting for service {service_name} to stop")


def delete_service(service_name=SERVICE_NAME, *, runner: CommandRunner = subprocess.run, sleep=time.sleep):
    state = query_service_state(service_name, runner=runner)
    if state is None:
        return

    _run_command(["sc", "delete", service_name], check=False, runner=runner)
    deleted = wait_for_condition(
        lambda: query_service_state(service_name, runner=runner) is None,
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
    _run_command(["sc", "start", service_name], runner=runner)
    running = wait_for_condition(
        lambda: query_service_state(service_name, runner=runner) == "RUNNING",
        sleep=sleep,
    )
    if not running:
        raise ServiceManagerError(f"Timed out waiting for service {service_name} to start")


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

    stop_and_delete_service(runner=runner, sleep=sleep)
    delete_task(runner=runner, sleep=sleep)
    create_worker_task(runtime_path, service_user, runner=runner)
    create_service(runtime_path, runner=runner)
    start_service(runner=runner, sleep=sleep)
    start_worker_task(runner=runner)
    return InstallSummary(runtime_path=runtime_path, service_user=service_user)


def uninstall_runtime_service(
    *,
    runner: CommandRunner = subprocess.run,
    sleep=time.sleep,
):
    if not is_admin():
        raise ServiceManagerError(
            "Administrator privileges are required because uninstall removes a Windows service and scheduled task."
        )

    stop_and_delete_service(runner=runner, sleep=sleep)
    delete_task(runner=runner, sleep=sleep)


__all__ = [
    "InstallSummary",
    "ServiceManagerError",
    "create_service",
    "create_worker_task",
    "delete_service",
    "delete_task",
    "get_current_user",
    "install_runtime_service",
    "is_admin",
    "query_service_state",
    "query_task_exists",
    "resolve_runtime_path",
    "start_service",
    "start_worker_task",
    "stop_and_delete_service",
    "stop_service",
    "uninstall_runtime_service",
    "wait_for_condition",
]
