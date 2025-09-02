#!/usr/bin/env python3
"""Simple GUI helper to install dependencies and configure the ClipboardGPT tool.

Features:
- Install required packages for the current OS
- Set persistent environment variables (OPENAI_API_KEY, OPENAI_MODEL, GHUB_CHATGPT_NO_TOAST)
- Simple Tkinter GUI to edit/save settings
"""
import sys
import os
import subprocess
import platform
import tkinter as tk
from tkinter import messagebox

REPO_DIR = os.path.dirname(os.path.abspath(__file__))

def run_cmd(cmd):
    try:
        subprocess.check_call(cmd, shell=False)
        return True
    except subprocess.CalledProcessError as e:
        print("Command failed:", e)
        return False

def install_packages():
    system = platform.system()
    base = ["openai", "pyperclip"]
    extras = []
    if system == "Windows":
        extras.append("win10toast")
    elif system == "Linux":
        extras.append("notify2")
    elif system == "Darwin":
        # macOS: no toast dependency by default, keep base only
        extras.extend([])

    pkgs = base + extras
    python = sys.executable
    for pkg in pkgs:
        messagebox.showinfo("Install", f"Installing {pkg}...")
        ok = run_cmd([python, "-m", "pip", "install", pkg])
        if not ok:
            messagebox.showerror("Error", f"Failed to install {pkg}. See console.")
            return
    messagebox.showinfo("Done", "All packages installed.")

def persist_env_var(key, value):
    system = platform.system()
    try:
        if system == "Windows":
            # setx persists for future sessions
            subprocess.check_call(["setx", key, value], shell=True)
        else:
            shell = os.environ.get("SHELL", "")
            rc = os.path.expanduser("~/.bashrc")
            if shell.endswith("zsh"):
                rc = os.path.expanduser("~/.zshrc")
            with open(rc, "a", encoding="utf-8") as f:
                f.write(f"\nexport {key}='{value}'\n")
    except Exception as e:
        print("Failed to persist env var:", e)

def save_config(api_key, model, no_toast):
    if not api_key:
        messagebox.showerror("Error", "OPENAI API key is required")
        return
    os.environ["OPENAI_API_KEY"] = api_key
    os.environ["OPENAI_MODEL"] = model or "gpt-4o-mini"
    os.environ["GHUB_CHATGPT_NO_TOAST"] = "1" if no_toast else "0"
    # Persist to user environment
    persist_env_var("OPENAI_API_KEY", api_key)
    persist_env_var("OPENAI_MODEL", model or "gpt-4o-mini")
    persist_env_var("GHUB_CHATGPT_NO_TOAST", "1" if no_toast else "0")
    messagebox.showinfo("Saved", "Configuration saved to environment (may require new shell session).")

def open_repo_folder():
    if sys.platform == "win32":
        subprocess.Popen(["explorer", REPO_DIR])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", REPO_DIR])
    else:
        subprocess.Popen(["xdg-open", REPO_DIR])

def build_gui():
    root = tk.Tk()
    root.title("ClipboardGPT Setup")

    tk.Label(root, text="OpenAI API Key:").grid(row=0, column=0, sticky="e")
    api_entry = tk.Entry(root, width=50)
    api_entry.grid(row=0, column=1)

    tk.Label(root, text="Model (e.g. gpt-4o-mini):").grid(row=1, column=0, sticky="e")
    model_entry = tk.Entry(root, width=50)
    model_entry.grid(row=1, column=1)

    no_toast_var = tk.BooleanVar(value=False)
    tk.Checkbutton(root, text="Disable toast notifications", variable=no_toast_var).grid(row=2, column=1, sticky="w")

    tk.Button(root, text="Install dependencies", command=install_packages).grid(row=3, column=0, pady=8)
    tk.Button(root, text="Save configuration", command=lambda: save_config(api_entry.get().strip(), model_entry.get().strip(), no_toast_var.get())).grid(row=3, column=1)
    tk.Button(root, text="Open folder", command=open_repo_folder).grid(row=4, column=0, pady=6)
    tk.Button(root, text="Quit", command=root.destroy).grid(row=4, column=1)

    root.mainloop()

if __name__ == "__main__":
    build_gui()
