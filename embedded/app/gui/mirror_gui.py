"""HUD renderer for the smart mirror (overlay + CLI)."""
from __future__ import annotations

import argparse
import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

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
    """Centralised constants for layout and styling."""

    FRAME_SCALE = 0.88
    BAR_OPACITY = 0.50
    CHIP_OPACITY = 0.55
    TOAST_DURATION = 3.0
    ACTIVE_INTERVAL = 6
    IDLE_INTERVAL = 18
    TIMER_INTERVAL_MS = 80  # ~12.5 Hz
    FONT_FAMILY = "Roboto"

    TOP_FONT = 16
    SUB_FONT = 14
    CHIP_FONT = 13
    BOTTOM_FONT = 15

    @staticmethod
    def text_primary(alpha: int = 235) -> QtGui.QColor:
        color = QtGui.QColor(255, 255, 255)
        color.setAlpha(alpha)
        return color

    @staticmethod
    def text_secondary(alpha: int = 200) -> QtGui.QColor:
        color = QtGui.QColor(255, 255, 255)
        color.setAlpha(alpha)
        return color

    @staticmethod
    def fitbit_chip(level: str) -> QtGui.QColor:
        palette = {
            "green": QtGui.QColor("#4CAF50"),
            "yellow": QtGui.QColor("#FFC107"),
            "red": QtGui.QColor("#F44336"),
        }
        return palette.get(level, QtGui.QColor("#607D8B"))


class OverlayWindow(QtWidgets.QWidget):  # type: ignore
    """Qt overlay window that renders the camera frame and HUD layers."""

    def __init__(self, base_url: str, *, debug: bool = False):
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self.debug = debug
        self.state = HudState({}, {}, {})
        self.last_error: Optional[str] = None
        self.frame_pixmap: Optional[QtGui.QPixmap] = None
        self._client = requests.Session() if requests else None
        self._tick = 0
        self._session_interval = HudStyle.ACTIVE_INTERVAL
        self._poll_lock = False
        self._toast_message: Optional[str] = None
        self._toast_until = 0.0
        self._last_feedback_code: Optional[str] = None
        self._latest_metrics: Dict[str, Any] = {}
        self._current_feedback: str = "--"
        self._session_summary: Optional[Dict[str, Any]] = None
        self._last_voice_seq: int = 0

        self.setWindowTitle("TFG Smart Mirror HUD")
        self.setCursor(QtCore.Qt.BlankCursor)
        self.setMinimumSize(720, 1280)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(HudStyle.TIMER_INTERVAL_MS)

    # ---------------------------------------------------------------- paint --

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

        portrait = self.height() >= self.width()
        margin = max(18, int(min(self.width(), self.height()) * 0.035))
        bar_width = int(self.width() * HudStyle.FRAME_SCALE)
        bar_x = (self.width() - bar_width) // 2
        top_height = max(160 if portrait else 120, int(self.height() * (0.20 if portrait else 0.14)))
        bottom_height = max(80, int(self.height() * 0.09))

        top_rect = QtCore.QRect(bar_x, margin, bar_width, top_height)
        bottom_rect = QtCore.QRect(
            bar_x,
            self.height() - margin - bottom_height,
            bar_width,
            bottom_height,
        )

        self._draw_top_panel(painter, top_rect, portrait=portrait)
        self._draw_bottom_panel(painter, bottom_rect)

        if self._session_summary:
            self._draw_session_summary(painter)

        if self._toast_message:
            self._draw_toast(painter, bottom_rect)

    # --------------------------------------------------------------- polling --

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
            resp = self._client.get(f"{self.base_url}/session/status", timeout=1.2)
            if resp.ok:
                session_data = resp.json().get("data", {}) or {}
                self.state.session = session_data
                session_requires_start = bool(session_data.get("requires_voice_start"))
                summary = session_data.get("session_summary")
                if summary:
                    self._session_summary = summary
                elif session_data.get("status") in {"active", "paused"}:
                    self._session_summary = None
                if session_requires_start and not self._toast_message and not self._session_summary:
                    self._toast_message = "Di \"Iniciar sesion\" para comenzar"
                    self._toast_until = time.time() + HudStyle.TOAST_DURATION
                    self._last_feedback_code = "voice_requires_start"
                voice_event = session_data.get("voice_event") or {}
                try:
                    seq = int(voice_event.get("seq", 0) or 0)
                except Exception:
                    seq = 0
                if seq and seq > self._last_voice_seq:
                    message = voice_event.get("message")
                    if message:
                        self._toast_message = str(message)
                        self._toast_until = time.time() + HudStyle.TOAST_DURATION
                        self._last_feedback_code = "voice_event"
                    self._last_voice_seq = seq
        except Exception as exc:  # pragma: no cover
            self.last_error = f"session: {exc}"
        try:
            resp = self._client.get(f"{self.base_url}/biometrics/last", timeout=1.2)
            if resp.ok:
                self.state.biometrics = resp.json().get("data", {})
        except Exception as exc:  # pragma: no cover
            self.last_error = f"biometrics: {exc}"
        status = (self.state.session or {}).get("status", "idle")
        self._session_interval = HudStyle.ACTIVE_INTERVAL if status == "active" else HudStyle.IDLE_INTERVAL

    def _fetch_posture(self) -> None:
        if not self._client:
            return
        try:
            resp = self._client.post(f"{self.base_url}/posture", json={}, timeout=1.2)
            if resp.ok:
                posture = resp.json().get("data", {})
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
        feedback = (posture.get("feedback") or "").strip()
        code = posture.get("feedback_code") or ""
        if feedback:
            self._current_feedback = feedback
        if not feedback:
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

    # -------------------------------------------------------------- draw top --

    def _draw_panel(self, painter: QtGui.QPainter, rect: QtCore.QRect, radius: int) -> None:
        painter.save()
        bg = QtGui.QColor(0, 0, 0)
        bg.setAlpha(int(255 * HudStyle.BAR_OPACITY))
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, radius, radius)
        painter.restore()

    def _draw_top_panel(self, painter: QtGui.QPainter, rect: QtCore.QRect, *, portrait: bool) -> None:
        self._draw_panel(painter, rect, radius=18)
        session = self.state.session or {}
        posture = self.state.posture or {}

        status = (session.get("status") or "idle").title()
        duration = _fmt_duration(session.get("duration_sec"))
        exercise = posture.get("exercise") or session.get("exercise") or "--"
        reps = posture.get("rep_count", 0)
        phase = posture.get("phase_label") or posture.get("phase") or "--"

        font_title = QtGui.QFont(HudStyle.FONT_FAMILY, HudStyle.TOP_FONT)
        font_body = QtGui.QFont(HudStyle.FONT_FAMILY, HudStyle.SUB_FONT)

        painter.setFont(font_title)
        painter.setPen(HudStyle.text_primary())
        title_rect = QtCore.QRect(rect.x() + 16, rect.y() + 12, rect.width() - 32, font_title.pointSize() + 8)
        painter.drawText(
            title_rect,
            QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
            f"Sesión: {status} • {duration}",
        )

        painter.setFont(font_body)
        metrics = painter.fontMetrics()
        y_cursor = title_rect.bottom() + 8
        lines = [
            f"Ejercicio: {exercise}",
            f"Reps: {reps} • Fase: {phase}",
        ]
        for line in lines:
            line_rect = QtCore.QRect(rect.x() + 16, y_cursor, rect.width() - 32, metrics.height())
            painter.drawText(line_rect, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, metrics.elidedText(line, QtCore.Qt.ElideRight, line_rect.width()))
            y_cursor += metrics.height() + 4

    # --------------------------------------------------------------- draw bottom

    def _build_biometrics(self) -> Tuple[str, str, Tuple[str, QtGui.QColor]]:
        biometrics = self.state.biometrics or {}
        hr = biometrics.get("heart_rate_bpm")
        steps = biometrics.get("steps")
        hr_line = f"Frecuencia cardiaca: {hr} bpm" if hr is not None else "Frecuencia cardiaca: --"
        steps_line = f"Pasos: {steps}" if steps is not None else "Pasos: --"
        level = biometrics.get("fitbit_status_level", "yellow")
        icon = biometrics.get("fitbit_status_icon") or "[?]"
        chip_color = HudStyle.fitbit_chip(level)
        chip_color.setAlpha(int(255 * HudStyle.CHIP_OPACITY))
        chip = (f"{icon} Fitbit {level}", chip_color)
        return hr_line, steps_line, chip

    def _draw_bottom_panel(self, painter: QtGui.QPainter, rect: QtCore.QRect) -> None:
        self._draw_panel(painter, rect, radius=14)
        session = self.state.session or {}
        status = (session.get("status") or "idle").lower()
        active_duration = session.get("duration_active_sec")
        time_text = f"Tiempo activo: {_fmt_duration(active_duration)}" if status == "active" else "Sesión inactiva"

        font_left = QtGui.QFont(HudStyle.FONT_FAMILY, HudStyle.BOTTOM_FONT)
        painter.setFont(font_left)
        metrics_left = painter.fontMetrics()
        left_rect = QtCore.QRect(rect.x() + 18, rect.y(), rect.width() // 3, rect.height())
        painter.setPen(HudStyle.text_primary())
        painter.drawText(left_rect, QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, metrics_left.elidedText(time_text, QtCore.Qt.ElideRight, left_rect.width()))

        font_info = QtGui.QFont(HudStyle.FONT_FAMILY, HudStyle.SUB_FONT)
        painter.setFont(font_info)
        metrics_info = painter.fontMetrics()
        hr_line, steps_line, chip = self._build_biometrics()
        info_rect = QtCore.QRect(rect.x() + rect.width() // 3 + 8, rect.y(), rect.width() // 3, rect.height())
        painter.drawText(
            info_rect,
            QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
            metrics_info.elidedText(hr_line, QtCore.Qt.ElideRight, info_rect.width()),
        )
        painter.drawText(
            info_rect,
            QtCore.Qt.AlignLeft | QtCore.Qt.AlignBottom,
            metrics_info.elidedText(steps_line, QtCore.Qt.ElideRight, info_rect.width()),
        )

        chip_width = metrics_info.horizontalAdvance(chip[0]) + 26
        chip_height = max(26, int(rect.height() * 0.55))
        chip_rect = QtCore.QRect(rect.right() - chip_width - 18, rect.y() + (rect.height() - chip_height) // 2, chip_width, chip_height)
        self._draw_chip_box(painter, chip_rect, chip[0], chip[1])

        if self.debug and status == "active":
            self._draw_debug_metrics(painter, rect)

    def _draw_debug_metrics(self, painter: QtGui.QPainter, rect: QtCore.QRect) -> None:
        if not self.debug or not self._latest_metrics:
            return
        items: List[Tuple[str, Optional[QtGui.QColor]]] = []
        fps = self._latest_metrics.get("fps")
        p50 = self._latest_metrics.get("latency_p50")
        p95 = self._latest_metrics.get("latency_p95")
        if fps is not None:
            items.append((f"FPS {fps:.1f}", None))
        if p50 is not None:
            items.append((f"p50 {p50:.1f} ms", None))
        if p95 is not None:
            items.append((f"p95 {p95:.1f} ms", None))
        if not items:
            return
        painter.save()
        font = QtGui.QFont(HudStyle.FONT_FAMILY, 12)
        painter.setFont(font)
        self._draw_chip_row(painter, items, QtCore.QRect(rect.x(), rect.y(), rect.width(), rect.height()), align_right=True, padding_x=8)
        painter.restore()

    def _draw_session_summary(self, painter: QtGui.QPainter) -> None:
        summary = self._session_summary or {}
        lines: List[str] = ["Resumen de la sesion"]
        duration = summary.get("duration_sec")
        if isinstance(duration, int):
            lines.append(f"Duracion: {_fmt_duration(duration)}")
        active = summary.get("duration_active_sec")
        if isinstance(active, int):
            lines.append(f"Activo: {_fmt_duration(active)}")
        total_reps = summary.get("total_reps")
        lines.append(f"Reps totales: {total_reps if isinstance(total_reps, int) else 0}")
        rep_breakdown = summary.get("rep_breakdown") or {}
        for exercise, count in sorted(rep_breakdown.items()):
            label = exercise.replace("_", " ").title()
            lines.append(f"{label}: {count}")
        painter.save()
        font = QtGui.QFont(HudStyle.FONT_FAMILY, HudStyle.SUB_FONT + 1)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        if not lines:
            painter.restore()
            return
        width = max(metrics.horizontalAdvance(line) for line in lines) + 48
        line_height = metrics.height() + 6
        height = line_height * len(lines) + 24
        rect = QtCore.QRect(
            (self.width() - width) // 2,
            (self.height() - height) // 2,
            width,
            height,
        )
        bg = QtGui.QColor(0, 0, 0)
        bg.setAlpha(int(255 * 0.72))
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 18, 18)
        painter.setPen(HudStyle.text_primary())
        y = rect.y() + 18
        for line in lines:
            painter.drawText(QtCore.QRect(rect.x() + 20, y, rect.width() - 40, metrics.height()), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, line)
            y += line_height
        painter.restore()

    def _draw_toast(self, painter: QtGui.QPainter, bottom_rect: QtCore.QRect) -> None:
        if not self._toast_message:
            return
        painter.save()
        font = QtGui.QFont(HudStyle.FONT_FAMILY, 13)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(self._toast_message) + 40
        height = metrics.height() + 14
        rect = QtCore.QRect((self.width() - width) // 2, bottom_rect.top() - height - 12, width, height)
        self._draw_chip_box(painter, rect, self._toast_message, QtGui.QColor(0, 0, 0, int(255 * HudStyle.CHIP_OPACITY)))
        painter.restore()

    # ------------------------------------------------------------- chip utils

    def _draw_chip_row(
        self,
        painter: QtGui.QPainter,
        chips: List[Tuple[str, Optional[QtGui.QColor]]],
        rect: QtCore.QRect,
        *,
        align_right: bool = False,
        padding_x: int = 12,
    ) -> None:
        if not chips:
            return
        metrics = painter.fontMetrics()
        spacing = 8
        chip_height = max(24, int(rect.height() * 0.55))
        if align_right:
            x_cursor = rect.right() - spacing
            for text, color in reversed(chips):
                width = metrics.horizontalAdvance(text) + padding_x * 2
                x_cursor = self._draw_chip(
                    painter,
                    text,
                    x_cursor,
                    rect,
                    chip_height,
                    HudStyle.text_primary(),
                    bg_color=color or QtGui.QColor(0, 0, 0, int(255 * HudStyle.CHIP_OPACITY)),
                    padding_x=padding_x,
                    width_override=width,
                )
                x_cursor -= spacing
        else:
            x_cursor = rect.x() + spacing
            for text, color in chips:
                width = metrics.horizontalAdvance(text) + padding_x * 2
                chip_rect = QtCore.QRect(x_cursor, rect.y() + (rect.height() - chip_height) // 2, width, chip_height)
                self._draw_chip_box(
                    painter,
                    chip_rect,
                    text,
                    color or QtGui.QColor(0, 0, 0, int(255 * HudStyle.CHIP_OPACITY)),
                )
                x_cursor += width + spacing

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
        painter.save()
        metrics = painter.fontMetrics()
        width = width_override or metrics.horizontalAdvance(text) + padding_x * 2
        rect = QtCore.QRect(
            x_cursor - width,
            bar_rect.y() + (bar_rect.height() - height) // 2,
            width,
            height,
        )
        self._draw_chip_box(
            painter,
            rect,
            text,
            bg_color or QtGui.QColor(0, 0, 0, int(255 * HudStyle.CHIP_OPACITY)),
            text_color=text_color,
        )
        painter.restore()
        return rect.x() - 6

    def _draw_chip_box(
        self,
        painter: QtGui.QPainter,
        rect: QtCore.QRect,
        text: str,
        bg_color: QtGui.QColor,
        *,
        text_color: Optional[QtGui.QColor] = None,
    ) -> None:
        painter.save()
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(bg_color)
        radius = rect.height() // 2
        painter.drawRoundedRect(rect, radius, radius)
        painter.setPen(text_color or HudStyle.text_primary())
        painter.drawText(rect, QtCore.Qt.AlignCenter, text)
        painter.restore()

    # --------------------------------------------------------------- CLI mode


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
                    f"FC={hr} ({zone}) pasos={steps} | "
                    f"{exercise}: total={reps_total} ejercicio={reps_current} calidad={quality} fps={fps} | {feedback}"
                )
            except Exception as exc:
                print(f"HUD error: {exc}")
            await asyncio.sleep(0.2)


class MirrorApp:
    def run(self, base_url: str, *, debug: bool = False) -> None:  # pragma: no cover
        if QtWidgets is None:
            print("PyQt5 no está instalado. Ejecuta en modo CLI con --cli.")
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

