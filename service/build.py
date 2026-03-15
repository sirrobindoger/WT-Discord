# build.py
import PyInstaller.__main__

def build_executables():
    PyInstaller.__main__.run([
        'main.py',
        '--paths=..',
        '--onefile',
        '--windowed',
        '--name=WarThunderRPC_Setup',
        '--icon=icon.ico',
        '--add-data=warthunder_rpc_service.py;.',
        '--add-data=installer.py;.',
        '--add-data=telemetry.py;.',
        '--add-data=mapinfo.py;.',
        '--add-data=maps.py;.',
        '--hidden-import=win32timezone',
        '--hidden-import=PIL',
        '--hidden-import=pypresence',
        '--hidden-import=requests',
        '--hidden-import=telemetry',
        '--hidden-import=telemetry.mapinfo',
        '--hidden-import=win32serviceutil',
        '--hidden-import=win32service',
        '--hidden-import=win32event',
        '--hidden-import=servicemanager',
        '--hidden-import=nest_asyncio',
        '--hidden-import=asyncio',
        '--hidden-import=threading',
        '--hidden-import=psutil',
        '--hidden-import=winreg',
        '--hidden-import=vehicle_images'
    ])

if __name__ == "__main__":
    build_executables()
