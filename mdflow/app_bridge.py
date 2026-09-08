"""QWebChannel ブリッジ: ui.js から呼ばれるスロット群.

純ロジックは webapi に委譲し、ここはダイアログ等のGUI副作用と入出力整形のみ。
戻り値は JSON 文字列（QWebChannel は result=str を JS のコールバックへ渡す）。
"""
from __future__ import annotations

import base64
import json
import tempfile
from pathlib import Path
from typing import Optional

from .qt import QtCore, QtWidgets
from . import pptx_io, webapi

pyqtSlot = QtCore.pyqtSlot


class Bridge(QtCore.QObject):
    def __init__(self, window: QtWidgets.QWidget, initial_text: str = ""):
        super().__init__(window)
        self._window = window
        self._initial = initial_text
        self.current_path: Optional[Path] = None

    # ---- 初期化 ----
    @pyqtSlot(result=str)
    def initialText(self) -> str:
        return self._initial

    # ---- 参照・描画（純ロジック委譲）----
    @pyqtSlot(str, result=str)
    def parseDoc(self, md: str) -> str:
        return json.dumps(webapi.parse_doc(md), ensure_ascii=False)

    @pyqtSlot(str, str, str, str, result=str)
    def renderDiagram(self, md: str, diagram_id: str, conditions: str, preset: str) -> str:
        return json.dumps(
            webapi.render_diagram(md, diagram_id, conditions, preset), ensure_ascii=False)

    # ---- 条件（プリセット）登録 ----
    @pyqtSlot(str, str, str, str, str, result=str)
    def addPreset(self, md: str, diagram_id: str, name: str, when: str, nodes_json: str) -> str:
        try:
            nodes = json.loads(nodes_json or "[]")
        except json.JSONDecodeError:
            nodes = []
        return json.dumps(
            webapi.add_preset(md, diagram_id, name, when, nodes), ensure_ascii=False)

    # ---- ファイル ----
    @pyqtSlot(result=str)
    def openFile(self) -> str:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self._window, "Markdownを開く", "", "Markdown (*.md);;All (*.*)")
        if not path:
            return ""
        self.current_path = Path(path)
        return self.current_path.read_text("utf-8")

    @pyqtSlot(str, str, str, result=str)
    def saveFile(self, md: str, diagram_id: str, preset: str) -> str:
        md = webapi.apply_selection(md, diagram_id, preset)  # 選択状態を正へ反映
        path = self.current_path
        if path is None:
            p, _ = QtWidgets.QFileDialog.getSaveFileName(
                self._window, "保存", "", "Markdown (*.md)")
            if not p:
                return json.dumps({"md": md, "message": "キャンセル"}, ensure_ascii=False)
            path = Path(p)
            self.current_path = path
        path.write_text(md, encoding="utf-8")
        return json.dumps({"md": md, "message": f"保存: {path.name}"}, ensure_ascii=False)

    # ---- PPT出力 ----
    @pyqtSlot(str, str, str, str, str, result=str)
    def exportPpt(self, md: str, diagram_id: str, conditions: str, preset: str,
                  png_dataurl: str) -> str:
        try:
            payload = webapi.build_payload(md, diagram_id, conditions, preset)
        except Exception as e:  # noqa: BLE001
            return json.dumps({"error": f"構築失敗: {e}"}, ensure_ascii=False)

        default = f"{diagram_id or 'diagram'}.pptx"
        out, _ = QtWidgets.QFileDialog.getSaveFileName(
            self._window, "PPTへ出力", default, "PowerPoint (*.pptx)")
        if not out:
            return json.dumps({"error": "キャンセル"}, ensure_ascii=False)

        png = Path(tempfile.gettempdir()) / f"mdflow_{diagram_id or 'd'}.png"
        png.write_bytes(_decode_dataurl(png_dataurl))
        pptx_io.export_ppt(payload, png, Path(out), title=diagram_id)
        return json.dumps({"path": str(out)}, ensure_ascii=False)

    # ---- PPT取込 ----
    @pyqtSlot(result=str)
    def importPpt(self) -> str:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self._window, "PPTを取り込む", "", "PowerPoint (*.pptx)")
        if not path:
            return json.dumps({"error": "キャンセル"}, ensure_ascii=False)
        try:
            return self.import_from_path(Path(path))
        except Exception as e:  # noqa: BLE001
            return json.dumps({"error": f"取込失敗: {e}"}, ensure_ascii=False)

    def import_from_path(self, path: Path) -> str:
        res = pptx_io.import_ppt(path)
        return json.dumps(webapi.import_result_to_dict(res), ensure_ascii=False)


def _decode_dataurl(dataurl: str) -> bytes:
    if "," in dataurl:
        dataurl = dataurl.split(",", 1)[1]
    return base64.b64decode(dataurl)
