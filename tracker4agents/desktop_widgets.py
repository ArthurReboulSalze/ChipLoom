"""Small shared Qt widgets and helpers for the desktop window."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QLabel, QPushButton, QWidget

from .model import Sample

ASSETS = Path(__file__).resolve().parent / "assets"


def brand_icon() -> QIcon:
    """Use the four-channel emblem from the approved logo, with square padding.

    This is a display crop of the bundled artwork, not a second visual identity.
    Keeping the source inside the package also supports non-editable installs.
    """
    logo = QPixmap(str(ASSETS / "chiploom-logo.png"))
    if logo.isNull():
        return QIcon()
    emblem = logo.copy(100, 160, 520, 410)
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        canvas = QPixmap(size, size)
        canvas.fill(Qt.GlobalColor.transparent)
        scaled = emblem.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
        painter = QPainter(canvas)
        painter.drawPixmap((size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled)
        painter.end()
        icon.addPixmap(canvas)
    return icon


def label(text: str, name: str = "") -> QLabel:
    result = QLabel(text)
    result.setTextFormat(Qt.TextFormat.PlainText)
    if name:
        result.setObjectName(name)
    return result


def button(text: str, callback, name: str = "") -> QPushButton:
    result = QPushButton(text)
    if name:
        result.setObjectName(name)
    result.clicked.connect(callback)
    return result


def clock(milliseconds: int) -> str:
    seconds = max(0, milliseconds) // 1000
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def sample_name(sample: Sample, slot: int) -> str:
    prefix = f"{slot:02X} "
    return sample.name[len(prefix):] if sample.name.startswith(prefix) else sample.name or "Sample"


class TaskSignals(QObject):
    finished = Signal(int, object)
    failed = Signal(int, str)


class Task(QRunnable):
    def __init__(self, token: int, operation):
        super().__init__()
        self.token, self.operation = token, operation
        self.signals = TaskSignals()

    def run(self):
        try:
            self.signals.finished.emit(self.token, self.operation())
        except Exception as exc:
            self.signals.failed.emit(self.token, str(exc))



class Waveform(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.sample: Sample | None = None
        self.setMinimumHeight(130)

    def set_sample(self, sample: Sample | None):
        self.sample = sample
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rectangle = self.rect().adjusted(10, 12, -10, -12)
        colors = self.window.palette_colors
        painter.fillRect(self.rect(), QColor(colors["panel"]))
        painter.setPen(QPen(QColor(colors["border"]), 1))
        painter.drawLine(rectangle.left(), rectangle.center().y(), rectangle.right(), rectangle.center().y())
        if not self.sample or not self.sample.pcm:
            painter.setPen(QColor(colors["muted"]))
            painter.drawText(rectangle, Qt.AlignmentFlag.AlignCenter, self.window.t("Select a sample"))
            return
        data = self.sample.pcm
        if self.sample.loop_length:
            start = rectangle.left() + rectangle.width() * self.sample.loop_start / len(data)
            end = rectangle.left() + rectangle.width() * (self.sample.loop_start + self.sample.loop_length) / len(data)
            painter.fillRect(int(start), rectangle.top(), max(1, int(end - start)), rectangle.height(), QColor(colors["loop"]))
        painter.setPen(QPen(QColor(colors["accent"]), 1.3))
        count = min(len(data), max(2, rectangle.width() * 2))
        path = QPainterPath()
        for index in range(count):
            value = data[min(len(data) - 1, index * len(data) // count)]
            x = rectangle.left() + index * rectangle.width() / max(1, count - 1)
            y = rectangle.center().y() - value * rectangle.height() * 0.46 / 128
            path.moveTo(x, y) if index == 0 else path.lineTo(x, y)
        painter.drawPath(path)
