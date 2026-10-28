"""Stereo RMS/peak display, fed by the real-time engine or by the rendered WAV being played."""

from array import array
import math
import sys
import time
import wave

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
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


class WavLevels:
    """Levels of a rendered 16-bit WAV around a playback position, measured on the GUI thread.

    Qt's QAudioBufferOutput hands decoded audio over from its renderer thread, and a Python
    receiver there deadlocks with QMediaPlayer.stop(): the renderer waits for the GIL while the
    GUI thread, holding it, waits for the renderer. The window plays files it rendered itself,
    so it reads the heard audio from them instead.
    """

    WINDOW = .05   # seconds measured per tick

    def __init__(self):
        self.path, self.pcm, self.channels, self.rate = None, b"", 0, 0

    def at(self, path: str, milliseconds: int):
        if path != self.path:
            self._load(path)
        if not self.rate:
            return None
        width = 2 * self.channels
        start = int(milliseconds * self.rate / 1000) * width
        chunk = self.pcm[start:start + int(self.WINDOW * self.rate) * width]
        return pcm_levels(chunk, self.channels) if chunk else None

    def _load(self, path: str):
        self.path, self.pcm, self.channels, self.rate = path, b"", 0, 0
        try:
            with wave.open(path, "rb") as audio:
                if audio.getsampwidth() != 2 or audio.getnchannels() not in (1, 2):
                    return
                values = array("h", audio.readframes(audio.getnframes()))
                channels, rate = audio.getnchannels(), audio.getframerate()
        except (OSError, EOFError, wave.Error):
            return
        if sys.byteorder != "little":
            values.byteswap()
        self.pcm, self.channels, self.rate = values.tobytes(), channels, rate


class LevelMeter(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setObjectName("levelMeter")
        self.setFixedSize(246, 38)
        self.buffer_count = 0
        self.reset()

    def reset(self):
        self.raw_rms = self.raw_peaks = (0.0, 0.0)
        self.levels = self.peaks = (0.0, 0.0)
        self.received_at = 0.0
        self.update()

    def feed_levels(self, rms, peaks):
        """Levels of the audio being heard, from the real-time engine or the rendered WAV."""
        self.raw_rms, self.raw_peaks = rms, peaks
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

    SEGMENTS = 22

    def paintEvent(self, event):
        p = self.window.palette_colors
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor(p["border"]))
        painter.setBrush(QColor(p["bg"]))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 6, 6)
        painter.setPen(QColor(p["muted"]))
        font = painter.font()
        font.setPixelSize(10)
        painter.setFont(font)
        peak = max(self.peaks)
        text = f"{20 * math.log10(peak):.1f}" if peak > .001 else "−∞"
        painter.drawText(self.width() - 52, 0, 44, self.height(), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                         text + " dB")
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        for channel, y in enumerate((8, 22)):
            painter.setPen(QColor(p["muted"]))
            painter.drawText(8, y - 1, 12, 10, Qt.AlignmentFlag.AlignCenter, ("L", "R")[channel])
            level, peak_fraction = self.fraction(self.levels[channel]), self.fraction(self.peaks[channel])
            for segment in range(self.SEGMENTS):
                threshold = (segment + 1) / self.SEGMENTS
                color = p["border"]
                if threshold <= level:
                    color = p["error"] if threshold > .96 else p["warning"] if threshold > .82 else p["meter"]
                painter.fillRect(24 + segment * 8, y, 6, 8, QColor(color))
            if peak_fraction > 0:
                painter.fillRect(24 + round(peak_fraction * (self.SEGMENTS * 8 - 4)), y - 1, 2, 10, QColor(p["accent"]))
