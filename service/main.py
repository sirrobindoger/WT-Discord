# WarThunderRPC.py
import sys
import ctypes
from installer import InstallerGUI, run_as_admin, is_admin
import win32serviceutil
import servicemanager
from warthunder_rpc_service import WarThunderRPCService

def main():
    if len(sys.argv) > 1:
        if sys.argv[1] == '--service':
            # Initialize and start as a Windows service
            servicemanager.Initialize()
            servicemanager.PrepareToHostSingle(WarThunderRPCService)
            servicemanager.StartServiceCtrlDispatcher()
        elif sys.argv[1] == '--run':
            # Run directly without service wrapper
            wt_rpc = WarThunderRPCService(None)
            wt_rpc.run_service()
        elif sys.argv[1] == '--install' and is_admin():
            app = InstallerGUI()
            app.root.mainloop()
    else:
        # No arguments - show installer GUI
        if not is_admin():
            run_as_admin()
        else:
            app = InstallerGUI()
            app.root.mainloop()

if __name__ == '__main__':
    main()