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
    FRAME_SCALE = 0.9
    BAR_OPACITY = 0.5
    CHIP_OPACITY = 0.55
    TOAST_DURATION = 3.0
    ACTIVE_INTERVAL = 6
    IDLE_INTERVAL = 18
    TIMER_INTERVAL_MS = 80  # ~12.5 Hz
    FONT_FAMILY = "Roboto"

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
    """Overlay window that renders the camera frame and HUD layers."""

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
        self._current_feedback: str = ""

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
        margin = max(20, int(min(self.width(), self.height()) * 0.035))
        bar_width = int(self.width() * HudStyle.FRAME_SCALE)
        bar_x = (self.width() - bar_width) // 2
        top_height = max(180 if portrait else 130, int(self.height() * (0.22 if portrait else 0.16)))
        bottom_height = max(70, int(self.height() * 0.08))

        top_rect = QtCore.QRect(bar_x, margin, bar_width, top_height)
        bottom_rect = QtCore.QRect(
            bar_x,
            self.height() - margin - bottom_height,
            bar_width,
            bottom_height,
        )

        self._draw_top_panel(painter, top_rect, portrait=portrait)

        status = (self.state.session or {}).get("status", "idle")
        if status == "active":
            self._draw_bottom_panel(painter, bottom_rect)
        else:
            self._draw_bottom_idle(painter, bottom_rect)

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
                self.state.session = resp.json().get("data", {})
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

    def _draw_panel(self, painter: QtGui.QPainter, rect: QtCore.QRect, radius: int = 16) -> None:
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
        feedback = self._current_feedback or "--"

        base = int(rect.height() * (0.12 if portrait else 0.15))
        font_line = QtGui.QFont(HudStyle.FONT_FAMILY, max(14, base))
        painter.setFont(font_line)
        metrics = painter.fontMetrics()
        spacing = max(4, int(metrics.height() * 0.25))

        lines = [
            f"Sesión: {status} • {duration}",
            f"Ejercicio: {exercise}",
            f"Reps: {reps} • Fase: {phase}",
            f"Feedback: {feedback}",
        ]

        max_width = rect.width() - 32
        y = rect.y() + 16 + metrics.ascent()
        painter.setPen(HudStyle.text_primary())
        for line in lines:
            painter.drawText(
                QtCore.QRect(rect.x() + 16, y - metrics.ascent(), max_width, metrics.height()),
                QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop,
                metrics.elidedText(line, QtCore.Qt.ElideRight, max_width),
            )
            y += metrics.height() + spacing
            if y > rect.bottom() - 60:
                break

    # ----------------------------------------------------- draw bottom active

    def _build_biometrics_data(self, biometrics: Dict[str, Any]) -> Tuple[str, str, Tuple[str, QtGui.QColor]]:
        hr = biometrics.get("heart_rate_bpm")
        steps = biometrics.get("steps")
        hr_line = f"Frecuencia cardiaca: {hr} bpm" if hr is not None else "Frecuencia cardiaca: --"
        steps_line = f"Pasos: {steps}" if steps is not None else "Pasos: --"
        level = biometrics.get("fitbit_status_level", "yellow")
        icon = biometrics.get("fitbit_status_icon") or "●"
        chip_color = HudStyle.fitbit_chip(level)
        chip_color.setAlpha(int(255 * HudStyle.CHIP_OPACITY))
        chip = (f"{icon} Fitbit {level}", chip_color)
        return hr_line, steps_line, chip

    def _draw_bottom_panel(self, painter: QtGui.QPainter, rect: QtCore.QRect) -> None:
        self._draw_panel(painter, rect, radius=14)
        session = self.state.session or {}
        biometrics = self.state.biometrics or {}

        active = session.get("duration_active_sec")
        left_text = f"Tiempo activo: {_fmt_duration(active)}"

        font_time = QtGui.QFont(HudStyle.FONT_FAMILY, max(16, int(rect.height() * 0.35)))
        painter.setFont(font_time)
        metrics = painter.fontMetrics()
        painter.setPen(HudStyle.text_primary())
        painter.drawText(
            QtCore.QRect(rect.x() + 18, rect.y(), rect.width() // 3, rect.height()),
            QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
            metrics.elidedText(left_text, QtCore.Qt.ElideRight, rect.width() // 3),
        )

        hr_line, steps_line, chip = self._build_biometrics_data(biometrics)
        font_info = QtGui.QFont(HudStyle.FONT_FAMILY, max(14, int(rect.height() * 0.3)))
        painter.setFont(font_info)
        info_rect = QtCore.QRect(rect.x() + rect.width() // 3 + 12, rect.y(), rect.width() // 3, rect.height())
        info_metrics = painter.fontMetrics()
        painter.drawText(info_rect, QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, info_metrics.elidedText(hr_line, QtCore.Qt.ElideRight, info_rect.width()))
        painter.drawText(info_rect, QtCore.Qt.AlignBottom | QtCore.Qt.AlignLeft, info_metrics.elidedText(steps_line, QtCore.Qt.ElideRight, info_rect.width()))

        painter.setFont(font_info)
        chip_rect = QtCore.QRect(rect.right() - (info_metrics.horizontalAdvance(chip[0]) + 28), rect.y() + (rect.height() - max(26, int(rect.height() * 0.55))) // 2, info_metrics.horizontalAdvance(chip[0]) + 28, max(26, int(rect.height() * 0.55)))
        self._draw_chip_box(painter, chip_rect, chip[0], chip[1])

        if self.debug:
            self._draw_debug_metrics(painter, rect)

    def _draw_bottom_idle(self, painter: QtGui.QPainter, rect: QtCore.QRect) -> None:
        self._draw_panel(painter, rect, radius=14)
        biometrics = self.state.biometrics or {}
        hr_line, steps_line, chip = self._build_biometrics_data(biometrics)

        font_info = QtGui.QFont(HudStyle.FONT_FAMILY, max(16, int(rect.height() * 0.32)))
        painter.setFont(font_info)
        metrics = painter.fontMetrics()

        painter.setPen(HudStyle.text_primary())
        painter.drawText(
            QtCore.QRect(rect.x() + 18, rect.y(), rect.width() // 2, rect.height()),
            QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
            metrics.elidedText(hr_line, QtCore.Qt.ElideRight, rect.width() // 2),
        )
        painter.drawText(
            QtCore.QRect(rect.x() + 18, rect.y(), rect.width() // 2, rect.height()),
            QtCore.Qt.AlignLeft | QtCore.Qt.AlignBottom,
            metrics.elidedText(steps_line, QtCore.Qt.ElideRight, rect.width() // 2),
        )

        chip_rect = QtCore.QRect(rect.right() - (metrics.horizontalAdvance(chip[0]) + 28), rect.y() + (rect.height() - max(26, int(rect.height() * 0.55))) // 2, metrics.horizontalAdvance(chip[0]) + 28, max(26, int(rect.height() * 0.55)))
        self._draw_chip_box(painter, chip_rect, chip[0], chip[1])

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
        font = QtGui.QFont(HudStyle.FONT_FAMILY, max(11, int(rect.height() * 0.28)))
        painter.setFont(font)
        self._draw_chip_row(painter, items, rect, align_right=True, padding_x=8)
        painter.restore()

    def _draw_toast(self, painter: QtGui.QPainter, rect: QtCore.QRect) -> None:
        if not self._toast_message:
            return
        font = QtGui.QFont(HudStyle.FONT_FAMILY, max(13, int(rect.height() * 0.3)))
        painter.setFont(font)
        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(self._toast_message) + 40
        chip_rect = QtCore.QRect((self.width() - width) // 2, rect.top() - metrics.height() - 12, width, max(26, int(rect.height() * 0.45)))
        color = QtGui.QColor(0, 0, 0, int(255 * HudStyle.CHIP_OPACITY))
        self._draw_chip_box(painter, chip_rect, self._toast_message, color)

    # --------------------------------------------------------- chip utilities

    def _draw_chip_row(
        self,
        painter: QtGui.QQuantify":[,]]
