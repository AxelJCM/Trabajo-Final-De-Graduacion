"""GUI module for the mirror display.

In production, render camera feed, pose overlays, and feedback.
"""
from __future__ import annotations

import argparse
import asyncio
import time

try:
    from PyQt5 import QtWidgets, QtGui, QtCore
except Exception:  # pragma: no cover
    QtWidgets = None  # type: ignore
    QtGui = None  # type: ignore
    QtCore = None  # type: ignore


class OverlayWindow(QtWidgets.QWidget):  # type: ignore
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.hr = None
        self.quality = None
        self.hint = ""
        self.setWindowTitle("Smart Mirror")
        self.setStyleSheet("background-color: black;")
        self.setGeometry(100, 100, 800, 480)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(1000)

    def paintEvent(self, event):  # pragma: no cover
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        # HR
        p.setPen(QtGui.QColor("white"))
        font = QtGui.QFont("Arial", 36, QtGui.QFont.Bold)
        p.setFont(font)
        hr_text = f"HR: {self.hr if self.hr is not None else '--'}"
        p.drawText(30, 80, hr_text)
        # Quality color
        q = self.quality if self.quality is not None else 0
        color = QtGui.QColor("red")
        if q >= 80:
            color = QtGui.QColor("green")
        elif q >= 60:
            color = QtGui.QColor("yellow")
        p.setBrush(color)
        p.setPen(QtCore.Qt.NoPen)
        p.drawEllipse(30, 100, 30, 30)
        # Hint
        p.setPen(QtGui.QColor("white"))
        font2 = QtGui.QFont("Arial", 18)
        p.setFont(font2)
        p.drawText(30, 150, self.hint or "")

    def poll(self):  # pragma: no cover
        import requests
        try:
            r1 = requests.get(f"{self.base_url}/biometrics/last", timeout=3)
            if r1.ok:
                d = r1.json().get("data", {})
                self.hr = d.get("heart_rate_bpm")
        except Exception:
            pass
        try:
            r2 = requests.post(f"{self.base_url}/posture", json={}, timeout=3)
            if r2.ok:
                d2 = r2.json().get("data", {})
                self.quality = d2.get("quality") or d2.get("fps")  # fallback
                self.hint = d2.get("feedback") or ""
        except Exception:
            pass
        self.update()


class MirrorApp:
    """Qt overlay with CLI fallback."""

    def run(self, base_url: str) -> None:  # pragma: no cover - GUI
        if QtWidgets is None:
            print("PyQt5 not available. Run CLI: python -m app.gui.mirror_gui --cli")
            return
        app = QtWidgets.QApplication([])
        w = OverlayWindow(base_url)
        w.show()
        app.exec_()


async def cli_loop(base_url: str) -> None:
    import httpx

    async with httpx.AsyncClient(timeout=3) as client:
        while True:
            try:
                b = await client.post(f"{base_url}/biometrics", json={})
                p = await client.post(f"{base_url}/posture", json={})
                hr = b.json().get("data", {}).get("heart_rate_bpm")
                feedback = p.json().get("data", {}).get("feedback")
                print(f"HR={hr} | Posture={feedback}")
            except Exception as exc:
                print(f"CLI error: {exc}")
            await asyncio.sleep(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cli", action="store_true", help="Run CLI fallback mode")
    parser.add_argument("--overlay", action="store_true", help="Run GUI overlay mode")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="API base URL")
    args = parser.parse_args()
    if args.cli:
        asyncio.run(cli_loop(args.base_url))
    else:
        MirrorApp().run(args.base_url)


if __name__ == "__main__":
    main()
