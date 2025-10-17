"""HUD renderer for the smart mirror (overlay + CLI)."""
from __future__ import annotations

import argparse
import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

try:
    from PyQt5 import QtCore, QtGui, QtWidgets  # type: ignore
except Exception:  # pragma: no cover
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
    FRAME_SCALE = 0.9
    BAR_OPACITY = 0.5
    CHIP_OPACITY = 0.52
    TOAST_DURATION = 3.0
    ACTIVE_INTERVAL = 6
    IDLE_INTERVAL = 16
    TIMER_INTERVAL_MS = 80
    FONT_FAMILY = "Roboto"

    @staticmethod
    def text_primary(alpha: int = 230) -> QtGui.QColor:
        color = QtGui.QColor(255, 255, 255)
        color.setAlpha(alpha)
        return color

    @staticmethod
    def fitbit_color(level: str) -> QtGui.QColor:
        palette = {
            "green": QtGui.QColor("#4CAF50"),
            "yellow": QtGui.QColor("#FFC107"),
            "red": QtGui.QColor("#F44336"),
        }
        return QtGui.QColor(palette.get(level, QtGui.QColor("#607D8B")))


class OverlayWindow(QtWidgets.QWidget):  # type: ignore
    def __init__(self, base_url: str, *, debug: bool = False):
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self.debug = debug
        self.state = HudState({}, {}, {})
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
        self.timer.start(HudStyle.TIMER_INTERVAL_MS)

    # ---------------------------- paint helpers ---------------------------

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

        margin = max(18, int(min(self.width(), self.height()) * 0.04))
        bar_width = int(self.width() * HudStyle.FRAME_SCALE)
        bar_x = (self.width() - bar_width) // 2
        top_height = max(48, int(self.height() * 0.055))
        bottom_height = max(48, int(self.height() * 0.055))

        top_rect = QtCore.QRect(bar_x, margin, bar_width, top_height)
        bottom_rect = QtCore.QRect(
            bar_x,
            self.height() - margin - bottom_height,
            bar_width,
            bottom_height,
        )

        self._draw_top_bar(painter, top_rect)
        status = (self.state.session or {}).get("status", "idle")
        if status == "active":
            self._draw_bottom_bar(painter, bottom_rect)
        elif self.debug:
            self._draw_debug_metrics(painter, bottom_rect)

    # ----------------------------- polling --------------------------------

    def poll(self) -> None:
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
            response = self._client.get(f"{self.base_url}/session/status", timeout=1.2)
            if response.ok:
                self.state.session = response.json().get("data", {})
        except Exception as exc:  # pragma: no cover
            self.last_error = f"session: {exc}"
        try:
            response = self._client.get(f"{self.base_url}/biometrics/last", timeout=1.2)
            if response.ok:
                self.state.biometrics = response.json().get("data", {})
        except Exception as exc:  # pragma: no cover
            self.last_error = f"biometrics: {exc}"

        status = (self.state.session or {}).get("status", "idle")
        self._session_interval = HudStyle.ACTIVE_INTERVAL if status == "active" else HudStyle.IDLE_INTERVAL

    def _fetch_posture(self) -> None:
        if not self._client:
            return
        try:
            response = self._client.post(f"{self.base_url}/posture", json={}, timeout=1.2)
            if response.ok:
                posture = response.json().get("data", {})
                self.state.posture = posture
                self._latest_metrics = {
                    "fps": posture.get("fps"),
                    "latency_p50": posture.get("latency_ms_p50"),
                    "latency_p95": posture.get("latency_ms_p95"),
                }
                self._update_frame(posture.get("frame_b64"))
                self._handle_feedback(posture)
        except Exception as exc:  # pragma: no cover
            self.last_error = f"posture: {exc}"

    def _update_frame(self, frame_b64: Optional[str]) -> None:
        if not frame_b64:
            self.frame_pixmap = None
            return
        try:
            data = QtCore.QByteArray.fromBase64(frame_b64.encode("utf-8"))
            image = QtGui.QImage.fromData(data, "JPG")
            self.frame_pixmap = None if image.isNull() else QtGui.QPixmap.fromImage(image)
        except Exception as exc:  # pragma: no cover
            self.frame_pixmap = None
            self.last_error = f"frame decode: {exc}"

    def _handle_feedback(self, posture: Dict[str, Any]) -> None:
        feedback = posture.get("feedback")
        code = posture.get("feedback_code")
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

    # ----------------------------- drawing --------------------------------

    def _draw_top_bar(self, painter: QtGui.QPainter, rect: QtCore.QRect) -> None:
        painter.save()
        bg = QtGui.QColor(0, 0, 0)
        bg.setAlpha(int(255 * HudStyle.BAR_OPACITY))
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 16, 16)
        painter.restore()

        session = self.state.session or {}
        posture = self.state.posture or {}
        biometrics = self.state.biometrics or {}

        font_main = QtGui.QFont(HudStyle.FONT_FAMILY, max(18, int(rect.height() * 0.42)))
        font_chip = QtGui.QFont(HudStyle.FONT_FAMILY, max(13, int(rect.height() * 0.32)))

        painter.setFont(font_chip)
        metrics_chip = painter.fontMetrics()
        chip_padding = 12
        spacing = 10

        chips: list[tuple[str, Optional[QtGui.QColor], int]] = []
        steps = biometrics.get("steps")
        if steps is not None:
            text = f"Pasos: {steps}"
            width = metrics_chip.horizontalAdvance(text) + chip_padding * 2
            chips.append((text, None, width))
        hr = biometrics.get("heart_rate_bpm")
        if hr is not None:
            text = f"FC: {hr} bpm"
            width = metrics_chip.horizontalAdvance(text) + chip_padding * 2
            chips.append((text, None, width))
        level = biometrics.get("fitbit_status_level", "yellow")
        icon = biometrics.get("fitbit_status_icon") or "●"
        fitbit_color = HudStyle.fitbit_color(level)
        fitbit_color.setAlpha(int(255 * HudStyle.CHIP_OPACITY))
        text = f"{icon} Fitbit {level}"
        width = metrics_chip.horizontalAdvance(text) + chip_padding * 2
        chips.append((text, fitbit_color, width))

        chips_total = sum(width for _, _, width in chips) + spacing * (len(chips) - 1 if chips else 0)
        available_width = rect.width() - chips_total - spacing * 2

        painter.setFont(font_main)
        metrics_main = painter.fontMetrics()

        left_width = max(90, min(int(rect.width() * 0.32), available_width - 120))
        left_width = min(left_width, rect.width() - chips_total - spacing * 3)
        left_width = max(80, left_width)

        center_left = rect.x() + left_width + spacing
        center_available = rect.width() - left_width - chips_total - spacing * 3
        if center_available < 80:
            deficit = 80 - center_available
            left_width = max(80, left_width - deficit)
            center_left = rect.x() + left_width + spacing
            center_available = rect.width() - left_width - chips_total - spacing * 3
            center_available = max(60, center_available)

        left_rect = QtCore.QRect(rect.x() + spacing, rect.y(), left_width, rect.height())
        status = (session.get("status") or "idle").title()
        duration_total = _fmt_duration(session.get("duration_sec"))
        left_text = f"Sesión: {status} • {duration_total}"
        left_text = metrics_main.elidedText(left_text, QtCore.Qt.ElideRight, left_rect.width())
        painter.setPen(HudStyle.text_primary())
        painter.drawText(left_rect, QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, left_text)

        center_rect = QtCore.QRect(center_left, rect.y(), center_available, rect.height())
        exercise = posture.get("exercise") or session.get("exercise") or "--"
        reps = posture.get("rep_count", 0)
        phase = posture.get("phase_label") or posture.get("phase") or "--"
        center_text = f"Ejercicio: {exercise} • Reps: {reps} • Fase: {phase}"
        center_text = metrics_main.elidedText(center_text, QtCore.Qt.ElideRight, max(40, center_available))
        painter.drawText(center_rect, QtCore.Qt.AlignCenter, center_text)

        painter.setFont(font_chip)
        x_cursor = rect.right() - spacing
        for text, color, width in reversed(chips):
            available = x_cursor - (center_rect.right() + spacing)
            max_text_width = max(30, available - (chip_padding * 2))
            elided = metrics_chip.elidedText(text, QtCore.Qt.ElideRight, max_text_width)
            chip_color = color or QtGui.QColor(0, 0, 0, int(255 * HudStyle.CHIP_OPACITY))
            x_cursor = self._draw_chip(
                painter,
                elided,
                x_cursor,
                rect,
                max(26, int(rect.height() * 0.6)),
                HudStyle.text_primary(),
                bg_color=chip_color,
                padding_x=chip_padding,
                width_override=width,
            )

    def _draw_bottom_bar(self, painter: QtGui.QPainter, rect: QtCore.QRect) -> None:
        painter.save()
        bg = QtGui.QColor(0, 0, 0)
        bg.setAlpha(int(255 * HudStyle.BAR_OPACITY))
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 14, 14)
        painter.restore()

        session = self.state.session or {}
        active = session.get("duration_active_sec")
        left_text = f"Tiempo activo: {_fmt_duration(active)}"

        font_main = QtGui.QFont(HudStyle.FONT_FAMILY, max(18, int(rect.height() * 0.42)))
        painter.setFont(font_main)
        metrics_main = painter.fontMetrics()
        left_rect = QtCore.QRect(rect.x() + 18, rect.y(), rect.width() // 2, rect.height())
        painter.setPen(HudStyle.text_primary())
        painter.drawText(
            left_rect,
            QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
            metrics_main.elidedText(left_text, QtCore.Qt.ElideRight, left_rect.width()),
        )

        if self._toast_message:
            painter.setFont(QtGui.QFont(HudStyle.FONT_FAMILY, max(14, int(rect.height() * 0.32))))
            chip_height = max(26, int(rect.height() * 0.6))
            chip_color = QtGui.QColor(0, 0, 0, int(255 * HudStyle.CHIP_OPACITY))
            self._draw_chip(
                painter,
                self._toast_message,
                rect.right() - 14,
                rect,
                chip_height,
                HudStyle.text_primary(),
                bg_color=chip_color,
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
        font_chip = QtGui.QFont(HudStyle.FONT_FAMILY, max(12, int(rect.height() * 0.3)))
        painter.setFont(font_chip)
        chip_color = QtGui.QColor(0, 0, 0, int(255 * HudStyle.CHIP_OPACITY))
        metrics = painter.fontMetrics()
        spacing = 8
        chip_height = max(24, int(rect.height() * 0.55))
        x_cursor = rect.right() - spacing
        for text in reversed(items):
            width = metrics.horizontalAdvance(text) + 16
            x_cursor = self._draw_chip(
                painter,
                text,
                x_cursor,
                rect,
                chip_height,
                HudStyle.text_primary(),
                bg_color=chip_color,
                padding_x=8,
                width_override=width,
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
        width_override: Optional[int] = None,
    ) -> int:
        if not text:
            return x_cursor
        painter.save()
        metrics = painter.fontMetrics()
        width = width_override or (metrics.horizontalAdvance(text) + padding_x * 2)
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
        return rect.x() - 8

    # ---------------------------- CLI fallback ---------------------------


ASYNC_REFRESH = 0.2


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
                fitbit_status = biometrics.get("fitbit_status_icon", "●")
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
            await asyncio.sleep(ASYNC_REFRESH)


class MirrorApp:
    def run(self, base_url: str, *, debug: bool = False) -> None:  # pragma: no cover
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
