#!/usr/bin/env python3
"""
BeepConf Qt Chat — single clean implementation

UI and behaviors implemented per user's schema. Uses OpenAI client v1 chat.completions.create.
"""
import json
import os
import sys
import threading
import traceback
from pathlib import Path
from typing import List, Optional

import pyperclip
from openai import OpenAI
from PyQt5 import QtCore, QtGui, QtWidgets

try:
    import tiktoken
except Exception:
    tiktoken = None


APP_NAME = "BeepConf Qt Chat"
CONFIG_DIR = Path.home() / ".beepconf_qt_chat"
CONFIG_FILE = CONFIG_DIR / "config.json"

#!/usr/bin/env python3
import json
import os
import sys
import traceback
from pathlib import Path
from typing import List, Optional

import pyperclip
from openai import OpenAI
from PyQt5 import QtCore, QtWidgets

try:
    import tiktoken
except Exception:
    tiktoken = None


APP_NAME = "BeepConf Qt Chat"
CONFIG_DIR = Path.home() / ".beepconf_qt_chat"
CONFIG_FILE = CONFIG_DIR / "config.json"
HISTORY_FILE = CONFIG_DIR / "history.json"

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful assistant. Provide concise answers suitable for copy-pasting back to the clipboard."
)


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


class ApiWorker(QtCore.QThread):
    finished = QtCore.pyqtSignal(object, object)

    def __init__(self, api_key: Optional[str], base_url: Optional[str], messages: List[dict], model: str, temperature: float, n: int, timeout: int = 60):
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

            resp = client.chat.completions.create(
                model=self.model,
                messages=self.messages,
                temperature=self.temperature,
                n=self.n,
                max_tokens=1024,
                request_timeout=self.timeout,
            )
            self.finished.emit(resp, None)
        except Exception as e:
            tb = traceback.format_exc()
            self.finished.emit(None, (e, tb))


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1000, 700)

        self.worker: Optional[ApiWorker] = None
        self.current_attachments: List[dict] = []
        self.token_price_per_1k = 0.002

        self._build_ui()
        cfg = load_json(CONFIG_FILE, {})
        self.token_price_per_1k = float(cfg.get("token_price_per_1k", 0.002))
        self._load_config()
        self._load_history()

    def _build_ui(self):
        central = QtWidgets.QWidget()
        root = QtWidgets.QVBoxLayout(central)

        top = QtWidgets.QHBoxLayout()
        self.prompts_combo = QtWidgets.QComboBox()
        self.model_combo = QtWidgets.QComboBox()
        for m in ["gpt-4o-mini", "gpt-4o", "gpt-4", "gpt-3.5-turbo"]:
            self.model_combo.addItem(m)
        self.token_label = QtWidgets.QLabel("Est. tokens: 0")
        top.addWidget(self.prompts_combo)
        top.addWidget(self.model_combo)
        top.addStretch(1)
        top.addWidget(self.token_label)
        root.addLayout(top)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)

        left = QtWidgets.QWidget()
        lv = QtWidgets.QVBoxLayout(left)
        self.history_list = QtWidgets.QListWidget()
        self.history_list.itemClicked.connect(self.on_history_selected)
        lv.addWidget(self.history_list)
        splitter.addWidget(left)

        center = QtWidgets.QWidget()
        cv = QtWidgets.QVBoxLayout(center)
        self.chat_history = QtWidgets.QListWidget()
        cv.addWidget(self.chat_history)
        self.candidates = QtWidgets.QListWidget()
        self.candidates.itemClicked.connect(self._on_candidate)
        cv.addWidget(QtWidgets.QLabel("Candidates:"))
        cv.addWidget(self.candidates)
        self.preview = QtWidgets.QPlainTextEdit()
        self.preview.setMaximumHeight(180)
        cv.addWidget(QtWidgets.QLabel("Selected response preview:"))
        cv.addWidget(self.preview)
        splitter.addWidget(center)

        root.addWidget(splitter, 1)

        ib = QtWidgets.QHBoxLayout()
        self.attach_btn = QtWidgets.QPushButton("Attach")
        self.attach_btn.clicked.connect(self._attach)
        self.input_edit = QtWidgets.QTextEdit()
        self.send_btn = QtWidgets.QPushButton("Send")
        self.send_btn.clicked.connect(self._send)
        ib.addWidget(self.attach_btn)
        ib.addWidget(self.input_edit, 1)
        ib.addWidget(self.send_btn)
        root.addLayout(ib)

        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(120)
        root.addWidget(self.log)

        self.setCentralWidget(central)

    def _load_config(self):
        cfg = load_json(CONFIG_FILE, {})
        for p in cfg.get("prompts", []):
            self.prompts_combo.addItem(p.get("name", ""), p.get("text", ""))

    def _load_history(self):
        hist = load_json(HISTORY_FILE, [])
        for e in reversed(hist):
            it = QtWidgets.QListWidgetItem((e.get("prompt") or "")[:80])
            it.setData(QtCore.Qt.UserRole, e)
            self.history_list.addItem(it)

    def _attach(self):
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Attach files")
        for p in files:
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    txt = f.read()
                self.current_attachments.append({"path": p, "text": txt})
                self._log(f"Attached {p}")
            except Exception as e:
                self._log(f"Attach failed: {e}")

    def _send(self):
        prompt = self.input_edit.toPlainText().strip() or pyperclip.paste()
        if not prompt:
            self._log("No prompt")
            return
        for a in self.current_attachments:
            prompt += f"\n\n[Attachment: {a['path']}]\n" + a.get("text", "")[:2000]

        messages = [{"role": "system", "content": DEFAULT_SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
        api_key = os.environ.get("OPENAI_API_KEY")
        base = os.environ.get("OPENAI_API_BASE") or os.environ.get("OPENAI_BASE_URL")
        model = self.model_combo.currentText()
        temperature = 0.2
        n = 1

        self.send_btn.setEnabled(False)
        self._log("Sending...")
        self.worker = ApiWorker(api_key, base, messages, model, temperature, n)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _on_finished(self, resp, err):
        self.send_btn.setEnabled(True)
        if err:
            e, tb = err
            self._log(f"API error: {e}\n{tb}")
            return

        try:
            choices = getattr(resp, "choices", None) or (resp.get("choices") if isinstance(resp, dict) else [])
            self.candidates.clear()
            candidates_texts = []
            for c in choices:
                if isinstance(c, dict):
                    m = c.get("message") or {}
                    txt = m.get("content") or c.get("text") or ""
                else:
                    msg = getattr(c, "message", None)
                    txt = getattr(msg, "content", "") if msg else getattr(c, "text", "") or ""
                txt = (txt or "").strip()
                candidates_texts.append(txt)
                item = QtWidgets.QListWidgetItem(txt[:200].replace("\n", " "))
                item.setData(QtCore.Qt.UserRole, txt)
                self.candidates.addItem(item)

            if candidates_texts:
                self.preview.setPlainText(candidates_texts[0])
            self._append_history(self.input_edit.toPlainText(), candidates_texts)
            self._log(f"Received {len(candidates_texts)} candidate(s)")
        except Exception as e:
            self._log(f"Failed to parse API response: {e}")

    def _on_candidate(self, item: QtWidgets.QListWidgetItem):
        txt = item.data(QtCore.Qt.UserRole) or item.text()
        self.preview.setPlainText(txt)

    def _append_history(self, prompt: str, responses: List[str]):
        entry = {"prompt": prompt, "responses": responses}
        hist = load_json(HISTORY_FILE, [])
        hist.append(entry)
        save_json(HISTORY_FILE, hist)
        it = QtWidgets.QListWidgetItem(prompt[:80])
        it.setData(QtCore.Qt.UserRole, entry)
        self.history_list.insertItem(0, it)

    def on_history_selected(self, item: QtWidgets.QListWidgetItem):
        data = item.data(QtCore.Qt.UserRole) or {}
        prompt = data.get("prompt", "")
        responses = data.get("responses", [])
        self.input_edit.setPlainText(prompt)
        self.candidates.clear()
        for r in responses:
            it = QtWidgets.QListWidgetItem(r[:200].replace("\n", " "))
            it.setData(QtCore.Qt.UserRole, r)
            self.candidates.addItem(it)
        if responses:
            self.preview.setPlainText(responses[0])

    def _update_token_estimate(self):
        txt = self.input_edit.toPlainText()
        words = len(txt.split())
        est = int(max(1, words / 0.75))
        self.token_label.setText(f"Est. tokens: {est} (words: {words})")

    def _log(self, msg: str):
        self.log.appendPlainText(msg)


def main():
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
                # Left nav
