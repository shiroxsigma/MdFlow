"""MdFlow デスクトップGUI（QWebEngine + QWebChannel）.

NoteWithPixie 風のダークUI（Monaco系エディタ想定・現状はtextarea / markdown-it / mermaid）を
サーバなしで QWebEngineView に丸ごと描画し、ロジックは Python(Bridge) が担う。
外部ネットワーク通信は行わない（アセットはローカル同梱）。
"""
from __future__ import annotations

import base64
import json
import tempfile
from pathlib import Path
from typing import Optional

from .qt import (
    QtCore, QtGui, QtWidgets, QWebEngineView, QWebEngineSettings,
    QWebChannel, QT_API,
)
from . import pptx_io
from .document import Document
from .app_bridge import Bridge

_RES = Path(__file__).parent / "resources"
_SAMPLE = Path(__file__).parents[1] / "samples" / "login.md"


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MdFlow")
        self.resize(1440, 900)
        self.setAcceptDrops(True)

        self.view = QWebEngineView(self)
        self.setCentralWidget(self.view)

        # ローカルファイル間のアクセスを許可（外部URLは不可）
        s = self.view.settings()
        try:
            s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
            s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        except AttributeError:  # PyQt5 の列挙名
            s.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
            s.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, False)

        self.bridge = Bridge(self, initial_text=_SAMPLE.read_text("utf-8"))
        self.channel = QWebChannel(self)
        self.channel.registerObject("bridge", self.bridge)
        self.view.page().setWebChannel(self.channel)

        self.view.load(QtCore.QUrl.fromLocalFile(str(_RES / "ui.html")))

    # ---- ドラッグ＆ドロップ（.pptx / .md）----
    def dragEnterEvent(self, e: QtGui.QDragEnterEvent) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e: QtGui.QDropEvent) -> None:
        for url in e.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.suffix.lower() == ".pptx":
                self._drop_pptx(p)
            elif p.suffix.lower() == ".md":
                self.bridge.current_path = p
                self._run_js("mdflowLoadFile", p.read_text("utf-8"))
            break

    def _drop_pptx(self, path: Path) -> None:
        try:
            payload_json = self.bridge.import_from_path(path)
        except Exception as ex:  # noqa: BLE001
            QtWidgets.QMessageBox.warning(self, "取込失敗", str(ex))
            return
        self._run_js("mdflowLoadImport", payload_json)

    def _run_js(self, fn: str, arg: str) -> None:
        self.view.page().runJavaScript(f"window.{fn}({json.dumps(arg)})")


def main() -> int:
    import sys
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("MdFlow")
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
