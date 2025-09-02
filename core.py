#!/usr/bin/env python3
"""Core API helpers for BeepConf Qt Chat.

Provides:
- ApiWorker: QThread that runs OpenAI chat.completions.create with a fallback
  for client versions that don't accept request_timeout.
- notify, copy_to_clipboard, token estimator, simple history persistence helpers.
"""
import json
import os
import traceback
from pathlib import Path
from typing import List, Optional

import pyperclip
from openai import OpenAI
from PyQt5 import QtCore

try:
    import tiktoken
except Exception:
    tiktoken = None


APP_NAME = "BeepConf Qt Chat"
CONFIG_DIR = Path.home() / ".beepconf_qt_chat"
CONFIG_FILE = CONFIG_DIR / "config.json"
HISTORY_FILE = CONFIG_DIR / "history.json"


def ensure_config_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default):
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        return default
    return default


def save_json(path: Path, data):
    ensure_config_dir()
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def notify(title: str, msg: str, duration: int = 5):
    try:
        if os.name == "nt":
            try:
                from win10toast import ToastNotifier

                ToastNotifier().show_toast(title, msg, duration=duration, threaded=True)
                return
            except Exception:
                pass

        try:
            import notify2

            notify2.init(APP_NAME)
            n = notify2.Notification(title, msg)
            n.set_timeout(duration * 1000)
            n.show()
            return
        except Exception:
            pass
    except Exception:
        pass

    try:
        print(f"[notify] {title}: {msg}")
    except Exception:
        pass


def copy_to_clipboard(text: str):
    try:
        pyperclip.copy(text)
        return True
    except Exception:
        return False


def estimate_tokens(text: str, model: str = "gpt-3.5-turbo") -> int:
    if not text:
        return 0
    if tiktoken:
        try:
            enc = None
            try:
                enc = tiktoken.encoding_for_model(model)
            except Exception:
                enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
        except Exception:
            pass
    # fallback heuristic
    words = len(text.split())
    return int(max(1, words / 0.75))


class ApiWorker(QtCore.QThread):
    finished = QtCore.pyqtSignal(object, object)  # (response, error)

    def __init__(self, api_key: Optional[str], base_url: Optional[str], messages: List[dict], model: str, temperature: float = 0.2, n: int = 1, timeout: int = 60):
        super().__init__()
        self.api_key = api_key
        self.base_url = base_url
        self.messages = messages
        self.model = model
        self.temperature = temperature
        self.n = n
        self.timeout = timeout

    def run(self):
        try:
            client_kwargs = {}
            if self.api_key:
                client_kwargs["api_key"] = self.api_key
            if self.base_url:
                client_kwargs["api_base"] = self.base_url
            client = OpenAI(**client_kwargs) if client_kwargs else OpenAI()

            try:
                resp = client.chat.completions.create(
                    model=self.model,
                    messages=self.messages,
                    temperature=self.temperature,
                    n=self.n,
                    max_tokens=1024,
                    request_timeout=self.timeout,
                )
            except TypeError as e:
                # older/newer clients may not accept request_timeout kwarg
                if "request_timeout" in str(e):
                    resp = client.chat.completions.create(
                        model=self.model,
                        messages=self.messages,
                        temperature=self.temperature,
                        n=self.n,
                        max_tokens=1024,
                    )
                else:
                    raise

            self.finished.emit(resp, None)
        except Exception as e:
            tb = traceback.format_exc()
            self.finished.emit(None, (e, tb))

