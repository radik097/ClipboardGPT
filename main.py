#!/usr/bin/env python3
"""Launcher for BeepConf Qt Chat using the provided Qt Designer UI file.

This runtime loads `ui/mainwindows.ui` via PyQt5.uic and keeps UI and core (API)
separated. Do not generate `ui_*.py` files.
"""
import os
import sys
from pathlib import Path
from typing import List

from PyQt5 import QtWidgets, uic

from core import ApiWorker, notify, copy_to_clipboard, estimate_tokens, load_json, save_json, HISTORY_FILE, CONFIG_FILE
import json

# optional settings file (created from ghub_chatgpt_clip.py contents)
SETTINGS_PATH = Path(__file__).parent / "settings.json"


UI_FILE = Path(__file__).parent / "ui" / "mainwindows.ui"


class MainApp(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        uic.loadUi(str(UI_FILE), self)

        # state
        self.worker = None
        self.total_tokens = 0
        self.total_cost = 0.0

        # UI wiring (names from mainwindows.ui)
        # Buttons and widgets referenced in the UI
        self.send_btn.clicked.connect(self.on_send)
        self.attach_btn.clicked.connect(self.on_attach)
        self.chatList.itemClicked.connect(self.on_chat_selected)

        # load config/prompts
        cfg = load_json(CONFIG_FILE, {})
        self.token_price_per_1k = float(cfg.get("token_price_per_1k", 0.002))

        # load prompt presets from settings.json if present
        self.prompt_presets = []
        try:
            if SETTINGS_PATH.exists():
                with open(SETTINGS_PATH, "r", encoding="utf-8") as fh:
                    s = json.load(fh)
                    self.prompt_presets = s.get("prompt_presets", [])
        except Exception:
            self.prompt_presets = []

        # Wire prompts button to show presets (if UI contains promptsButton)
        try:
            if hasattr(self, "promptsButton"):
                self.promptsButton.clicked.connect(self.show_prompts_menu)
        except Exception:
            pass

        self._load_history()

    def _load_history(self):
        hist = load_json(HISTORY_FILE, [])
        for e in reversed(hist):
            title = (e.get("prompt") or "")[:80]
            it = QtWidgets.QListWidgetItem(title)
            it.setData(0, e)
            self.chatList.addItem(it)

    def on_attach(self):
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Attach files")
        cur = self.input_line.text() or ""
        for p in files:
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    txt = f.read()
                cur += f"\n\n[Attachment: {p}]\n" + txt[:2000]
            except Exception as e:
                try:
                    self.log.appendPlainText(f"Attach failed: {e}")
                except Exception:
                    pass
                notify("Attach failed", str(e))
        self.input_line.setText(cur)

    def show_prompts_menu(self):
        # Build a QMenu from presets and exec it near the button
        menu = QtWidgets.QMenu(self)
        if not self.prompt_presets:
            menu.addAction("No presets")
        else:
            for p in self.prompt_presets:
                name = p.get("name") or (p.get("text") or "")[:40]
                act = menu.addAction(name)
                # store full text on the action
                act.setData(p.get("text"))

        act = menu.exec_(self.promptsButton.mapToGlobal(self.promptsButton.rect().bottomLeft()))
        if act is None:
            return
        text = act.data() or ""
        # insert into input_line
        try:
            self.input_line.setText(text)
        except Exception:
            pass

    def on_send(self):
        prompt = (self.input_line.text() or "").strip()
        if not prompt:
            # fallback to clipboard content
            try:
                import pyperclip

                prompt = pyperclip.paste().strip()
            except Exception:
                prompt = ""

        if not prompt:
            notify("No prompt", "Type text or put content in the clipboard.")
            return

        messages = [{"role": "system", "content": "You are a helpful assistant."}, {"role": "user", "content": prompt}]
        api_key = os.environ.get("OPENAI_API_KEY")
        base = os.environ.get("OPENAI_API_BASE") or os.environ.get("OPENAI_BASE_URL")
        model = self.model_combo.currentText() if hasattr(self, "model_combo") else "gpt-3.5-turbo"

        self.send_btn.setEnabled(False)
        try:
            self.log.appendPlainText("Sending request...")
        except Exception:
            pass
        notify("Sending", "Request sent")
        self.worker = ApiWorker(api_key, base, messages, model, temperature=0.2, n=1)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _on_finished(self, resp, err):
        self.send_btn.setEnabled(True)
        if err:
            e, tb = err
            try:
                self.log.appendPlainText(f"API error: {e}\n{tb}")
            except Exception:
                pass
            notify("API error", str(e))
            return

        choices = getattr(resp, "choices", None) or (resp.get("choices") if isinstance(resp, dict) else [])
        responses: List[str] = []
        for c in choices:
            if isinstance(c, dict):
                m = c.get("message") or {}
                txt = m.get("content") or c.get("text") or ""
            else:
                msg = getattr(c, "message", None)
                txt = getattr(msg, "content", "") if msg else getattr(c, "text", "") or ""
            txt = (txt or "").strip()
            responses.append(txt)

        if not responses:
            notify("No response", "Model returned no text")
            return

        first = responses[0]
        # show in center chat history
        try:
            self.chat_history.addItem(first)
        except Exception:
            pass
        copy_to_clipboard(first)

        # token accounting
        tokens = estimate_tokens(first, model=self.model_combo.currentText() if hasattr(self, "model_combo") else "gpt-3.5-turbo")
        cost = tokens / 1000.0 * self.token_price_per_1k
        self.total_tokens += tokens
        self.total_cost += cost
        try:
            self.tokenCostLabel.setText(f"{tokens} tokens")
            self.summaryPayLabel.setText(f"${self.total_cost:.6f}")
        except Exception:
            # UI labels may not exist in some variants
            pass

        # persist history
        entry = {"prompt": self.input_line.text(), "responses": responses, "tokens": tokens, "cost": cost}
        hist = load_json(HISTORY_FILE, [])
        hist.append(entry)
        save_json(HISTORY_FILE, hist)

        # add to left nav
        try:
            it = QtWidgets.QListWidgetItem((entry.get("prompt") or "")[:80])
            it.setData(0, entry)
            self.chatList.insertItem(0, it)
        except Exception:
            pass

        try:
            self.log.appendPlainText("Done")
        except Exception:
            pass
        notify("Response ready", "First candidate copied to clipboard")

    def on_chat_selected(self, item):
        data = item.data(0) or {}
        prompt = data.get("prompt", "")
        responses = data.get("responses", [])
        try:
            self.chat_history.clear()
            for r in responses:
                self.chat_history.addItem(r)
        except Exception:
            pass


def main():
    app = QtWidgets.QApplication(sys.argv)
    w = MainApp()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
