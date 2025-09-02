from PyQt5 import QtWidgets
from PyQt5.uic import loadUi
import sys

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        loadUi("ui/mainwindows.ui", self)
        # wire signals quickly
        self.send_btn.clicked.connect(self.on_send)
        self.attach_btn.clicked.connect(self.on_attach)
        self.toggleNavButton.clicked.connect(self.toggle_nav)

    def on_send(self):
        text = self.input_line.text().strip()
        if not text:
            return
        self.chat_history.addItem(f"You: {text}")
        self.input_line.clear()

    def on_attach(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Attach files")
        for p in paths:
            self.chat_history.addItem(f"[Attached] {p}")

    def toggle_nav(self):
        self.leftPanel.setVisible(not self.leftPanel.isVisible())

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())
