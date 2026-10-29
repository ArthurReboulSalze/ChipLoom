"""Small shared Qt widgets and helpers for the desktop window."""

from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile

from PySide6.QtCore import Q_ARG, QCoreApplication, QEvent, QMetaObject, QObject, QPointF, QRunnable, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QListWidget, QPushButton, QSizePolicy, QWidget

from .model import Sample
from .themes import icon_colors


def media_call(player, method: str, *args):
    """Call a QMediaPlayer slot through the event loop, so the GIL is released while Qt runs it.

    `stop()` and `setSource()` make Qt's FFmpeg backend wait for its audio thread, which is then
    destroying a renderer connected to our QAudioOutput. That object is a Python wrapper, so the
    thread needs the GIL to read its meta-object; a direct call holds the GIL during the wait and
    both threads stall for good (seen in CI on Windows). Queuing the call and delivering it with
    sendPostedEvents, which PySide runs without the GIL, keeps the call synchronous.
    """
    QMetaObject.invokeMethod(player, method, Qt.ConnectionType.QueuedConnection, *(Q_ARG(type(arg), arg) for arg in args))
    QCoreApplication.sendPostedEvents(player, QEvent.Type.MetaCall)

ASSETS = Path(__file__).resolve().parent / "assets"
# Said on every control that edits MOD samples (loop, trim, gain, fades, library, recipes, instruments) when the open
# module is an XM: the core refuses those operations there (patch.MOD_ONLY_OPERATIONS).
XM_REFUSED_TIP = "This edits 8-bit MOD samples and is not available on an XM module."


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


def _glyph(kind: str, color: str, size: int) -> QImage:
    """A check mark or a chevron, drawn with round strokes on a transparent square."""
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), size * (0.15 if kind == "check" else 0.14))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    points = {"check": ((.22, .52), (.43, .72), (.78, .30)), "down": ((.20, .36), (.50, .66), (.80, .36)),
              "up": ((.20, .64), (.50, .34), (.80, .64))}[kind]
    painter.drawPolyline([QPointF(x * size, y * size) for x, y in points])
    painter.end()
    return image


def ui_icons(theme: str) -> dict[str, str]:
    """The glyphs the stylesheet shows as images (check mark, combo and spin box chevrons) for a theme.

    Written once as small PNGs (plus a @2x copy for high-density screens) in a folder named after the colours they
    use, so a changed palette never meets a stale file. Returns {} when the folder cannot be written: the stylesheet
    then falls back to plain indicators."""
    colors = icon_colors(theme)
    folder = Path(tempfile.gettempdir()) / "chiploom-ui" / (theme + "-" + hashlib.sha1(
        repr(sorted(colors.items())).encode()).hexdigest()[:10])
    wanted = {"check": ("check", colors["check"]), "up": ("up", colors["chevron"]), "down": ("down", colors["chevron"]),
              "up_off": ("up", colors["chevron_off"]), "down_off": ("down", colors["chevron_off"])}
    try:
        folder.mkdir(parents=True, exist_ok=True)
        for name, (kind, color) in wanted.items():
            for suffix, size in (("", 14), ("@2x", 28)):
                target = folder / f"{name}{suffix}.png"
                if not target.is_file() and not _glyph(kind, color, size).save(str(target), "PNG"):
                    return {}
    except OSError:
        return {}
    return {name: str(folder / f"{name}.png") for name in wanted}


class ElidedLabel(QLabel):
    """A one-line label that shortens its text with an ellipsis instead of widening its row; the full text stays
    in `text()` and in the tooltip."""

    def __init__(self, text: str = "", name: str = ""):
        super().__init__(text)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        if name:
            self.setObjectName(name)

    def minimumSizeHint(self):
        return QSize(0, super().minimumSizeHint().height())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        shown = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, self.width())
        painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), shown)


class HintList(QListWidget):
    """A list that says, in muted text inside its own box, what will appear in it while it is empty, so an empty
    column of the window never looks like a field to type in."""

    def __init__(self):
        super().__init__()
        self._hint = ""

    def set_hint(self, text: str) -> None:
        self._hint = text
        self.viewport().update()

    def hint(self) -> str:
        return self._hint

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.count() or not self._hint:
            return
        painter = QPainter(self.viewport())
        color = self.palette().color(self.foregroundRole())
        color.setAlpha(140)
        painter.setPen(color)
        area = self.viewport().rect().adjusted(10, 8, -10, -8)
        painter.drawText(area, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap),
                         self._hint)


def separator() -> QFrame:
    """A thin vertical rule between two groups of buttons."""
    rule = QFrame()
    rule.setObjectName("separator")
    rule.setFixedHeight(22)
    return rule


class ShortcutPopup(QFrame):
    """The key reference of the pattern grid: keys on the left, what they do on the right, one row per habit.

    `rows` is a list of (keys, description) where the description is a translatable source string."""

    def __init__(self, window, rows):
        super().__init__(window, Qt.WindowType.Popup)
        self.window, self.rows = window, rows
        self.setObjectName("shortcutPopup")
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(16, 12, 16, 12)
        self.grid.setHorizontalSpacing(16)
        self.grid.setVerticalSpacing(6)
        self.build()

    def build(self):
        while self.grid.count():
            self.grid.takeAt(0).widget().deleteLater()
        for index, (keys, text) in enumerate(self.rows):
            key = label(self.window.t(keys), "shortcutKeys")
            self.grid.addWidget(key, index, 0, Qt.AlignmentFlag.AlignTop)
            description = label(self.window.t(text), "muted")
            description.setWordWrap(True)
            description.setMinimumWidth(300)
            self.grid.addWidget(description, index, 1)

    def show_under(self, anchor: QWidget):
        self.build()
        self.adjustSize()
        spot = anchor.mapToGlobal(anchor.rect().bottomRight())
        self.move(spot.x() - self.width(), spot.y() - self.height() - anchor.height() - 4)
        self.show()


def label(text: str, name: str = "") -> QLabel:
    result = QLabel(text)
    result.setTextFormat(Qt.TextFormat.PlainText)
    if name:
        result.setObjectName(name)
    return result


def button(text: str, callback, name: str = "") -> QPushButton:
    result = QPushButton(text)
    result.setFocusPolicy(Qt.FocusPolicy.TabFocus)   # a mouse click keeps the keyboard in the grid; Tab still reaches it
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
        peak = 32768 if self.sample.bits == 16 else 128
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
            y = rectangle.center().y() - value * rectangle.height() * 0.46 / peak
            path.moveTo(x, y) if index == 0 else path.lineTo(x, y)
        painter.drawPath(path)
