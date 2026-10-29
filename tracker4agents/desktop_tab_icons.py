"""Small drawn icons for the tabs under the grid, so each tab is recognized at a glance.

`apply_tab_icons(window)` gives every tab of `window.sample_tabs` an icon drawn with QPainter in a colour of the
current theme: a waveform for Song samples, stacked drawers for the Sample library, a spark for Create, piano keys
for Instruments and a speech bubble for Agent. Vector drawings, so they follow the theme and stay sharp at any
scale (16 and 32 px pixmaps). Relies on: window.sample_tabs, window.tab_titles (page -> English title) and
window.palette_colors (theme colours); desktop_layout calls it after building the tabs, desktop_preferences after a
theme change.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

# English tab title -> (drawing, theme colour key)
TAB_ICONS = {"Song samples": ("wave", "accent"), "Sample library": ("bank", "meter"), "Create": ("spark", "warning"),
             "Instruments": ("keys", "error"), "Agent": ("bubble", "proposal")}


def visible(color: str, panel: str) -> QColor:
    """`color`, lightened on a dark panel or darkened on a light one until it stands out (theme colours meant for
    backgrounds, such as the proposal violet, become usable as icon colours)."""
    shade, ground = QColor(color), QColor(panel)
    dark = ground.lightness() < 128
    for _ in range(8):
        if abs(shade.lightness() - ground.lightness()) >= 90:
            break
        shade = shade.lighter(135) if dark else shade.darker(135)
    return shade


def _draw(kind: str, painter: QPainter, size: int, color: QColor) -> None:
    s = size
    pen = QPen(color, max(1.2, s * 0.09))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if kind == "wave":          # one and a half cycles of a sine
        path = QPainterPath(QPointF(0.08 * s, 0.5 * s))
        for step in range(1, 41):
            x = 0.08 + 0.84 * step / 40
            path.lineTo(QPointF(x * s, (0.5 - 0.32 * math.sin(step / 40 * 3 * math.pi)) * s))
        painter.drawPath(path)
    elif kind == "bank":        # three stacked drawers with handles
        for index in range(3):
            top = (0.1 + index * 0.28) * s
            painter.drawRoundedRect(QRectF(0.12 * s, top, 0.76 * s, 0.22 * s), 0.05 * s, 0.05 * s)
            painter.drawLine(QPointF(0.42 * s, top + 0.11 * s), QPointF(0.58 * s, top + 0.11 * s))
    elif kind == "spark":       # a four-pointed spark and a small one
        path = QPainterPath(QPointF(0.42 * s, 0.1 * s))
        for x, y in ((0.52, 0.42), (0.84, 0.52), (0.52, 0.62), (0.42, 0.94), (0.32, 0.62), (0.0 + 0.06, 0.52),
                     (0.32, 0.42), (0.42, 0.1)):
            path.lineTo(QPointF(x * s, y * s))
        painter.setBrush(color)
        painter.drawPath(path)
        painter.drawEllipse(QPointF(0.8 * s, 0.2 * s), 0.06 * s, 0.06 * s)
    elif kind == "keys":        # three white keys and two black ones
        painter.drawRoundedRect(QRectF(0.1 * s, 0.14 * s, 0.8 * s, 0.72 * s), 0.06 * s, 0.06 * s)
        for x in (0.37, 0.63):
            painter.drawLine(QPointF(x * s, 0.5 * s), QPointF(x * s, 0.86 * s))
        painter.setBrush(color)
        for x in (0.3, 0.57):
            painter.drawRect(QRectF(x * s, 0.14 * s, 0.13 * s, 0.38 * s))
    elif kind == "bubble":      # a speech bubble with three dots
        path = QPainterPath()
        path.addRoundedRect(QRectF(0.08 * s, 0.12 * s, 0.84 * s, 0.56 * s), 0.16 * s, 0.16 * s)
        painter.drawPath(path)
        painter.drawPolyline([QPointF(0.3 * s, 0.68 * s), QPointF(0.24 * s, 0.9 * s), QPointF(0.46 * s, 0.68 * s)])
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        for x in (0.32, 0.5, 0.68):
            painter.drawEllipse(QPointF(x * s, 0.4 * s), 0.055 * s, 0.055 * s)


def tab_icon(kind: str, color: QColor) -> QIcon:
    icon = QIcon()
    for size in (16, 32):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        _draw(kind, painter, size, color)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


def apply_tab_icons(window) -> None:
    tabs = window.sample_tabs
    tabs.setIconSize(QSize(16, 16))
    colors = window.palette_colors
    for index in range(tabs.count()):
        title = window.tab_titles.get(tabs.widget(index))
        if title in TAB_ICONS:
            kind, key = TAB_ICONS[title]
            tabs.setTabIcon(index, tab_icon(kind, visible(colors.get(key) or colors["accent"], colors["panel"])))
