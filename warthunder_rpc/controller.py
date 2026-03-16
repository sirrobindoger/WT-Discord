from __future__ import annotations

import ctypes
import os
import queue
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox

import pystray
import win32api
import win32con
import win32event
import win32gui
from PIL import Image, ImageDraw

from .constants import CONTROLLER_MUTEX_NAME, CONTROLLER_WINDOW_TITLE
from .service_manager import (
    ServiceManagerError,
    controller_autostart_enabled,
    get_service_status,
)
from .user_config import read_username, write_username


ERROR_ALREADY_EXISTS = 183
TRAY_TOOLTIP = "War Thunder RPC"


def _create_mutex():
    mutex = win32event.CreateMutex(None, False, CONTROLLER_MUTEX_NAME)
    already_running = win32api.GetLastError() == ERROR_ALREADY_EXISTS
    return mutex, already_running


def _focus_existing_window():
    window_handle = win32gui.FindWindow(None, CONTROLLER_WINDOW_TITLE)
    if not window_handle:
        return False

    win32gui.ShowWindow(window_handle, win32con.SW_RESTORE)
    win32gui.ShowWindow(window_handle, win32con.SW_SHOW)
    try:
        win32gui.SetForegroundWindow(window_handle)
    except Exception:
        pass
    return True


def ensure_single_instance():
    mutex, already_running = _create_mutex()
    if already_running:
        _focus_existing_window()
        return None
    return mutex


def _build_tray_image(color):
    image = Image.new("RGBA", (64, 64), (18, 20, 26, 255))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8, 8, 56, 56), radius=14, fill=(32, 36, 44, 255))
    draw.ellipse((22, 22, 42, 42), fill=color)
    return image


class ControllerApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(CONTROLLER_WINDOW_TITLE)
        self.root.geometry("460x330")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)

        self.status_value = tk.StringVar(value="Checking service...")
        self.task_value = tk.StringVar(value="Checking worker task...")
        self.username_value = tk.StringVar(value=read_username() or "")
        self.message_value = tk.StringVar(value="The username is used for kill tracking.")
        self.autostart_value = tk.StringVar(value="Controller autostart: checking...")

        self._icon = None
        self._queue = queue.Queue()

        self._build_layout()
        self._start_tray()
        self.refresh_status()
        self.root.after(2000, self._poll_status)
        self.root.after(250, self._drain_queue)

    def _build_layout(self):
        wrapper = tk.Frame(self.root, padx=18, pady=16)
        wrapper.pack(fill="both", expand=True)

        intro = tk.Label(
            wrapper,
            text="War Thunder RPC runs in the background. Use this control center to manage the service and the tracked War Thunder username.",
            justify="left",
            wraplength=410,
        )
        intro.pack(anchor="w", pady=(0, 12))

        status_frame = tk.LabelFrame(wrapper, text="Background Status", padx=12, pady=12)
        status_frame.pack(fill="x")

        tk.Label(status_frame, text="Service:").grid(row=0, column=0, sticky="w")
        tk.Label(status_frame, textvariable=self.status_value, anchor="w").grid(row=0, column=1, sticky="w")
        tk.Label(status_frame, text="Worker task:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        tk.Label(status_frame, textvariable=self.task_value, anchor="w").grid(row=1, column=1, sticky="w", pady=(6, 0))
        tk.Label(status_frame, textvariable=self.autostart_value, anchor="w").grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )

        user_frame = tk.LabelFrame(wrapper, text="Kill Tracking", padx=12, pady=12)
        user_frame.pack(fill="x", pady=(12, 0))

        tk.Label(user_frame, text="War Thunder username:").grid(row=0, column=0, sticky="w")
        entry = tk.Entry(user_frame, textvariable=self.username_value, width=34)
        entry.grid(row=1, column=0, sticky="we", pady=(6, 0))
        tk.Button(user_frame, text="Save Username", command=self.save_username).grid(row=1, column=1, padx=(10, 0))
        tk.Label(
            user_frame,
            text="This value is used to match kill feed messages to your account.",
            justify="left",
            wraplength=395,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))

        controls = tk.LabelFrame(wrapper, text="Service Controls", padx=12, pady=12)
        controls.pack(fill="x", pady=(12, 0))

        tk.Button(controls, text="Start Service", width=18, command=lambda: self.run_elevated("--service-action", "start")).grid(
            row=0, column=0, padx=(0, 8), pady=(0, 8), sticky="we"
        )
        tk.Button(controls, text="Stop Service", width=18, command=lambda: self.run_elevated("--service-action", "stop")).grid(
            row=0, column=1, pady=(0, 8), sticky="we"
        )
        tk.Button(controls, text="Enable Auto Start", width=18, command=lambda: self.run_elevated("--service-action", "enable")).grid(
            row=1, column=0, padx=(0, 8), sticky="we"
        )
        tk.Button(controls, text="Disable Service", width=18, command=lambda: self.run_elevated("--service-action", "disable")).grid(
            row=1, column=1, sticky="we"
        )

        footer = tk.Label(wrapper, textvariable=self.message_value, anchor="w", justify="left", wraplength=410)
        footer.pack(anchor="w", pady=(14, 0))

    def _start_tray(self):
        self._icon = pystray.Icon(TRAY_TOOLTIP, _build_tray_image((85, 170, 85, 255)), TRAY_TOOLTIP, self._tray_menu())
        self._icon.run_detached()

    def _tray_menu(self):
        return pystray.Menu(
            pystray.MenuItem("Open Control Center", lambda icon, item: self._queue.put(("show", None))),
            pystray.MenuItem("Start Service", lambda icon, item: self._queue.put(("action", "start"))),
            pystray.MenuItem("Stop Service", lambda icon, item: self._queue.put(("action", "stop"))),
            pystray.MenuItem("Enable Auto Start", lambda icon, item: self._queue.put(("action", "enable"))),
            pystray.MenuItem("Disable Service", lambda icon, item: self._queue.put(("action", "disable"))),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit Controller", lambda icon, item: self._queue.put(("exit", None))),
        )

    def _update_tray_icon(self, service_state):
        if not self._icon:
            return

        color = (85, 170, 85, 255)
        if service_state in {"STOPPED", "NOT_INSTALLED"}:
            color = (190, 72, 72, 255)
        elif service_state in {"STOP_PENDING", "START_PENDING"}:
            color = (212, 160, 48, 255)

        self._icon.icon = _build_tray_image(color)
        self._icon.title = f"{TRAY_TOOLTIP} - {service_state.replace('_', ' ').title()}"
        self._icon.update_menu()

    def _poll_status(self):
        self.refresh_status()
        self.root.after(2000, self._poll_status)

    def _drain_queue(self):
        while not self._queue.empty():
            event, payload = self._queue.get_nowait()
            if event == "show":
                self.show_window()
            elif event == "action":
                self.run_elevated("--service-action", payload)
            elif event == "exit":
                self.exit_controller()
        self.root.after(250, self._drain_queue)

    def refresh_status(self):
        try:
            status = get_service_status()
        except ServiceManagerError as exc:
            self.status_value.set("Unavailable")
            self.task_value.set("Unavailable")
            self.autostart_value.set("Controller autostart: unavailable")
            self.message_value.set(str(exc))
            self._update_tray_icon("NOT_INSTALLED")
            return

        service_state = status["service_state"]
        start_type = status["service_start_type"]
        task_exists = status["task_exists"]

        readable_start_type = start_type.replace("_", " ").title()
        self.status_value.set(f"{service_state.replace('_', ' ').title()} ({readable_start_type})")
        self.task_value.set("Present" if task_exists else "Missing")
        self.autostart_value.set(
            f"Controller autostart: {'Enabled' if controller_autostart_enabled() else 'Disabled'}"
        )
        self._update_tray_icon(service_state)

    def save_username(self):
        username = self.username_value.get().strip()
        if not username:
            messagebox.showerror("Username Required", "Enter your War Thunder username for kill tracking.")
            return

        try:
            saved = write_username(username)
        except Exception as exc:
            messagebox.showerror("Save Failed", f"Could not save the username: {exc}")
            return

        self.username_value.set(saved)
        self.message_value.set(f"Saved username for kill tracking: {saved}")

    def run_elevated(self, *arguments):
        params = subprocess.list2cmdline(list(arguments))
        result = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
        if result <= 32:
            self.message_value.set("Administrator approval is required to change the service.")
            return

        self.message_value.set("Requested service change. Refreshing status...")
        self.root.after(1500, self.refresh_status)

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide_window(self):
        self.root.withdraw()
        self.message_value.set("Control center is still running in the tray.")

    def exit_controller(self):
        if self._icon:
            self._icon.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    mutex = ensure_single_instance()
    if mutex is None:
        return

    app = ControllerApp()
    try:
        app.run()
    finally:
        del mutex
