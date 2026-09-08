"""PyQt6 / PyQt5 の両対応シム。WebEngine を含めて import を一本化する.

インストール例（どちらか）:
    pip install PyQt6 PyQt6-WebEngine
    pip install PyQt5 PyQtWebEngine
"""
from __future__ import annotations

QT_API = None

try:  # PyQt6 優先（Python 3.13 で入りやすい）
    from PyQt6 import QtCore, QtGui, QtWidgets  # type: ignore
    from PyQt6.QtWebChannel import QWebChannel  # type: ignore
    from PyQt6.QtWebEngineCore import QWebEngineSettings  # type: ignore
    from PyQt6.QtWebEngineWidgets import QWebEngineView  # type: ignore
    QT_API = "PyQt6"
except Exception:  # pragma: no cover - 環境依存
    try:
        from PyQt5 import QtCore, QtGui, QtWidgets  # type: ignore
        from PyQt5.QtWebChannel import QWebChannel  # type: ignore
        from PyQt5.QtWebEngineWidgets import QWebEngineSettings, QWebEngineView  # type: ignore
        QT_API = "PyQt5"
    except Exception as e:  # pragma: no cover
        raise ImportError(
            "PyQt6(+PyQt6-WebEngine) または PyQt5(+PyQtWebEngine) が必要です。\n"
            "  pip install PyQt6 PyQt6-WebEngine\n"
            f"元エラー: {e}"
        ) from e

__all__ = [
    "QtCore", "QtGui", "QtWidgets", "QWebEngineView",
    "QWebEngineSettings", "QWebChannel", "QT_API",
]
