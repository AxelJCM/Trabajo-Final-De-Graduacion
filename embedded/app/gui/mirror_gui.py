"""HUD renderer for the smart mirror.

Provides both a PyQt overlay and a CLI dashboard that consume the API in real time.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

try:  # Optional dependency for the overlay
    from PyQt5 import QtCore, QtGui, QtWidgets  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    QtWidgets = None  # type: ignore
    QtGui = None  # type: ignore
    QtCore = None  # type: ignore


def _fmt_duration(seconds: Optional[int]) -> str:
    if seconds is None:
        return "--:--"
    minutes, secs = divmod(max(0, int(seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


@dataclass
class HudState:
    biometrics: Dict[str, Any]
    posture: Dict[str, Any]
    session: Dict[str, Any]


class OverlayWindow(QtWidgets.QWidget):  # type: ignore
    """Simple overlay that paints the HUD layout."""

    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self.state = HudState({}, {}, {})
        self.last_error: Optional[str] = None

        self.setWindowTitle("TFG Smart Mirror HUD")
        self.setStyleSheet("background-color: black;")
        self.setGeometry(100, 100, 1024, 600)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(1000)

    def paintEvent(self, event):  # pragma: no cover - GUI only
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.fillRect(self.rect(), QtGui.QColor(0, 0, 0))

        self._draw_session(painter)
        self._draw_biometrics(painter)
        self._draw_posture(painter)
        self._draw_footer(painter)

    def poll(self):  # pragma: no cover - GUI only
        import requests

        try:
            session_r = requests.get(f"{self.base_url}/session/status", timeout=3)
            if session_r.ok:
                self.state.session = session_r.json().get("data", {})
            biometrics_r = requests.get(f"{self.base_url}/biometrics/last", timeout=3)
            if biometrics_r.ok:
                self.state.biometrics = biometrics_r.json().get("data", {})
            posture_r = requests.post(f"{self.base_url}/posture", json={}, timeout=3)
            if posture_r.ok:
                self.state.posture = posture_r.json().get("data", {})
            self.last_error = None
        except Exception as exc:  # pragma: no cover
            self.last_error = str(exc)
        self.update()

    # --- drawing helpers ------------------------------------------------

    def _draw_text(self, painter: QtGui.QPainter, text: str, x: int, y: int, size: int, color: str = "white", bold: bool = False):
        font = QtGui.QFont("Roboto", pointSize=size)
        font.setBold(bold)
        painter.setFont(font)
        painter.setPen(QtGui.QColor(color))
        painter.drawText(x, y, text)

    def _draw_session(self, painter: QtGui.QPainter):
        session = self.state.session or {}
        status = (session.get("status") or "idle").upper()
        started = session.get("started_at")
        duration = session.get("duration_sec")
        command = session.get("last_command") or "--"
        command_ts = _parse_timestamp(session.get("last_command_ts"))
        timestamp = command_ts.strftime("%H:%M:%S") if command_ts else "--"

        self._draw_text(painter, f"Sesión: {status}", 30, 60, 28, bold=True)
        self._draw_text(painter, f"Inicio: {started or '--'}", 30, 100, 18)
        self._draw_text(painter, f"Duración total: {_fmt_duration(duration)}", 30, 130, 18)
        self._draw_text(painter, f"Comando: {command} ({timestamp})", 30, 160, 18)

    def _draw_biometrics(self, painter: QtGui.QPainter):
        biometrics = self.state.biometrics or {}
        hr = biometrics.get("heart_rate_bpm", "--")
        steps = biometrics.get("steps", "--")
        zone_label = biometrics.get("zone_label") or "Sin datos"
        zone_color = biometrics.get("zone_color") or "#7F8C8D"
        status_icon = biometrics.get("fitbit_status_icon") or "🟡"
        status_level = biometrics.get("fitbit_status_level", "yellow")
        status_msg = biometrics.get("fitbit_status_message") or ""

        qt_color = QtGui.QColor(zone_color)
        painter.setPen(qt_color)
        painter.setBrush(qt_color)
        painter.drawRoundedRect(760, 40, 200, 60, 8, 8)

        self._draw_text(painter, f"FC {hr} bpm", 770, 80, 26, color="black", bold=True)
        self._draw_text(painter, zone_label, 770, 110, 16, color="white")

        self._draw_text(painter, f"Pasos: {steps}", 760, 150, 18)
        self._draw_text(painter, f"{status_icon} Fitbit {status_level}", 760, 180, 18)
        if status_msg:
            self._draw_text(painter, status_msg, 760, 210, 16)

    def _draw_posture(self, painter: QtGui.QPainter):
        posture = self.state.posture or {}
        session = self.state.session or {}
        exercise = posture.get("exercise") or session.get("exercise") or "--"
        phase = posture.get("phase_label") or posture.get("phase") or "--"
        reps_total = posture.get("rep_count", 0)
        reps_current = posture.get("current_exercise_reps", 0)
        feedback = posture.get("feedback") or "Sin feedback"
        quality = posture.get("quality", 0)

        self._draw_text(painter, f"Ejercicio: {exercise}", 30, 230, 26, bold=True)
        self._draw_text(painter, f"Reps sesión: {reps_total}", 30, 270, 20)
        self._draw_text(painter, f"Reps ejercicio: {reps_current}", 30, 300, 20)
        self._draw_text(painter, f"Fase: {phase}", 30, 330, 20)
        self._draw_text(painter, f"Calidad: {quality:.0f}", 30, 360, 20)

        painter.setPen(QtGui.QColor("#F1C40F"))
        self._draw_text(painter, feedback, 30, 400, 24)

    def _draw_footer(self, painter: QtGui.QPainter):
        session = self.state.session or {}
        active = session.get("duration_active_sec")
        footer = f"Tiempo activo: {_fmt_duration(active)}"
        painter.setPen(QtGui.QColor("white"))
        self._draw_text(painter, footer, 30, self.height() - 40, 20)

        if self.last_error:
            self._draw_text(painter, f"Error HUD: {self.last_error}", 30, self.height() - 15, 14, color="#E74C3C")


async def cli_loop(base_url: str) -> None:
    """ASCII dashboard for environments without a GUI."""
    import httpx

    base = base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=3) as client:
        while True:
            try:
                biometrics = (await client.get(f"{base}/biometrics/last")).json().get("data", {})
                session = (await client.get(f"{base}/session/status")).json().get("data", {})
                posture = (await client.post(f"{base}/posture", json={})).json().get("data", {})

                hr = biometrics.get("heart_rate_bpm", "--")
                zone = biometrics.get("zone_label", "--")
                zone_color = biometrics.get("zone_color", "#7F8C8D")
                fitbit_status = biometrics.get("fitbit_status_icon", "🟡")
                steps = biometrics.get("steps", "--")

                status = session.get("status", "--")
                duration = _fmt_duration(session.get("duration_sec"))
                active = _fmt_duration(session.get("duration_active_sec"))
                command = session.get("last_command", "--")

                exercise = posture.get("exercise") or session.get("exercise") or "--"
                reps_total = posture.get("rep_count", 0)
                reps_current = posture.get("current_exercise_reps", 0)
                feedback = posture.get("feedback", "Sin feedback")

                print(
                    f"[Sesión {status}] dur={duration} activo={active} cmd={command} | "
                    f"FC={hr} ({zone}) pasos={steps} {fitbit_status} | "
                    f"{exercise}: total={reps_total} ejercicio={reps_current} | {feedback} | zona_color={zone_color}"
                )
            except Exception as exc:
                print(f"HUB error: {exc}")
            await asyncio.sleep(1)


class MirrorApp:
    """Qt overlay wrapper."""

    def run(self, base_url: str) -> None:  # pragma: no cover - GUI only
        if QtWidgets is None:
            print("PyQt5 no está instalado. Ejecuta en modo CLI con --cli.")
            return
        app = QtWidgets.QApplication([])
        window = OverlayWindow(base_url)
        window.show()
        app.exec_()


def main() -> None:
    parser = argparse.ArgumentParser(description="HUD para el TFG Smart Mirror")
    parser.add_argument("--cli", action="store_true", help="Ejecutar en modo CLI")
    parser.add_argument("--overlay", action="store_true", help="Ejecutar overlay PyQt (por defecto)")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="URL base de la API")
    args = parser.parse_args()

    if args.cli:
        asyncio.run(cli_loop(args.base_url))
    else:
        MirrorApp().run(args.base_url)


if __name__ == "__main__":
    main()
