from __future__ import annotations

import argparse
import os
import sys

import servicemanager

from .local import main as local_main
from .service_manager import (
    ServiceManagerError,
    get_current_user,
    install_runtime_service,
    resolve_runtime_path,
    uninstall_runtime_service,
)
from .user_config import read_username, write_username
from .windows_service import WarThunderRPCService
from .worker import main as worker_main


def build_parser():
    parser = argparse.ArgumentParser(prog="WarThunderRPC")
    parser.add_argument("--service", action="store_true", help="Run the Windows service host")
    parser.add_argument("--worker", action="store_true", help="Run the Discord RPC worker")
    parser.add_argument("--local", action="store_true", help="Run in local interactive mode")
    parser.add_argument("--install-service", action="store_true", help="Install or update the Windows service")
    parser.add_argument("--uninstall-service", action="store_true", help="Remove the Windows service and worker task")
    parser.add_argument("--set-username", metavar="USERNAME", help="Store the War Thunder username for kill tracking")
    parser.add_argument("--get-username", action="store_true", help="Print the stored War Thunder username")
    parser.add_argument("--runtime-path", metavar="PATH", help="Override the runtime executable path for installer actions")
    parser.add_argument("--service-user", metavar="USERNAME", help="Override the Windows user used for the worker task")
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


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.service:
            _run_service_host()
            return

        if args.worker:
            worker_main()
            return

        if args.install_service:
            username = read_username()
            if not username:
                raise ServiceManagerError(
                    "No War Thunder username is configured yet. Set it first so kill tracking can identify your account."
                )
            runtime_path = _resolve_self_runtime_path(args.runtime_path)
            service_user = args.service_user or get_current_user()
            summary = install_runtime_service(runtime_path, service_user)
            print(f"Installed {summary.service_name} using {summary.runtime_path} for {summary.service_user}")
            return

        if args.uninstall_service:
            uninstall_runtime_service()
            print("Removed the War Thunder RPC service and worker task")
            return

        if args.set_username is not None:
            username = write_username(args.set_username)
            print(f"Saved War Thunder username for kill tracking: {username}")
            return

        if args.get_username:
            username = read_username() or ""
            print(username)
            return

        if args.local or len(sys.argv) == 1:
            local_main()
            return
    except ServiceManagerError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc

    parser.print_help()


if __name__ == "__main__":
    main()
