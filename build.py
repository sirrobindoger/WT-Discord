import PyInstaller.__main__


def build_executable():
    PyInstaller.__main__.run(["WarThunderRPC_Setup.spec", "--clean", "--noconfirm"])


if __name__ == "__main__":
    build_executable()
