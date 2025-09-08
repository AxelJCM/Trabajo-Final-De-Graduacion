"""GUI module for the mirror display.

In production, render camera feed, pose overlays, and feedback.
"""
from __future__ import annotations

try:
    from PyQt5 import QtWidgets
except Exception:  # pragma: no cover
    QtWidgets = None  # type: ignore


class MirrorApp:
    """Minimal Qt app stub."""

    def run(self) -> None:  # pragma: no cover - GUI
        if QtWidgets is None:
            print("PyQt5 not available on this device.")
            return
        app = QtWidgets.QApplication([])
        w = QtWidgets.QLabel("Espejo Interactivo - Listo")
        w.resize(640, 480)
        w.show()
        app.exec_()
