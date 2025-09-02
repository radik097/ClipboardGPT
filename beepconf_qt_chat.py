#!/usr/bin/env python3
"""
BeepConf Qt Chat - cleaned full implementation

Features implemented:
- TopBar: prompts, model/version, cost tokens, summary cost
- Left navigation with toggle and list of chats
- Center chat area with title, chat history, candidates and preview
- Bottom input bar with Attach, QTextEdit input, Send
- Attach handler (file open and simple text inclusion)
- Save/Delete prompts, token estimate (tiktoken fallback), cost accumulation
- Background API calls using OpenAI client (v1) - minimal safe parsing
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

    def __init__(self, api_key: str, base_url: Optional[str], messages: List[dict], model: str, temperature: float, n: int, timeout: int = 60):
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
        self.resize(1200, 700)

        self.worker: Optional[ApiWorker] = None
        self.current_attachments: List[dict] = []
        self.total_tokens = 0
        self.token_price_per_1k = 0.002

        self._build_ui()
        cfg = load_json(CONFIG_FILE, {})
        self.token_price_per_1k = float(cfg.get("token_price_per_1k", 0.002))
        self._load_config()
        self._load_history()

    def _build_ui(self):
        central = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(central)

        # TopBar
        topbar = QtWidgets.QHBoxLayout()
        self.promptsBox = QtWidgets.QComboBox()
        self.versionBox = QtWidgets.QComboBox()
        for m in ["gpt-4o-mini", "gpt-4o", "gpt-4", "gpt-3.5-turbo"]:
            self.versionBox.addItem(m)
        self.costLabel = QtWidgets.QLabel("Cost tokens: 0")
        self.summaryLabel = QtWidgets.QLabel("Total tokens: 0 | Cost: $0.00")

        topbar.addWidget(self.promptsBox)
        topbar.addWidget(self.versionBox)
        topbar.addStretch(1)
        topbar.addWidget(self.costLabel)
        topbar.addWidget(self.summaryLabel)
        v.addLayout(topbar)

        # Splitter: left nav and center
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)

        # Left nav
        nav = QtWidgets.QWidget()
        nv = QtWidgets.QVBoxLayout(nav)
        self.toggleBtn = QtWidgets.QToolButton()
        self.toggleBtn.setText("☰")
        self.toggleBtn.setCheckable(True)
        self.toggleBtn.setChecked(True)
        self.toggleBtn.clicked.connect(self._on_toggle_nav)
        nv.addWidget(self.toggleBtn)

        self.chatList = QtWidgets.QListWidget()
        nv.addWidget(self.chatList, 1)

        btn_row = QtWidgets.QHBoxLayout()
        self.settingsBtn = QtWidgets.QPushButton("Settings")
        self.customBtn = QtWidgets.QPushButton("Customize")
        btn_row.addWidget(self.settingsBtn)
        btn_row.addWidget(self.customBtn)
        nv.addLayout(btn_row)

        splitter.addWidget(nav)

        # Center chat area
        chatArea = QtWidgets.QWidget()
        cv = QtWidgets.QVBoxLayout(chatArea)
        self.titleLabel = QtWidgets.QLabel("Title of chat")
        self.titleLabel.setStyleSheet("font-weight: bold; font-size: 16px;")
        cv.addWidget(self.titleLabel)

        self.chatHistory = QtWidgets.QListWidget()
        cv.addWidget(self.chatHistory, 1)

        self.responses_list = QtWidgets.QListWidget()
        self.responses_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.responses_list.itemClicked.connect(self._on_response_clicked)
        cv.addWidget(QtWidgets.QLabel("Candidates:"))
        cv.addWidget(self.responses_list)

        self.response_preview = QtWidgets.QPlainTextEdit()
        self.response_preview.setMaximumHeight(180)
        cv.addWidget(QtWidgets.QLabel("Selected response preview:"))
        cv.addWidget(self.response_preview)

        splitter.addWidget(chatArea)
        v.addWidget(splitter, 1)

        # InputBar
        inputBar = QtWidgets.QHBoxLayout()
        self.attachBtn = QtWidgets.QPushButton("Attach")
        self.attachBtn.clicked.connect(self._on_attach)
        self.inputEdit = QtWidgets.QTextEdit()
        self.sendBtn = QtWidgets.QPushButton("Send")
        self.sendBtn.clicked.connect(self.on_send_clicked)
        inputBar.addWidget(self.attachBtn)
        inputBar.addWidget(self.inputEdit, 1)
        inputBar.addWidget(self.sendBtn)
        v.addLayout(inputBar)

        # bottom controls
        bottom_row = QtWidgets.QHBoxLayout()
        self.save_conf_btn = QtWidgets.QPushButton("Save Config")
        self.save_conf_btn.clicked.connect(self.save_config)
        self.load_conf_btn = QtWidgets.QPushButton("Reload Config")
        self.load_conf_btn.clicked.connect(self._load_config)
        bottom_row.addWidget(self.save_conf_btn)
        bottom_row.addWidget(self.load_conf_btn)

        self.token_label = QtWidgets.QLabel("Est. tokens: 0")
        bottom_row.addWidget(self.token_label)
        bottom_row.addStretch(1)

        self.log_view = QtWidgets.QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(120)

        outer = QtWidgets.QVBoxLayout()
        outer.addLayout(bottom_row)
        outer.addWidget(self.log_view)
        v.addLayout(outer)

        self.setCentralWidget(central)
        self.status = self.statusBar()

        # prompt save/delete buttons
        self.savePromptBtn = QtWidgets.QPushButton("Save Prompt")
        self.savePromptBtn.clicked.connect(self._save_current_prompt)
        self.deletePromptBtn = QtWidgets.QPushButton("Delete Prompt")
        self.deletePromptBtn.clicked.connect(self._delete_selected_prompt)
        topbar.insertWidget(1, self.savePromptBtn)
        topbar.insertWidget(2, self.deletePromptBtn)

        # small compatibility widgets
        self.api_key_edit = QtWidgets.QLineEdit()
        self.api_key_edit.setVisible(False)
        self.temp_spin = QtWidgets.QDoubleSpinBox()
        self.n_spin = QtWidgets.QSpinBox()
        self.offline_checkbox = QtWidgets.QCheckBox()

    # config / history
    def _load_config(self):
        data = load_json(CONFIG_FILE, {})
        if not data:
            return
        # load prompts
        self.promptsBox.clear()
        for p in data.get("prompts", []):
            self.promptsBox.addItem(p.get("name", "prompt"), p.get("text", ""))
        # load selected model
        model = data.get("model")
        if model:
            idx = self.versionBox.findText(model)
            if idx >= 0:
                self.versionBox.setCurrentIndex(idx)

    def save_config(self):
        data = load_json(CONFIG_FILE, {})
        data["prompts"] = []
        for i in range(self.promptsBox.count()):
            data["prompts"].append({"name": self.promptsBox.itemText(i), "text": self.promptsBox.itemData(i)})
        data["model"] = self.versionBox.currentText()
        data["token_price_per_1k"] = self.token_price_per_1k
        save_json(CONFIG_FILE, data)
        self.log("Config saved")

    def _load_history(self):
        hist = load_json(HISTORY_FILE, [])
        self.history = hist
        self.chatList.clear()
        for entry in hist[::-1]:
            title = entry.get("prompt", "").splitlines()[0][:60]
            it = QtWidgets.QListWidgetItem(title)
            it.setData(QtCore.Qt.UserRole, entry)
            self.chatList.addItem(it)

    def _append_history(self, prompt: str, responses: List[str]):
        entry = {"prompt": prompt, "responses": responses}
        hist = load_json(HISTORY_FILE, [])
        hist.append(entry)
        save_json(HISTORY_FILE, hist)
        self._load_history()

    # UI actions
    def _on_attach(self):
        dlg = QtWidgets.QFileDialog(self)
        dlg.setFileMode(QtWidgets.QFileDialog.ExistingFiles)
        if dlg.exec_():
            files = dlg.selectedFiles()
            for p in files:
                try:
                    with open(p, "r", encoding="utf-8", errors="ignore") as f:
                        txt = f.read()
                    self.current_attachments.append({"path": p, "text": txt})
                    self.log(f"Attached {p}")
                except Exception as e:
                    self.log(f"Attach failed {p}: {e}")

    def _on_toggle_nav(self):
        visible = self.toggleBtn.isChecked()
        # show/hide nav widget
        self.chatList.setVisible(visible)

    def _on_chat_selected(self, item: QtWidgets.QListWidgetItem):
        data = item.data(QtCore.Qt.UserRole) or {}
        self.titleLabel.setText((data.get("prompt", "").splitlines()[0]) or "Chat")
        self.chatHistory.clear()
        for r in data.get("responses", []):
            it = QtWidgets.QListWidgetItem(r[:200])
            it.setData(QtCore.Qt.UserRole, r)
            self.chatHistory.addItem(it)

    def _on_response_clicked(self, item: QtWidgets.QListWidgetItem):
        txt = item.data(QtCore.Qt.UserRole) or item.text()
        self.response_preview.setPlainText(txt)

    def on_send_clicked(self):
        prompt = self.inputEdit.toPlainText().strip()
        if not prompt:
            prompt = pyperclip.paste()
        if not prompt:
            self.log("No input to send")
            return

        # include attachments (naive: append text)
        for a in self.current_attachments:
            prompt += "\n\n[Attachment: %s]\n" % a.get("path")
            prompt += a.get("text", "")[:2000]

        self.sendBtn.setEnabled(False)
        self.status.showMessage("Sending...")

        messages = [{"role": "system", "content": DEFAULT_SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
        api_key = os.environ.get("OPENAI_API_KEY") or self.api_key_edit.text().strip()
        base_url = os.environ.get("OPENAI_API_BASE") or os.environ.get("OPENAI_BASE_URL")
        model = self.versionBox.currentText()
        temp = 0.2
        n = 1

        self.worker = ApiWorker(api_key, base_url, messages, model, temp, n)
        self.worker.finished.connect(self._on_api_finished)
        self.worker.start()

    def _on_api_finished(self, resp, err):
        self.sendBtn.setEnabled(True)
        if err:
            e, tb = err
            self.log(f"API error: {e}\n{tb}")
            self.status.showMessage("Error")
            return

        try:
            # parse choices robustly
            choices = getattr(resp, "choices", None) or resp.get("choices", [])
            candidates = []
            for c in choices:
                if isinstance(c, dict):
                    msg = c.get("message") or {}
                    txt = msg.get("content") or c.get("text") or ""
                else:
                    msg = getattr(c, "message", None)
                    if msg:
                        txt = getattr(msg, "content", "")
                    else:
                        txt = getattr(c, "text", "") or ""
                candidates.append(txt.strip())

            # update UI
            self.responses_list.clear()
            for t in candidates:
                it = QtWidgets.QListWidgetItem(t[:200].replace("\n", " "))
                it.setData(QtCore.Qt.UserRole, t)
                self.responses_list.addItem(it)

            if candidates:
                self.response_preview.setPlainText(candidates[0])

            # append to history
            self._append_history(self.inputEdit.toPlainText(), candidates)

            # token estimate (naive): count words
            words = len(self.inputEdit.toPlainText().split())
            tokens = int(max(1, words / 0.75))
            self.costLabel.setText(f"Cost tokens: {tokens}")
            self.total_tokens += tokens
            cost = (self.total_tokens / 1000.0) * self.token_price_per_1k
            self.summaryLabel.setText(f"Total tokens: {self.total_tokens} | Cost: ${cost:.4f}")

            self.log(f"Received {len(candidates)} candidate(s)")
            self.status.showMessage("Done")
        except Exception as e:
            self.log(f"Failed to parse response: {e}")

    def _save_current_prompt(self):
        text = self.inputEdit.toPlainText().strip()
        if not text:
            self.log("Nothing to save as prompt")
            return
        name, ok = QtWidgets.QInputDialog.getText(self, "Prompt name", "Name for prompt:")
        if not ok or not name:
            return
        self.promptsBox.addItem(name, text)
        self.log("Saved prompt '%s'" % name)

    def _delete_selected_prompt(self):
        idx = self.promptsBox.currentIndex()
        if idx >= 0:
            name = self.promptsBox.itemText(idx)
            self.promptsBox.removeItem(idx)
            self.log(f"Deleted prompt {name}")

    def _update_token_estimate(self):
        txt = self.inputEdit.toPlainText()
        if tiktoken:
            try:
                enc = tiktoken.encoding_for_model(self.versionBox.currentText())
                tok = len(enc.encode(txt))
            except Exception:
                tok = max(1, len(txt.split()) // 1)
        else:
            tok = max(1, len(txt.split()) // 1)
        self.token_label.setText(f"Est. tokens: {tok}")

    def log(self, *parts):
        s = " ".join(str(p) for p in parts)
        self.log_view.appendPlainText(s)


def main():
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""
Full-featured PyQt5 GUI for the BeepConf Chat/Clipboard utility.

Features:
- API key / model selection / temperature / n (candidates)
- Save/load config to user home (~/.beepconf_qt_chat/config.json)
- Read clipboard, send to OpenAI-compatible API in background thread
- Show multiple candidates, allow manual pick or 'Auto-pick by model' (second short call)
- History list with selectable previous queries and responses
- Simple token estimate, logs and status messages

This file is intended to be a drop-in GUI companion to ghub_chatgpt_clip.py.
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

# optional tiktoken for token counting
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
    finished = QtCore.pyqtSignal(object, object)  # (result, error)

    def __init__(self, api_key: str, base_url: Optional[str], messages: List[dict],
                 model: str, temperature: float, n: int, timeout: int = 60):
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
            # Use new OpenAI client (v1+)
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
        self.resize(900, 700)

        self.worker: Optional[ApiWorker] = None
    self.current_attachments: List[dict] = []
    self.total_tokens = 0

    self._build_ui()
    self._load_config()
    self._load_history()

    def _build_ui(self):
        # Build layout according to user's Qt5 Chat GUI schema
        central = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(central)

        # --- TopBar ---
        topbar = QtWidgets.QHBoxLayout()
        self.promptsBox = QtWidgets.QComboBox()
        self.promptsBox.setToolTip("Saved prompts")
        # load from config if any
        cfg = load_json(CONFIG_FILE, {})
        for p in cfg.get("prompts", []):
            self.promptsBox.addItem(p.get("name", "prompt"), p.get("text", ""))

        # model/version selector
        self.versionBox = QtWidgets.QComboBox()
        for m in ["gpt-4o-mini", "gpt-4o", "gpt-4", "gpt-3.5-turbo", "llama2"]:
            self.versionBox.addItem(m)
        # cost labels
        self.costLabel = QtWidgets.QLabel("Cost tokens: 0")
        self.summaryLabel = QtWidgets.QLabel("Total tokens: 0 | Cost: $0.00")

        topbar.addWidget(self.promptsBox)
        topbar.addWidget(self.versionBox)
        topbar.addStretch(1)
        topbar.addWidget(self.costLabel)
        topbar.addWidget(self.summaryLabel)
        v.addLayout(topbar)

        # --- Splitter: Left Navigation and Center ChatArea ---
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)

        # Left nav
        nav = QtWidgets.QWidget()
        nv = QtWidgets.QVBoxLayout(nav)
        self.toggleBtn = QtWidgets.QToolButton()
        self.toggleBtn.setText("☰")
        self.toggleBtn.setCheckable(True)
        self.toggleBtn.setChecked(True)
        self.toggleBtn.clicked.connect(self._on_toggle_nav)
        nv.addWidget(self.toggleBtn)

        self.chatList = QtWidgets.QListWidget()
        self.chatList.itemClicked.connect(self._on_chat_selected)
        nv.addWidget(self.chatList, 1)

        bottom_nav = QtWidgets.QHBoxLayout()
        self.settingsBtn = QtWidgets.QPushButton("Settings")
        self.customBtn = QtWidgets.QPushButton("Customize")
        bottom_nav.addWidget(self.settingsBtn)
        bottom_nav.addWidget(self.customBtn)
        nv.addLayout(bottom_nav)

        splitter.addWidget(nav)

        # Center chat area
        chatArea = QtWidgets.QWidget()
        cv = QtWidgets.QVBoxLayout(chatArea)
        self.titleLabel = QtWidgets.QLabel("Title of chat")
        self.titleLabel.setStyleSheet("font-weight: bold; font-size: 16px;")
        cv.addWidget(self.titleLabel)


    self.chatHistory = QtWidgets.QListWidget()
    cv.addWidget(self.chatHistory, 1)

    # Candidates / responses list (synchronized with chatHistory for assistant messages)
    self.responses_list = QtWidgets.QListWidget()
    self.responses_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
    self.responses_list.itemClicked.connect(self._on_response_clicked)
    cv.addWidget(QtWidgets.QLabel("Candidates:"))
    cv.addWidget(self.responses_list)

    # preview of selected response
    self.response_preview = QtWidgets.QPlainTextEdit()
    self.response_preview.setReadOnly(False)
    self.response_preview.setMaximumHeight(180)
    cv.addWidget(QtWidgets.QLabel("Selected response preview:"))
    cv.addWidget(self.response_preview)

        splitter.addWidget(chatArea)

        v.addWidget(splitter, 1)

    # --- InputBar (bottom) ---
    inputBar = QtWidgets.QHBoxLayout()
        self.attachBtn = QtWidgets.QPushButton("Attach")
        self.attachBtn.clicked.connect(self._on_attach)
        self.inputEdit = QtWidgets.QTextEdit()
        self.sendBtn = QtWidgets.QPushButton("Send")
        self.sendBtn.clicked.connect(self.on_send_clicked)
        inputBar.addWidget(self.attachBtn)
        inputBar.addWidget(self.inputEdit, 1)
        inputBar.addWidget(self.sendBtn)
        v.addLayout(inputBar)

        # Logs and control buttons row
        bottom = QtWidgets.QHBoxLayout()
        self.save_conf_btn = QtWidgets.QPushButton("Save Config")
        self.save_conf_btn.clicked.connect(self.save_config)
        self.load_conf_btn = QtWidgets.QPushButton("Reload Config")
        self.load_conf_btn.clicked.connect(self._load_config)
        bottom.addWidget(self.save_conf_btn)
        bottom.addWidget(self.load_conf_btn)

        # token estimate in bottom-left
    self.token_label = QtWidgets.QLabel("Est. tokens: 0")
        bottom.addWidget(self.token_label)
        bottom.addStretch(1)

        # logs
        self.log_view = QtWidgets.QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(120)

        outer_bottom = QtWidgets.QVBoxLayout()
        outer_bottom.addLayout(bottom)
        outer_bottom.addWidget(self.log_view)

        v.addLayout(outer_bottom)

        self.setCentralWidget(central)

        # status bar
        self.status = self.statusBar()

        # internal counters
    self.token_price_per_1k = float(cfg.get("token_price_per_1k", 0.002))

    # invisible config widgets to keep compatibility with older methods
    self.api_key_edit = QtWidgets.QLineEdit()
    self.api_key_edit.setVisible(False)
    self.temp_spin = QtWidgets.QDoubleSpinBox()
    self.temp_spin.setVisible(False)
    self.n_spin = QtWidgets.QSpinBox()
    self.n_spin.setVisible(False)
    self.offline_checkbox = QtWidgets.QCheckBox()
    self.offline_checkbox.setVisible(False)

    # alias old name to new model combobox
    self.model_combo = self.versionBox

    # prompt save/delete buttons
    self.savePromptBtn = QtWidgets.QPushButton("Save Prompt")
    self.savePromptBtn.setFixedWidth(100)
    self.savePromptBtn.clicked.connect(self._save_current_prompt)
    self.deletePromptBtn = QtWidgets.QPushButton("Delete Prompt")
    self.deletePromptBtn.setFixedWidth(100)
    self.deletePromptBtn.clicked.connect(self._delete_selected_prompt)
    # insert prompt buttons into topbar (left side)
    topbar.insertWidget(1, self.savePromptBtn)
    topbar.insertWidget(2, self.deletePromptBtn)

    # keep a reference to nav widget for toggling
    self.nav_widget = nav


    # ---------- config / history ----------
    def _load_config(self):
        data = load_json(CONFIG_FILE, {})
        if not data:
            return
        self.api_key_edit.setText(data.get("api_key", ""))
        model = data.get("model")
        if model:
            idx = self.model_combo.findText(model)
            if idx >= 0:
                self.model_combo.setCurrentIndex(idx)
            else:
                self.model_combo.addItem(model)
                self.model_combo.setCurrentText(model)
        self.temp_spin.setValue(float(data.get("temperature", 0.2)))
        self.n_spin.setValue(int(data.get("n", 1)))
        self.offline_checkbox.setChecked(bool(data.get("offline_select", True)))

    def save_config(self):
        data = {
            "api_key": self.api_key_edit.text().strip(),
            "model": self.model_combo.currentText().strip(),
            "temperature": float(self.temp_spin.value()),
            "n": int(self.n_spin.value()),
            "offline_select": bool(self.offline_checkbox.isChecked()),
        }
        save_json(CONFIG_FILE, data)
        self.log("Config saved to %s" % CONFIG_FILE)

    def _load_history(self):
        hist = load_json(HISTORY_FILE, [])
        self.history = hist
        self.history_list.clear()
        for item in hist[::-1]:
            display = item.get("prompt", "(no prompt)")[:60].replace("\n", " ")
            lw = QtWidgets.QListWidgetItem(display)
            lw.setData(QtCore.Qt.UserRole, item)
            self.history_list.addItem(lw)

    def _append_history(self, prompt: str, responses: List[str]):
        entry = {"prompt": prompt, "responses": responses}
        hist = load_json(HISTORY_FILE, [])
        hist.append(entry)
        save_json(HISTORY_FILE, hist)
        self._load_history()

    # ---------- UI actions ----------
    def load_clipboard_into_prompt(self):
        try:
            txt = pyperclip.paste()
            self.prompt_edit.setPlainText(txt)
            self.log("Loaded clipboard into prompt (len=%d)" % len(txt))
            self._update_token_estimate()
        except Exception as e:
            self.log("Failed to read clipboard: %s" % e)

    def on_send_clicked(self):
        prompt = self.prompt_edit.toPlainText().strip()
        if not prompt:
            # try clipboard
            prompt = pyperclip.paste()
        if not prompt:
            self.log("No prompt or clipboard text available")
            return
        self.send_btn.setEnabled(False)
        self.status.showMessage("Sending request...")
        self.responses_list.clear()

        system = DEFAULT_SYSTEM_PROMPT
        messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]

        api_key = self.api_key_edit.text().strip() or os.environ.get("OPENAI_API_KEY")
        base_url = os.environ.get("OPENAI_API_BASE") or os.environ.get("OPENAI_BASE_URL")
        model = self.model_combo.currentText().strip()
        temperature = float(self.temp_spin.value())
        n = int(self.n_spin.value())

        self.worker = ApiWorker(api_key, base_url, messages, model, temperature, n)
        self.worker.finished.connect(self._on_api_finished)
        self.worker.start()

    def _on_api_finished(self, resp, err):
        self.send_btn.setEnabled(True)
        if err:
            e, tb = err
            self.log(f"API error: {e}\n{tb}")
            self.status.showMessage("Error")
            return

        # resp is an OpenAI response object; convert safely
        try:
            choices = resp.get("choices", [])
            candidates = []
            for c in choices:
                # support chat completion delta/content structure
                text = None
                if isinstance(c.get("message"), dict):
                    text = c["message"].get("content")
                else:
                    # older style
                    text = c.get("text") or c.get("message")
                if not text:
                    text = ""
                candidates.append(text.strip())

            # list candidates
            self.responses_list.clear()
            for t in candidates:
                it = QtWidgets.QListWidgetItem(t[:200].replace("\n", " "))
                it.setData(QtCore.Qt.UserRole, t)
                self.responses_list.addItem(it)

            if candidates:
                self.response_preview.setPlainText(candidates[0])
            self._append_history(self.prompt_edit.toPlainText(), candidates)
            self.log(f"Received {len(candidates)} candidate(s)")
            self.status.showMessage("Done")
        except Exception as e:
            self.log("Failed to parse API response: %s" % e)

    def on_response_selection_changed(self, current, previous):
        if not current:
            return
        t = current.data(QtCore.Qt.UserRole)
        if t is None:
            t = current.text()
        self.response_preview.setPlainText(t)

    def copy_selected_to_clipboard(self):
        txt = self.response_preview.toPlainText().strip()
        if not txt:
            self.log("No response to copy")
            return
        try:
            pyperclip.copy(txt)
            self.log("Copied selected response to clipboard")
        except Exception as e:
            self.log("Clipboard copy failed: %s" % e)

    def auto_pick_by_model(self):
        # Ask the model to pick the best candidate among shown ones.
        candidates = [self.responses_list.item(i).data(QtCore.Qt.UserRole)
                      for i in range(self.responses_list.count())]
        candidates = [c for c in candidates if c]
        if len(candidates) < 2:
            self.log("Need at least 2 candidates to auto-pick")
            return

        api_key = self.api_key_edit.text().strip() or os.environ.get("OPENAI_API_KEY")
        base_url = os.environ.get("OPENAI_API_BASE") or os.environ.get("OPENAI_BASE_URL")
        model = self.model_combo.currentText().strip()

        # Build a short prompt instructing to pick the best candidate and return only the chosen text
        pick_prompt = "Pick the best candidate (most helpful and concise). Return only the chosen text, no commentary.\n\nCandidates:\n"
        for i, c in enumerate(candidates, 1):
            pick_prompt += f"({i}) {c}\n\n"

        messages = [{"role": "system", "content": DEFAULT_SYSTEM_PROMPT},
                    {"role": "user", "content": pick_prompt}]

        # Run short API call on a background thread
        self.status.showMessage("Auto-picking best candidate...")

        def run_pick():
            try:
                client_kwargs = {}
                if api_key:
                    client_kwargs["api_key"] = api_key
                if base_url:
                    client_kwargs["api_base"] = base_url
                client = OpenAI(**client_kwargs) if client_kwargs else OpenAI()

                resp = client.chat.completions.create(model=model, messages=messages, temperature=0.0, n=1)
                text = ""
                # adapt to new response shape
                choices = getattr(resp, "choices", None) or resp.get("choices", [])
                if choices:
                    first = choices[0]
                    # v1 objects sometimes have message/content nested
                    if isinstance(first, dict):
                        m = first.get("message") or {}
                        text = m.get("content") or first.get("text") or ""
                    else:
                        # if it's an object with message attribute
                        msg = getattr(first, "message", None)
                        if msg:
                            text = getattr(msg, "content", "") or ""
                        else:
                            text = getattr(first, "text", "") or ""
                # find best candidate by simple substring match
                chosen = text.strip()
                idx = None
                for i, c in enumerate(candidates):
                    if chosen and chosen in c:
                        idx = i
                        break
                if idx is None:
                    # fallback: use first
                    idx = 0
                QtCore.QMetaObject.invokeMethod(self, "_apply_auto_pick", QtCore.Qt.QueuedConnection,
                                                QtCore.Q_ARG(int, idx),
                                                QtCore.Q_ARG(str, chosen))
            except Exception as e:
                tb = traceback.format_exc()
                QtCore.QMetaObject.invokeMethod(self, "_auto_pick_failed", QtCore.Qt.QueuedConnection,
                                                QtCore.Q_ARG(str, str(e)),
                                                QtCore.Q_ARG(str, tb))

        threading.Thread(target=run_pick, daemon=True).start()

    @QtCore.pyqtSlot(int, str)
    def _apply_auto_pick(self, idx: int, chosen_text: str):
        item = self.responses_list.item(idx)
        if item:
            self.responses_list.setCurrentItem(item)
            val = item.data(QtCore.Qt.UserRole)
            self.response_preview.setPlainText(val)
            pyperclip.copy(val)
            self.log("Auto-picked candidate #%d and copied to clipboard" % (idx + 1))
            self.status.showMessage("Auto-picked")

    @QtCore.pyqtSlot(str, str)
    def _auto_pick_failed(self, err: str, tb: str):
        self.log("Auto-pick failed: %s\n%s" % (err, tb))
        self.status.showMessage("Auto-pick failed")

    def on_history_selected(self, item: QtWidgets.QListWidgetItem):
        data = item.data(QtCore.Qt.UserRole) or {}
        prompt = data.get("prompt", "")
        responses = data.get("responses", [])
        self.prompt_edit.setPlainText(prompt)
        self.responses_list.clear()
        for r in responses:
            it = QtWidgets.QListWidgetItem(r[:200].replace("\n", " "))
            it.setData(QtCore.Qt.UserRole, r)
            self.responses_list.addItem(it)
        if responses:
            self.response_preview.setPlainText(responses[0])

    def _update_token_estimate(self):
        txt = self.prompt_edit.toPlainText()
        # crude token estimate: 1 token ~ 0.75 words
        words = len(txt.split())
        est = int(max(1, words / 0.75))
        self.token_label.setText(f"Est. tokens: {est} (words: {words})")

    def log(self, *parts):
        s = " ".join(str(p) for p in parts)
        self.log_view.appendPlainText(s)


def main():
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
