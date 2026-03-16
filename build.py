from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import PyInstaller.__main__


REPO_ROOT = Path(__file__).resolve().parent
RUNTIME_SPEC = REPO_ROOT / "WarThunderRPC.spec"
INNO_SCRIPT = REPO_ROOT / "installer.iss"


def find_iscc():
    direct = shutil.which("iscc") or shutil.which("ISCC.exe")
    if direct:
        return direct

    candidates = [
        Path("C:/Program Files (x86)/Inno Setup 6/ISCC.exe"),
        Path("C:/Program Files/Inno Setup 6/ISCC.exe"),
        Path.home() / "AppData/Local/Programs/Inno Setup 6/ISCC.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    return None


def build_runtime():
    PyInstaller.__main__.run([str(RUNTIME_SPEC), "--clean", "--noconfirm"])


def build_installer():
    iscc_path = find_iscc()
    if not iscc_path:
        print("Inno Setup compiler not found; runtime EXE was built but installer packaging was skipped.")
        return False

    subprocess.run([iscc_path, str(INNO_SCRIPT)], check=True)
    return True


def build_executable():
    build_runtime()
    build_installer()


if __name__ == "__main__":
    build_executable()
