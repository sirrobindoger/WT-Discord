# installer.py
import os
import sys
import winreg
import tkinter as tk
from tkinter import simpledialog, messagebox
import shutil
import subprocess
import win32serviceutil
import win32service
import win32event
import servicemanager
import socket
import ctypes
import time

VERSION = "1.0.0"

VERSION = "1.0.0"


def get_service_status():
    """Get detailed service status"""
    try:
        status = win32serviceutil.QueryServiceStatus('WarThunderRPC')[1]
        status_map = {
            win32service.SERVICE_STOPPED: ("Stopped", "red"),
            win32service.SERVICE_START_PENDING: ("Starting...", "orange"),
            win32service.SERVICE_STOP_PENDING: ("Stopping...", "orange"),
            win32service.SERVICE_RUNNING: ("Running", "green"),
            win32service.SERVICE_PAUSED: ("Paused", "orange"),
            win32service.SERVICE_PAUSE_PENDING: ("Pausing...", "orange"),
            win32service.SERVICE_CONTINUE_PENDING: ("Resuming...", "orange"),
        }
        return status_map.get(status, ("Unknown", "gray"))
    except:
        return ("Not Installed", "red")

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def run_as_admin():
    """Re-run the script with admin rights"""
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)

class UsernameDialog:
    def __init__(self, parent):
        self.username = None
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("War Thunder Username Setup")
        self.dialog.geometry("300x150")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        tk.Label(self.dialog, text="Enter your War Thunder username:").pack(pady=10)
        
        self.entry = tk.Entry(self.dialog, width=30)
        self.entry.pack(pady=10)
        
        tk.Button(self.dialog, text="Save", command=self.save).pack(pady=10)
        
        # Center the dialog
        self.dialog.update_idletasks()
        width = self.dialog.winfo_width()
        height = self.dialog.winfo_height()
        x = (self.dialog.winfo_screenwidth() // 2) - (width // 2)
        y = (self.dialog.winfo_screenheight() // 2) - (height // 2)
        self.dialog.geometry('{}x{}+{}+{}'.format(width, height, x, y))

    def save(self):
        username = self.entry.get().strip()
        if username:
            try:
                registry_key = winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, r"Software\WarThunderRPC")
                winreg.SetValueEx(registry_key, "Username", 0, winreg.REG_SZ, username)
                winreg.CloseKey(registry_key)
                self.username = username
                self.dialog.destroy()
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save username: {e}")
        else:
            messagebox.showerror("Error", "Username cannot be empty")

def get_username():
    """Get username from registry"""
    try:
        registry_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"Software\WarThunderRPC", 0, winreg.KEY_READ)
        username, _ = winreg.QueryValueEx(registry_key, "Username")
        winreg.CloseKey(registry_key)
        return username
    except:
        return None

def change_username(root):
    dialog = UsernameDialog(root)
    root.wait_window(dialog.dialog)
    return dialog.username

class InstallerGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("War Thunder RPC Installer")
        self.root.geometry("400x350")
        
        # Add configurations to prevent hanging
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.after(100, self.check_pending_operations)
        
        
        # Center the window
        self.center_window()
        
        # Version info
        version_label = tk.Label(self.root, text=f"Version: {VERSION}", font=('Arial', 10))
        version_label.pack(pady=5)
        
        # Service status frame
        self.status_frame = tk.Frame(self.root, relief=tk.GROOVE, borderwidth=2)
        self.status_frame.pack(pady=10, padx=20, fill='x')
        
        tk.Label(self.status_frame, text="Service Status:", font=('Arial', 10, 'bold')).pack(pady=5)
        self.status_label = tk.Label(self.status_frame, text="Checking...", font=('Arial', 10))
        self.status_label.pack(pady=5)
        
        # Username frame
        self.username_frame = tk.LabelFrame(self.root, text="User Configuration", relief=tk.GROOVE, borderwidth=2)
        self.username_frame.pack(pady=10, padx=20, fill='x')
        
        self.username_label = tk.Label(self.username_frame, text="Username: Not Set", font=('Arial', 10))
        self.username_label.pack(side='left', padx=10, pady=10)
        
        tk.Button(self.username_frame, text="Change Username", 
                 command=self.change_username).pack(side='right', padx=10, pady=10)
        
        # Action buttons frame
        self.button_frame = tk.LabelFrame(self.root, text="Service Control", relief=tk.GROOVE, borderwidth=2)
        self.button_frame.pack(pady=10, padx=20, fill='x')
        
        tk.Button(self.button_frame, text="Install/Update Service", 
                 command=self.install_service).pack(pady=5, padx=20, fill='x')
        tk.Button(self.button_frame, text="Uninstall Service", 
                 command=self.uninstall_service).pack(pady=5, padx=20, fill='x')
        
        # Exit button at bottom
        tk.Button(self.root, text="Exit", 
                 command=self.root.quit).pack(pady=10)
        
        # Initialize displays
        self.update_username_display()
        self.start_status_checker()

    def start_status_checker(self):
        """Start periodic status checks"""
        def check_status():
            status_text, status_color = get_service_status()
            self.status_label.config(text=status_text, fg=status_color)
            self.root.after(2000, check_status)  # Check every 2 seconds
        
        check_status()

    def check_pending_operations(self):
        """Check if any operations are pending and update GUI accordingly"""
        try:
            status_text, status_color = get_service_status()
            self.status_label.config(text=status_text, fg=status_color)
            
            # If service is in a pending state, check again soon
            if "pending" in status_text.lower():
                self.root.after(1000, self.check_pending_operations)
            else:
                self.root.after(5000, self.check_pending_operations)
        except Exception as e:
            print(f"Status check error: {e}")
            self.root.after(5000, self.check_pending_operations)

    def on_closing(self):
        """Handle window closing properly"""
        try:
            # Check if any service operations are pending
            status = get_service_status()[0]
            if "pending" in status.lower():
                if messagebox.askokcancel("Warning", 
                    "Service operations are still pending. Are you sure you want to exit?"):
                    self.root.destroy()
            else:
                self.root.destroy()
        except:
            self.root.destroy()

    def center_window(self):
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry('{}x{}+{}+{}'.format(width, height, x, y))

    def update_username_display(self):
        username = get_username()
        if username:
            self.username_label.config(text=f"Username: {username}")
        else:
            self.username_label.config(text="Username: Not Set")

    def change_username(self):
        if change_username(self.root):
            self.update_username_display()

    def install_service(self):
        if not get_username():
            messagebox.showerror("Error", "Please set your username first!")
            return
        
        if not is_admin():
            run_as_admin()
            self.root.quit()
            return
            
        try:
            install_dir = os.path.join(os.getenv('PROGRAMFILES'), 'WarThunderRPC')
            os.makedirs(install_dir, exist_ok=True)
            
            # Copy the current executable
            current_exe = sys.executable if getattr(sys, 'frozen', False) else sys.argv[0]
            exe_name = "WarThunderRPC.exe"
            installed_exe = os.path.join(install_dir, exe_name)
            
            shutil.copy2(current_exe, installed_exe)
            
            # Stop and remove existing service if it exists
            try:
                if win32serviceutil.QueryServiceStatus('WarThunderRPC')[1] == win32service.SERVICE_RUNNING:
                    subprocess.run(['sc', 'stop', 'WarThunderRPC'], 
                                check=True, capture_output=True, text=True)
                    time.sleep(2)
                subprocess.run(['sc', 'delete', 'WarThunderRPC'], 
                            check=True, capture_output=True, text=True)
                time.sleep(2)
            except:
                pass  # Service doesn't exist, continue
            
            # Create service using the installed exe
            service_cmd = f'"{installed_exe}" --service'
            
            # Install service
            subprocess.run([
                'sc', 'create', 'WarThunderRPC',
                'type=', 'own',
                'start=', 'auto',
                'binPath=', service_cmd,
                'DisplayName=', 'War Thunder Discord Rich Presence',
                'error=', 'normal'
            ], check=True, capture_output=True, text=True)
            
            # Set service description
            subprocess.run([
                'sc', 'description', 'WarThunderRPC',
                'Discord Rich Presence integration for War Thunder'
            ], check=True, capture_output=True, text=True)
            
            # Configure service recovery options
            subprocess.run([
                'sc', 'failure', 'WarThunderRPC',
                'reset=', '86400',
                'actions=', 'restart/60000/restart/60000/restart/60000'
            ], check=True, capture_output=True, text=True)
            
            # Start the service
            subprocess.run(['sc', 'start', 'WarThunderRPC'], 
                        check=True, capture_output=True, text=True)
            messagebox.showinfo("Success", "Service installed and started successfully!")
                
        except Exception as e:
            messagebox.showerror("Installation Error", f"Failed to install service:\n{str(e)}")
            
        # Update status display
        self.update_status()

    def update_status(self):
        """Force a status update"""
        status_text, status_color = get_service_status()
        self.status_label.config(text=status_text, fg=status_color)

# [Rest of the code remains the same]
    def uninstall_service(self):
        if not is_admin():
            run_as_admin()
            self.root.quit()
            return
            
        try:
            status_text = get_service_status()[0]
            if status_text != "Not Installed":
                if status_text == "Running":
                    self.status_label.config(text="Stopping service...", fg="orange")
                    self.root.update()
                    subprocess.run(['sc', 'stop', 'WarThunderRPC'], check=True)
                    time.sleep(2)
                
                self.status_label.config(text="Removing service...", fg="orange")
                self.root.update()
                subprocess.run(['sc', 'delete', 'WarThunderRPC'], check=True)
            
            install_dir = os.path.join(os.getenv('PROGRAMFILES'), 'WarThunderRPC')
            if os.path.exists(install_dir):
                shutil.rmtree(install_dir)
                
            messagebox.showinfo("Success", "Service uninstalled successfully!")
            
        except Exception as e:
            messagebox.showerror("Uninstallation Error", f"Failed to uninstall service: {str(e)}")
        
        # Update status after uninstallation attempt
        status_text, status_color = get_service_status()
        self.status_label.config(text=status_text, fg=status_color)

