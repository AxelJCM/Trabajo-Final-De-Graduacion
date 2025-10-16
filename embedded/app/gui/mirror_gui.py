"""HUD renderer for the smart mirror."""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

try:
    from PyQt5 import QtCore, QtGui, QtWidgets  # type: ignore
except Exception:  # pragma: no cover
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
    """Overlay that blends the live camera frame with session metrics."""

    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self.state = HudState({}, {}, {})
        self.last_error: Optional[str] = None
        self.frame_pixmap: Optional[QtGui.QPixmap] = None

        self.setWindowTitle("TFG Smart Mirror HUD")
        self.setCursor(QtCore.Qt.BlankCursor)
        self.setMinimumSize(720, 1280)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(1000)

    def paintEvent(self, event):  # pragma: no cover - GUI only
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        if self.frame_pixmap:
            scaled = self.frame_pixmap.scaled(
                self.size(), QtCore.Qt.KeepAspectRatioByExpanding, QtCore.Qt.SmoothTransformation
            )
            painter.drawPixmap((self.width() - scaled.width()) // 2, (self.height() - scaled.height()) // 2, scaled)
        else:
            painter.fillRect(self.rect(), QtGui.QColor(0, 0, 0))

        margin = int(self.width() * 0.05)
        panel_width = int(self.width() * 0.42)
        panel_height = int(self.height() * 0.18)

        session_rect = QtCore.QRect(margin, margin, panel_width, panel_height)
        biom_rect = QtCore.QRect(self.width() - panel_width - margin, margin, panel_width, panel_height)
        posture_rect = QtCore.QRect(
            margin,
            margin + panel_height + int(self.height() * 0.03),
            self.width() - 2 * margin,
            int(self.height() * 0.34),
        )
        footer_rect = QtCore.QRect(
            margin,
            self.height() - margin - int(self.height() * 0.1),
            self.width() - 2 * margin,
            int(self.height() * 0.08),
        )

        self._draw_session(painter, session_rect)
        self._draw_biometrics(painter, biom_rect)
        self._draw_posture(painter, posture_rect)
        self._draw_footer(painter, footer_rect)

    def poll(self):  # pragma: no cover - GUI only
        import requests

        try:
            self.last_error = None
            session_r = requests.get(f"{self.base_url}/session/status", timeout=3)
            if session_r.ok:
                self.state.session = session_r.json().get("data", {})
            biometrics_r = requests.get(f"{self.base_url}/biometrics/last", timeout=3)
            if biometrics_r.ok:
                self.state.biometrics = biometrics_r.json().get("data", {})
            posture_r = requests.post(f"{self.base_url}/posture", json={}, timeout=3)
            if posture_r.ok:
                posture_data = posture_r.json().get("data", {})
                self.state.posture = posture_data
                frame_b64 = posture_data.get("frame_b64")
                if frame_b64:
                    try:
                        byte_array = QtCore.QByteArray.fromBase64(frame_b64.encode("utf-8"))
                        image = QtGui.QImage.fromData(byte_array, "JPG")
                        if not image.isNull():
                            self.frame_pixmap = QtGui.QPixmap.fromImage(image)
                    except Exception as exc:  # pragma: no cover
                        self.last_error = f"Frame decode error: {exc}"
                else:
                    self.frame_pixmap = None
        except Exception as exc:  # pragma: no cover
            self.last_error = str(exc)
        self.update()

    def keyPressEvent(self, event):  # pragma: no cover - GUI only
        if event.key() == QtCore.Qt.Key_Escape:
            self.close()

    # --- drawing helpers ------------------------------------------------

    def _draw_panel_background(self, painter: QtGui.QPainter, rect: QtCore.QRect) -> None:
        painter.save()
        painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 40), 1))
        painter.setBrush(QtGui.QColor(0, 0, 0, 160))
        painter.drawRoundedRect(rect, 24, 24)
        painter.restore()

    def _draw_text(
        self,
        painter: QtGui.QPainter,
        text: str,
        position: QtCore.QPoint,
        size: int,
        *,
        color: str = "white",
        bold: bool = False,
    ) -> None:
        painter.save()
        font = QtGui.QFont("Roboto", pointSize=size)
        font.setBold(bold)
        painter.setFont(font)
        painter.setPen(QtGui.QColor(color))
        painter.drawText(position, text)
        painter.restore()

    def _draw_session(self, painter: QtGui.QPainter, rect: QtCore.QRect) -> None:
        self._draw_panel_background(painter, rect)
        session = self.state.session or {}
        status = (session.get("status") or "IDLE").upper()
        started = session.get("started_at") or "--"
        duration = _fmt_duration(session.get("duration_sec"))
        command = session.get("last_command") or "--"
        command_ts = _parse_timestamp(session.get("last_command_ts"))
        timestamp = command_ts.strftime("%H:%M:%S") if command_ts else "--"

        x = rect.x() + 30
        y = rect.y() + 55
        line = 38
        self._draw_text(painter, f"Sesion: {status}", QtCore.QPoint(x, y), 34, bold=True)
        self._draw_text(painter, f"Inicio: {started}", QtCore.QPoint(x, y + line), 22)
        self._draw_text(painter, f"Duracion total: {duration}", QtCore.QPoint(x, y + line * 2), 22)
        self._draw_text(painter, f"Ultimo comando: {command} ({timestamp})", QtCore.QPoint(x, y + line * 3), 20)

    def _draw_biometrics(self, painter: QtGui.QPainter, rect: QtCore.QRect) -> None:
        self._draw_panel_background(painter, rect)
        biometrics = self.state.biometrics or {}
        hr = biometrics.get("heart_rate_bpm", "--")
        steps = biometrics.get("steps", "--")
        zone_label = biometrics.get("zone_label") or "Sin datos"
        zone_color = biometrics.get("zone_color") or "#7F8C8D"
        status_icon = biometrics.get("fitbit_status_icon") or "O"
        status_level = biometrics.get("fitbit_status_level", "yellow")
        status_msg = biometrics.get("fitbit_status_message") or ""

        x = rect.x() + 30
        y = rect.y() + 55
        line = 36

        painter.save()
        painter.setPen(QtGui.QPen(QtGui.QColor(zone_color)))
        painter.setBrush(QtGui.QColor(zone_color))
        painter.drawRoundedRect(rect.x() + rect.width() - 140, rect.y() + 30, 110, 70, 16, 16)
        painter.restore()

        self._draw_text(
            painter,
            f"FC {hr} bpm",
            QtCore.QPoint(rect.x() + rect.width() - 128, rect.y() + 80),
            20,
            color="black",
            bold=True,
        )
        self._draw_text(
            painter,
            zone_label,
            QtCore.QPoint(rect.x() + rect.width() - 136, rect.y() + 108),
            14,
            color="white",
        )

        self._draw_text(painter, f"Pasos: {steps}", QtCore.QPoint(x, y), 24)
        self._draw_text(painter, f"{status_icon} Fitbit {status_level}", QtCore.QPoint(x, y + line), 22)
        if status_msg:
            self._draw_text(painter, status_msg, QtCore.QPoint(x, y + line * 2), 20)

    def _draw_posture(self, painter: QtGui.QPainter, rect: QtCore.QRect) -> None:
        self._draw_panel_background(painter, rect)
        posture = self.state.posture or {}
        session = self.state.session or {}
        exercise = posture.get("exercise") or session.get("exercise") or "--"
        phase = posture.get("phase_label") or posture.get("phase") or "--"
        reps_total = posture.get("rep_count", 0)
        reps_current = posture.get("current_exercise_reps", 0)
        feedback = posture.get("feedback") or "Sin feedback"
        quality = posture.get("quality", 0)
        latency = posture.get("latency_ms_p50")
        fps = posture.get("fps")

        latency_text = f"{latency:.1f}" if isinstance(latency, (int, float)) else "--"
        fps_text = f"{fps:.1f}" if isinstance(fps, (int, float)) else "--"

        x = rect.x() + 30
        y = rect.y() + 60
        line = 44
        self._draw_text(painter, f"Ejercicio: {exercise}", QtCore.QPoint(x, y), 32, bold=True)
        self._draw_text(painter, f"Reps sesion: {reps_total}", QtCore.QPoint(x, y + line), 24)
        self._draw_text(painter, f"Reps ejercicio: {reps_current}", QtCore.QPoint(x, y + line * 2), 24)
        self._draw_text(painter, f"Fase: {phase}", QtCore.QPoint(x, y + line * 3), 24)
        self._draw_text(painter, f"Calidad instantanea: {quality:.0f}", QtCore.QPoint(x, y + line * 4), 24)
        metrics_text = f"FPS: {fps_text}  |  Latencia p50: {latency_text} ms"
        self._draw_text(painter, metrics_text, QtCore.QPoint(x, y + line * 5), 20)

        painter.save()
        painter.setPen(QtGui.QPen(QtGui.QColor("#F1C40F")))
        self._draw_text(painter, feedback, QtCore.QPoint(x, y + line * 6), 26)
        painter.restore()

    def _draw_footer(self, painter: QtGui.QPainter, rect: QtCore.QRect) -> None:
        self._draw_panel_background(painter, rect)
        session = self.state.session or {}
        active = session.get("duration_active_sec")
        footer = f"Tiempo activo: {_fmt_duration(active)}"

        x = rect.x() + 30
        y = rect.y() + rect.height() // 2 + 10
        self._draw_text(painter, footer, QtCore.QPoint(x, y), 26, bold=True)

        if self.last_error:
            self._draw_text(painter, f"Error HUD: {self.last_error}", QtCore.QPoint(x, y + 40), 20, color="#E74C3C")


async def cli_loop(base_url: str) -> None:
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
                fitbit_status = biometrics.get("fitbit_status_icon", "O")
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
                    f"[Sesion {status}] dur={duration} activo={active} cmd={command} | "
                    f"FC={hr} ({zone}) pasos={steps} {fitbit_status} | "
                    f"{exercise}: total={reps_total} ejercicio={reps_current} | {feedback} | zona_color={zone_color}"
                )
            except Exception as exc:
                print(f"HUD error: {exc}")
            await asyncio.sleep(1)


class MirrorApp:
    """Qt overlay wrapper."""

    def run(self, base_url: str) -> None:  # pragma: no cover - GUI only
        if QtWidgets is None:
            print("PyQt5 no esta instalado. Ejecuta en modo CLI con --cli.")
            return
        app = QtWidgets.QApplication([])
        window = OverlayWindow(base_url)
        window.showFullScreen()
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
