"""Stereo RMS/peak display, fed by QMediaPlayer's decoded audio buffers."""

from array import array
import math
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtMultimedia import QAudioFormat
from PySide6.QtWidgets import QWidget


def pcm_levels(payload: bytes, channels: int = 2) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Native-endian signed 16-bit PCM, as requested from Qt's buffer output."""
    if not payload or channels not in (1, 2):
        return (0.0, 0.0), (0.0, 0.0)
    values = array("h", payload)
    peaks, rms = [], []
    for channel in range(channels):
        lane = values[channel::channels]
        if not lane:
            return (0.0, 0.0), (0.0, 0.0)
        peaks.append(max(abs(value) for value in lane) / 32768)
        rms.append(math.sqrt(sum(value * value for value in lane) / len(lane)) / 32768)
    if channels == 1:
        peaks *= 2
        rms *= 2
    return tuple(rms), tuple(peaks)


class LevelMeter(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setObjectName("levelMeter")
        self.setFixedSize(235, 54)
        self.buffer_count = 0
        self.reset()

    def reset(self):
        self.raw_rms = self.raw_peaks = (0.0, 0.0)
        self.levels = self.peaks = (0.0, 0.0)
        self.received_at = 0.0
        self.update()

    def feed(self, buffer):
        if buffer.isValid() and buffer.format().sampleFormat() == QAudioFormat.SampleFormat.Int16:
            self.raw_rms, self.raw_peaks = pcm_levels(bytes(buffer.constData()), buffer.format().channelCount())
            self.received_at = time.monotonic()
            self.buffer_count += 1

    def tick(self, active: bool, volume: float):
        live = active and time.monotonic() - self.received_at < .3
        rms = self.raw_rms if live else (0.0, 0.0)
        peaks = self.raw_peaks if live else (0.0, 0.0)
        self.levels = tuple(max(value * volume, old * .78) for value, old in zip(rms, self.levels))
        self.peaks = tuple(max(value * volume, old * .93) for value, old in zip(peaks, self.peaks))
        self.update()

    @staticmethod
    def fraction(value):
        return max(0.0, min(1.0, (20 * math.log10(max(1e-9, value)) + 54) / 54))

    def paintEvent(self, event):
        p = self.window.palette_colors
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(p["panel"]))
        painter.setPen(QColor(p["muted"]))
        font = painter.font()
        font.setPixelSize(10)
        painter.setFont(font)
        painter.drawText(6, 12, self.window.t("LEVEL"))
        peak = max(self.peaks)
        text = f"{20 * math.log10(peak):.1f} dBFS" if peak > .001 else "−∞ dBFS"
        painter.drawText(110, 0, 118, 16, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, text)
        for channel, y in enumerate((21, 38)):
            painter.setPen(QColor(p["muted"]))
            painter.drawText(6, y + 8, ("L", "R")[channel])
            level, peak_fraction = self.fraction(self.levels[channel]), self.fraction(self.peaks[channel])
            for segment in range(26):
                threshold = (segment + 1) / 26
                color = p["border"]
                if threshold <= level:
                    color = p["error"] if threshold > .96 else p["warning"] if threshold > .82 else p["meter"]
                painter.fillRect(22 + segment * 8, y, 6, 9, QColor(color))
            if peak_fraction > 0:
                painter.fillRect(22 + round(peak_fraction * 206), y - 1, 2, 11, QColor(p["accent"]))
