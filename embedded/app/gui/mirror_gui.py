"""HUD renderer for the smart mirror (overlay + CLI)."""
from __future__ import annotations

import argparse
import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

try:  # Optional dependency
    from PyQt5 import QtCore, QtGui, QtWidgets  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    QtWidgets = None  # type: ignore
    QtGui = None  # type: ignore
    QtCore = None  # type: ignore

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore


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


class HudStyle:
    """Centralised style constants."""

    FRAME_SCALE = 0.9
    BAR_OPACITY = 0.48
    CHIP_OPACITY = 0.52
    TOAST_DURATION = 3.0  # seconds
    IDLE_INTERVAL = 16  # ticks when idle (≈1.2s if timer=80ms)
    ACTIVE_INTERVAL = 6  # ticks when active (≈0.5s)
    FPS_TARGET_MS = 80  # ~12.5 Hz
    FONT_FAMILY = "Roboto"

    @staticmethod
    def text_primary(alpha: int = 230) -> QtGui.QColor:
        return QtGui.QColor(255, 255, 255, alpha)

    @staticmethod
    def fitbit_color(level: str) -> QtGui.QColor:
        palette = {
            "green": QtGui.QColor("#4CAF50"),
            "yellow": QtGui.QColor("#FFC107"),
            "red": QtGui.QColor("#F44336"),
        }
        return palette.get(level, QtGui.QColor("#607D8B"))


class OverlayWindow(QtWidgets.QWidget):  # type: ignore
    """Overlay that blends the live camera frame with session metrics."""

    def __init__(self, base_url: str, debug: bool = False):
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self.state = HudState({}, {}, {})
        self.debug = debug
        self.last_error: Optional[str] = None
        self.frame_pixmap: Optional[QtGui.QPixmap] = None
        self._client = requests.Session() if requests else None
        self._tick = 0
        self._poll_lock = False
        self._session_interval = HudStyle.ACTIVE_INTERVAL
        self._toast_message: Optional[str] = None
        self._toast_until: float = 0.0
        self._last_feedback_code: Optional[str] = None
        self._latest_metrics: Dict[str, Any] = {}

        self.setWindowTitle("TFG Smart Mirror HUD")
        self.setCursor(QtCore.Qt.BlankCursor)
        self.setMinimumSize(720, 1280)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(HudStyle.FPS_TARGET_MS)

    # ----------------------------- painting ---------------------------------

    def paintEvent(self, event):  # pragma: no cover - GUI only
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        if self.frame_pixmap:
            scaled = self.frame_pixmap.scaled(
                self.size(),
                QtCore.Qt.KeepAspectRatioByExpanding,
                QtCore.Qt.SmoothTransformation,
            )
            painter.drawPixmap(
                (self.width() - scaled.width()) // 2,
                (self.height() - scaled.height()) // 2,
                scaled,
            )
        else:
            painter.fillRect(self.rect(), QtGui.QColor(0, 0, 0))

        margin = max(20, int(self.height() * 0.03))
        bar_width = int(self.width() * HudStyle.FRAME_SCALE)
        bar_x = (self.width() - bar_width) // 2
        top_height = max(48, int(self.height() * 0.06))
        bottom_height = max(48, int(self.height() * 0.055))

        top_rect = QtCore.QRect(bar_x, margin, bar_width, top_height)
        bottom_rect = QtCore.QRect(
            bar_x,
            self.height() - margin - bottom_height,
            bar_width,
            bottom_height,
        )

        self._draw_top_bar(painter, top_rect)
        if (self.state.session or {}).get("status") not in {"idle", None}:
            self._draw_bottom_bar(painter, bottom_rect)
        elif self.debug:
            self._draw_debug_metrics(painter, bottom_rect)

    # ------------------------------ polling ---------------------------------

    def poll(self) -> None:  # pragma: no cover - GUI only
        if not self._client or self._poll_lock:
            return
        self._poll_lock = True
        try:
            self._tick = (self._tick + 1) % 360
            self._fetch_posture()
            if self._tick % self._session_interval == 0:
                self._fetch_session_and_biometrics()
        finally:
            self._poll_lock = False
        self._expire_toast()
        self.update()

    def _fetch_session_and_biometrics(self) -> None:
        if not self._client:
            return
        try:
            session_r = self._client.get(f"{self.base_url}/session/status", timeout=1.2)
            if session_r.ok:
                self.state.session = session_r.json().get("data", {})
        except Exception as exc:  # pragma: no cover
            self.last_error = f"session: {exc}"
        try:
            biometrics_r = self._client.get(f"{self.base_url}/biometrics/last", timeout=1.2)
            if biometrics_r.ok:
                self.state.biometrics = biometrics_r.json().get("data", {})
        except Exception as exc:  # pragma: no cover
            self.last_error = f"biometrics: {exc}"

        status = (self.state.session or {}).get("status", "idle")
        self._session_interval = HudStyle.ACTIVE_INTERVAL if status == "active" else HudStyle.IDLE_INTERVAL

    def _fetch_posture(self) -> None:
        if not self._client:
            return
        try:
            posture_r = self._client.post(f"{self.base_url}/posture", json={}, timeout=1.2)
            if posture_r.ok:
                posture_data = posture_r.json().get("data", {})
                self.state.posture = posture_data
                self._latest_metrics = {
                    "fps": posture_data.get("fps"),
                    "latency_p50": posture_data.get("latency_ms_p50"),
                    "latency_p95": posture_data.get("latency_ms_p95"),
                }
                self._update_frame(posture_data.get("frame_b64"))
                self._handle_feedback(posture_data)
        except Exception as exc:  # pragma: no cover
            self.last_error = f"posture: {exc}"

    def _update_frame(self, frame_b64: Optional[str]) -> None:
        if not frame_b64:
            self.frame_pixmap = None
            return
        try:
            byte_array = QtCore.QByteArray.fromBase64(frame_b64.encode("utf-8"))
            image = QtGui.QImage.fromData(byte_array, "JPG")
            if image.isNull():
                self.frame_pixmap = None
            else:
                self.frame_pixmap = QtGui.QPixmap.fromImage(image)
        except Exception as exc:  # pragma: no cover
            self.last_error = f"frame decode: {exc}"
            self.frame_pixmap = None

    def _handle_feedback(self, posture_data: Dict[str, Any]) -> None:
        feedback = posture_data.get("feedback")
        code = posture_data.get("feedback_code")
        if not feedback or not code:
            return
        if code in {"exercise_changed", "idle", "good", "excellent"}:
            return
        if code == self._last_feedback_code and time.time() < self._toast_until:
            return
        self._toast_message = feedback
        self._toast_until = time.time() + HudStyle.TOAST_DURATION
        self._last_feedback_code = code

    def _expire_toast(self) -> None:
        if self._toast_message and time.time() > self._toast_until:
            self._toast_message = None
            self._last_feedback_code = None

    # ----------------------------- drawing helpers ---------------------------

    def _draw_top_bar(self, painter: QtGui.QPainter, rect: QtCore.QRect) -> None:
        painter.save()
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor(0, 0, 0, int(255 * HudStyle.BAR_OPACITY)))
        painter.drawRoundedRect(rect, 18, 18)
        painter.restore()

        session = self.state.session or {}
        posture = self.state.posture or {}
        biometrics = self.state.biometrics or {}

        font_main = QtGui.QFont(HudStyle.FONT_FAMILY, max(20, int(rect.height() * 0.44)))
        font_chip = QtGui.QFont(HudStyle.FONT_FAMILY, max(14, int(rect.height() * 0.32)))

        # Left: session status + duration
        status = (session.get("status") or "idle").title()
        duration_total = _fmt_duration(session.get("duration_sec"))
        left_text = f"Sesión: {status} • {duration_total}"

        painter.setFont(font_main)
        painter.setPen(HudStyle.text_primary())
        left_rect = QtCore.QRect(
            rect.x() + int(rect.width() * 0.02),
            rect.y(),
            int(rect.width() * 0.3),
            rect.height(),
        )
        painter.drawText(left_rect, QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, left_text)

        # Center: exercise summary
        exercise = posture.get("exercise") or session.get("exercise") or "--"
        reps = posture.get("rep_count", 0)
        phase = posture.get("phase_label") or posture.get("phase") or "--"
        center_text = f"Ejercicio: {exercise} • reps: {reps} • fase: {phase}"
        center_rect = QtCore.QRect(
            rect.x(),
            rect.y(),
            rect.width(),
            rect.height(),
        )
        painter.drawText(center_rect, QtCore.Qt.AlignCenter, center_text)

        # Right: biometrics + Fitbit status
        hr = biometrics.get("heart_rate_bpm")
        steps = biometrics.get("steps")
        status_level = biometrics.get("fitbit_status_level", "yellow")
        status_icon = biometrics.get("fitbit_status_icon") or "●"
        chip_padding = 14
        chip_height = max(28, int(rect.height() * 0.6))

        painter.setFont(font_chip)
        x_cursor = rect.right() - chip_padding
        if steps is not None:
            chip_text = f"Pasos: {steps}"
            x_cursor = self._draw_chip(
                painter,
                chip_text,
                x_cursor,
                rect,
                chip_height,
                HudStyle.text_primary(),
            )
        if hr is not None:
            chip_text = f"FC: {hr} bpm"
            x_cursor = self._draw_chip(
                painter,
                chip_text,
                x_cursor,
                rect,
                chip_height,
                HudStyle.text_primary(),
            )
        fitbit_chip = f"{status_icon} Fitbit {status_level}"
        fitbit_color = HudStyle.fitbit_color(status_level)
        fitbit_color.setAlpha(int(255 * HudStyle.CHIP_OPACITY))
        x_cursor = self._draw_chip(
            painter,
            fitbit_chip,
            x_cursor,
            rect,
            chip_height,
            HudStyle.text_primary(),
            bg_color=fitbit_color,
        )

    def _draw_bottom_bar(self, painter: QtGui.QPainter, rect: QtCore.QRect) -> None:
        painter.save()
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor(0, 0, 0, int(255 * HudStyle.BAR_OPACITY)))
        painter.drawRoundedRect(rect, 16, 16)
        painter.restore()

        session = self.state.session or {}
        active = session.get("duration_active_sec")
        left_text = f"Tiempo activo: {_fmt_duration(active)}"

        font_main = QtGui.QFont(HudStyle.FONT_FAMILY, max(20, int(rect.height() * 0.45)))
        painter.setFont(font_main)
        painter.setPen(HudStyle.text_primary())
        painter.drawText(
            QtCore.QRect(rect.x() + 20, rect.y(), rect.width() // 2, rect.height()),
            QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft,
            left_text,
        )

        # Toast (if any)
        if self._toast_message:
            chip_height = max(28, int(rect.height() * 0.6))
            self._draw_chip(
                painter,
                self._toast_message,
                rect.right() - 16,
                rect,
                chip_height,
                HudStyle.text_primary(),
            )
        elif self.debug:
            self._draw_debug_metrics(painter, rect)

    def _draw_debug_metrics(self, painter: QtGui.QPainter, rect: QtCore.QRect) -> None:
        if not self.debug or not self._latest_metrics:
            return
        items = []
        fps = self._latest_metrics.get("fps")
        p50 = self._latest_metrics.get("latency_p50")
        p95 = self._latest_metrics.get("latency_p95")
        if fps is not None:
            items.append(f"FPS {fps:.1f}")
        if p50 is not None:
            items.append(f"p50 {p50:.1f} ms")
        if p95 is not None:
            items.append(f"p95 {p95:.1f} ms")
        if not items:
            return

        painter.save()
        painter.setFont(QtGui.QFont(HudStyle.FONT_FAMILY, max(13, int(rect.height() * 0.32))))
        x_cursor = rect.right() - 20
        for text in items:
            x_cursor = self._draw_chip(
                painter,
                text,
                x_cursor,
                rect,
                max(26, int(rect.height() * 0.55)),
                HudStyle.text_primary(),
                bg_color=QtGui.QColor(0, 0, 0, int(255 * HudStyle.CHIP_OPACITY)),
            )
        painter.restore()

    def _draw_chip(
        self,
        painter: QtGui.QPainter,
        text: str,
        x_cursor: int,
        bar_rect: QtCore.QRect,
        height: int,
        text_color: QtGui.QColor,
        *,
        bg_color: Optional[QtGui.QColor] = None,
        padding_x: int = 12,
    ) -> int:
        if not text:
            return x_cursor
        painter.save()
        font_metrics = painter.fontMetrics()
        text_width = font_metrics.horizontalAdvance(text)
        width = text_width + padding_x * 2
        rect = QtCore.QRect(
            x_cursor - width,
            bar_rect.y() + (bar_rect.height() - height) // 2,
            width,
            height,
        )
        bg = bg_color or QtGui.QColor(0, 0, 0, int(255 * HudStyle.CHIP_OPACITY))
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(bg)
        radius = height // 2
        painter.drawRoundedRect(rect, radius, radius)
        painter.setPen(text_color)
        painter.drawText(rect, QtCore.Qt.AlignCenter, text)
        painter.restore()
        return rect.x() - 12

    # ---------------------------- CLI fallback ------------------------------


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
                steps = biometrics.get("steps", "--")
                fitbit_status = biometrics.get("fitbit_status_icon", "O")
                status = session.get("status", "--")
                duration = _fmt_duration(session.get("duration_sec"))
                active = _fmt_duration(session.get("duration_active_sec"))
                command = session.get("last_command", "--")
                exercise = posture.get("exercise") or session.get("exercise") or "--"
                reps_total = posture.get("rep_count", 0)
                reps_current = posture.get("current_exercise_reps", 0)
                feedback = posture.get("feedback", "Sin feedback")
                quality = posture.get("quality")
                fps = posture.get("fps")

                print(
                    f"[Sesion {status}] dur={duration} activo={active} cmd={command} | "
                    f"FC={hr} ({zone}) pasos={steps} {fitbit_status} | "
                    f"{exercise}: total={reps_total} ejercicio={reps_current} calidad={quality} fps={fps} | {feedback}"
                )
            except Exception as exc:
                print(f"HUD error: {exc}")
            await asyncio.sleep(0.2)


class MirrorApp:
    """Qt overlay wrapper."""

    def run(self, base_url: str, *, debug: bool = False) -> None:  # pragma: no cover - GUI only
        if QtWidgets is None:
            print("PyQt5 no esta instalado. Ejecuta en modo CLI con --cli.")
            return
        app = QtWidgets.QApplication([])
        window = OverlayWindow(base_url, debug=debug)
        window.showFullScreen()
        app.exec_()


def main() -> None:
    parser = argparse.ArgumentParser(description="HUD para el TFG Smart Mirror")
    parser.add_argument("--cli", action="store_true", help="Ejecutar en modo CLI")
    parser.add_argument("--overlay", action="store_true", help="Ejecutar overlay PyQt (por defecto)")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="URL base de la API")
    parser.add_argument("--debug", action="store_true", help="Mostrar métricas técnicas en el HUD")
    args = parser.parse_args()

    if args.cli:
        asyncio.run(cli_loop(args.base_url))
    else:
        MirrorApp().run(args.base_url, debug=args.debug)


if __name__ == "__main__":
    main()
*** End Patch
