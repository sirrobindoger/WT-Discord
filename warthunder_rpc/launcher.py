import sys

import servicemanager

from .installer import InstallerGUI, is_admin, run_as_admin
from .local import main as local_main
from .worker import main as worker_main
from .windows_service import WarThunderRPCService


def main():
    if len(sys.argv) > 1:
        if sys.argv[1] == "--service":
            servicemanager.Initialize()
            servicemanager.PrepareToHostSingle(WarThunderRPCService)
            servicemanager.StartServiceCtrlDispatcher()
            return

        if sys.argv[1] == "--run":
            WarThunderRPCService(None).run_service()
            return

        if sys.argv[1] == "--worker":
            worker_main()
            return

        if sys.argv[1] == "--local":
            local_main()
            return

        if sys.argv[1] == "--install" and is_admin():
            app = InstallerGUI()
            app.root.mainloop()
            return

    if not is_admin():
        run_as_admin()
        return

    app = InstallerGUI()
    app.root.mainloop()
