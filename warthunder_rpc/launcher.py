from __future__ import annotations

import argparse
import json
import os
import sys

import servicemanager

from .service_manager import (
    ServiceManagerError,
    controller_autostart_enabled,
    disable_service,
    enable_service,
    get_current_user,
    get_service_status,
    install_runtime_service,
    resolve_runtime_path,
    set_controller_autostart,
    start_service,
    stop_service,
    terminate_runtime_processes,
    uninstall_runtime_service,
)
from .user_config import read_username, write_username
from .windows_service import WarThunderRPCService


def build_parser():
    parser = argparse.ArgumentParser(prog="WarThunderRPC")
    parser.add_argument("--controller", action="store_true", help="Run the tray and control center UI")
    parser.add_argument("--service", action="store_true", help="Run the Windows service host")
    parser.add_argument("--worker", action="store_true", help="Run the Discord RPC worker")
    parser.add_argument("--local", action="store_true", help="Run the developer local RPC loop")
    parser.add_argument("--install-service", action="store_true", help="Install or update the Windows service")
    parser.add_argument("--uninstall-service", action="store_true", help="Remove the Windows service and worker task")
    parser.add_argument("--set-username", metavar="USERNAME", help="Store the War Thunder username for kill tracking")
    parser.add_argument("--get-username", action="store_true", help="Print the stored War Thunder username")
    parser.add_argument("--status-json", action="store_true", help="Print machine-readable runtime/service status")
    parser.add_argument("--runtime-path", metavar="PATH", help="Override the runtime executable path for installer actions")
    parser.add_argument("--service-user", metavar="USERNAME", help="Override the Windows user used for the worker task")
    parser.add_argument(
        "--service-action",
        choices=("start", "stop", "enable", "disable"),
        help="Perform a privileged service action",
    )
    parser.add_argument("--enable-controller-autostart", action="store_true", help="Enable controller auto-start at login")
    parser.add_argument("--disable-controller-autostart", action="store_true", help="Disable controller auto-start at login")
    parser.add_argument("--cleanup-runtime-processes", action="store_true", help="Terminate stray runtime processes")
    return parser


def _run_service_host():
    servicemanager.Initialize()
    servicemanager.PrepareToHostSingle(WarThunderRPCService)
    servicemanager.StartServiceCtrlDispatcher()


def _resolve_self_runtime_path(provided_path):
    if provided_path:
        return resolve_runtime_path(provided_path)

    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable)

    return resolve_runtime_path(os.path.join(os.getcwd(), "dist", "WarThunderRPC.exe"))


def _emit_json(payload, *, exit_code=0):
    print(json.dumps(payload, sort_keys=True))
    raise SystemExit(exit_code)


def _build_status_payload():
    payload = get_service_status()
    payload["controller_autostart_enabled"] = controller_autostart_enabled()
    payload["username"] = read_username() or ""
    return payload


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.service:
            _run_service_host()
            return

        if args.worker:
            from .worker import main as worker_main

            worker_main()
            return

        if args.controller:
            from .controller import main as controller_main

            controller_main()
            return

        if args.install_service:
            username = read_username()
            if not username:
                _emit_json(
                    {
                        "success": False,
                        "error": "No War Thunder username is configured yet. Set it first so kill tracking can identify your account.",
                    },
                    exit_code=1,
                )

            runtime_path = _resolve_self_runtime_path(args.runtime_path)
            service_user = args.service_user or get_current_user()
            try:
                summary = install_runtime_service(runtime_path, service_user)
            except ServiceManagerError as exc:
                _emit_json(
                    {
                        "success": False,
                        "error": str(exc),
                        "status": _build_status_payload(),
                    },
                    exit_code=1,
                )

            _emit_json(
                {
                    "success": True,
                    "result": summary.to_dict(),
                    "status": _build_status_payload(),
                }
            )

        if args.uninstall_service:
            uninstall_runtime_service()
            print("Removed the War Thunder RPC service and worker task")
            return

        if args.service_action == "start":
            start_service()
            return

        if args.service_action == "stop":
            stop_service()
            return

        if args.service_action == "enable":
            enable_service()
            return

        if args.service_action == "disable":
            disable_service()
            return

        if args.set_username is not None:
            username = write_username(args.set_username)
            print(f"Saved War Thunder username for kill tracking: {username}")
            return

        if args.get_username:
            username = read_username() or ""
            print(username)
            return

        if args.status_json:
            try:
                payload = _build_status_payload()
            except Exception as exc:
                payload = {
                    "service_installed": False,
                    "service_state": "UNKNOWN",
                    "service_start_type": "UNKNOWN",
                    "service_running": False,
                    "task_exists": False,
                    "controller_autostart_enabled": False,
                    "username": "",
                    "status_error": str(exc),
                }
            _emit_json(payload)

        if args.enable_controller_autostart:
            runtime_path = _resolve_self_runtime_path(args.runtime_path)
            set_controller_autostart(True, command=f'"{runtime_path}" --controller')
            print("Enabled controller auto-start")
            return

        if args.disable_controller_autostart:
            set_controller_autostart(False)
            print("Disabled controller auto-start")
            return

        if args.cleanup_runtime_processes:
            pids = terminate_runtime_processes()
            print(" ".join(str(pid) for pid in pids))
            return

        if args.local:
            from .local import main as local_main

            local_main()
            return

        from .controller import main as controller_main

        controller_main()
        return
    except ServiceManagerError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc

    parser.print_help()


if __name__ == "__main__":
    main()
