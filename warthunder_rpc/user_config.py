from __future__ import annotations

import json
import os
from pathlib import Path

import winreg


REGISTRY_PATH = r"Software\WarThunderRPC"
USERNAME_VALUE = "Username"
LEGACY_REGISTRY_HIVES = (
    winreg.HKEY_CURRENT_USER,
    winreg.HKEY_LOCAL_MACHINE,
)

CONFIG_DIR_NAME = "WarThunderRPC"
CONFIG_FILE_NAME = "config.json"


def normalize_username(username):
    if not username:
        return ""

    normalized = " ".join(str(username).strip().split())
    while normalized.startswith("[") and "]" in normalized:
        _, remainder = normalized.split("]", 1)
        normalized = remainder.lstrip()

    return normalized.casefold()


def get_config_dir():
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / CONFIG_DIR_NAME
    return Path.home() / ".config" / CONFIG_DIR_NAME


def get_config_path():
    return get_config_dir() / CONFIG_FILE_NAME


def _read_json_config(path=None):
    config_path = Path(path) if path else get_config_path()
    if not config_path.exists():
        return {}

    try:
        with config_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}

    return data if isinstance(data, dict) else {}


def _write_json_config(data, path=None):
    config_path = Path(path) if path else get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)


def read_legacy_username():
    for hive in LEGACY_REGISTRY_HIVES:
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


def migrate_legacy_username():
    username = read_legacy_username()
    if username and not read_username(migrate_legacy=False):
        write_username(username)
    return username


def read_username(*, migrate_legacy=True):
    data = _read_json_config()
    username = str(data.get("username", "")).strip()
    if username:
        return username

    if not migrate_legacy:
        return None

    return migrate_legacy_username()


def write_username(username):
    username = (username or "").strip()
    if not username:
        raise ValueError("Username cannot be empty")

    data = _read_json_config()
    data["username"] = username
    _write_json_config(data)
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


__all__ = [
    "get_config_dir",
    "get_config_path",
    "get_or_prompt_username",
    "migrate_legacy_username",
    "normalize_username",
    "prompt_for_username",
    "read_legacy_username",
    "read_username",
    "write_username",
]
