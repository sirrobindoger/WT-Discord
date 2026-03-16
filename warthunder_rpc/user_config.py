import winreg


REGISTRY_PATH = r"Software\WarThunderRPC"
USERNAME_VALUE = "Username"
REGISTRY_HIVES = (
    winreg.HKEY_LOCAL_MACHINE,
    winreg.HKEY_CURRENT_USER,
)


def normalize_username(username):
    if not username:
        return ""

    normalized = " ".join(str(username).strip().split())
    while normalized.startswith("[") and "]" in normalized:
        _, remainder = normalized.split("]", 1)
        normalized = remainder.lstrip()

    return normalized.casefold()


def read_username():
    for hive in REGISTRY_HIVES:
        try:
            registry_key = winreg.OpenKey(hive, REGISTRY_PATH, 0, winreg.KEY_READ)
            username, _ = winreg.QueryValueEx(registry_key, USERNAME_VALUE)
            winreg.CloseKey(registry_key)
            if username and str(username).strip():
                return str(username).strip()
        except FileNotFoundError:
            continue
        except OSError:
            continue
    return None


def write_username(username):
    username = (username or "").strip()
    if not username:
        raise ValueError("Username cannot be empty")

    last_error = None
    for hive in REGISTRY_HIVES:
        try:
            registry_key = winreg.CreateKey(hive, REGISTRY_PATH)
            winreg.SetValueEx(registry_key, USERNAME_VALUE, 0, winreg.REG_SZ, username)
            winreg.CloseKey(registry_key)
            return username
        except OSError as exc:
            last_error = exc

    if last_error is not None:
        raise last_error

    return username


def prompt_for_username(title="War Thunder Username", prompt="What is your War Thunder username?"):
    import tkinter as tk
    from tkinter import simpledialog

    root = tk.Tk()
    root.withdraw()
    try:
        username = simpledialog.askstring(title, prompt, parent=root)
    finally:
        root.destroy()
    return username.strip() if username and username.strip() else None


def get_or_prompt_username(prompt_if_missing=False):
    username = read_username()
    if username or not prompt_if_missing:
        return username

    username = prompt_for_username()
    if username:
        write_username(username)
    return username
