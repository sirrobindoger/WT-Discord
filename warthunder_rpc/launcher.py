import sys

import servicemanager

from .installer import InstallerGUI, is_admin, run_as_admin
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

        if sys.argv[1] == "--install" and is_admin():
            app = InstallerGUI()
            app.root.mainloop()
            return

    if not is_admin():
        run_as_admin()
        return

    app = InstallerGUI()
    app.root.mainloop()
