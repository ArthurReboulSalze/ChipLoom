"""The ChipLoom help window: short topic cards with a search box, in the window's language.

`HelpDialog` shows the topics of `help_content` (Getting started, Writing notes, Samples and bank, Tuning, Library or
Synthesized, Working with your agent) plus the key reference of the "?" button (`desktop_layout.SHORTCUTS`), each
with its drawn icon (`desktop_tab_icons`). It is not modal, so the help stays open beside the song. Hooks:
desktop_menus adds "ChipLoom help" (Ctrl+F1; F1-F3 change the octave) to the Help menu and calls `show_help`.
Relies on: window.language, window.palette_colors, window.t.
"""
from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QTextBrowser,
                               QVBoxLayout)

from . import help_content
from .desktop_tab_icons import tab_icon, visible

ICON_COLORS = {"spark": "warning", "keys": "error", "bank": "meter", "wave": "accent", "bubble": "proposal"}


class HelpDialog(QDialog):
    """See the module docstring."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setObjectName("helpDialog")
        self.resize(760, 480)
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setObjectName("helpSearch")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda *_: self.refresh())
        layout.addWidget(self.search)
        body = QHBoxLayout()
        self.topics = QListWidget()
        self.topics.setObjectName("helpTopics")
        self.topics.setMaximumWidth(230)
        self.topics.currentRowChanged.connect(lambda *_: self.show_topic())
        body.addWidget(self.topics)
        self.page = QTextBrowser()
        self.page.setObjectName("helpPage")
        self.page.setOpenExternalLinks(False)
        body.addWidget(self.page, 1)
        layout.addLayout(body, 1)
        self._shown: list[dict] = []
        self.refresh()

    def all_topics(self) -> list[dict]:
        from .desktop_layout import SHORTCUTS
        t = self.window.t
        keys = {"id": "keys", "icon": "keys", "title": t("Keyboard shortcuts"),
                "items": [(t(keys_), t(what)) for keys_, what in SHORTCUTS]}
        query = self.search.text()
        found = help_content.search(query, self.window.language)
        words = [word for word in query.lower().split() if word]
        items = [item for item in keys["items"] if all(word in (item[0] + " " + item[1]).lower() for word in words)]
        if not words or items:
            found.append({**keys, "items": items if words else keys["items"]})
        return found

    def refresh(self):
        t, colors = self.window.t, self.window.palette_colors
        self.setWindowTitle(t("ChipLoom help"))
        self.search.setPlaceholderText(t("Search the help…"))
        wanted = self._shown[self.topics.currentRow()]["id"] if 0 <= self.topics.currentRow() < len(self._shown) else None
        self._shown = self.all_topics()
        self.topics.blockSignals(True)
        self.topics.clear()
        for topic in self._shown:
            color = visible(colors.get(ICON_COLORS.get(topic["icon"], "accent")) or colors["accent"], colors["panel"])
            item = QListWidgetItem(tab_icon(topic["icon"], color), topic["title"])
            self.topics.addItem(item)
        row = next((index for index, topic in enumerate(self._shown) if topic["id"] == wanted), 0)
        self.topics.setCurrentRow(row if self._shown else -1)
        self.topics.blockSignals(False)
        self.show_topic()

    def show_topic(self):
        row = self.topics.currentRow()
        if not 0 <= row < len(self._shown):
            self.page.setHtml(f"<p>{escape(self.window.t('Nothing matches this search.'))}</p>")
            return
        topic, accent = self._shown[row], self.window.palette_colors["accent"]
        rows = "".join(f"<tr><td style='padding:6px 14px 6px 0;vertical-align:top;white-space:nowrap'>"
                       f"<b style='color:{accent}'>{escape(gesture)}</b></td>"
                       f"<td style='padding:6px 0;vertical-align:top'>{escape(text)}</td></tr>"
                       for gesture, text in topic["items"])
        self.page.setHtml(f"<h2>{escape(topic['title'])}</h2><table>{rows}</table>")

    def text(self) -> str:
        """The page's plain text (tests read it)."""
        return self.page.toPlainText()


def show_help(window, topic: str | None = None) -> HelpDialog:
    """Open (or raise) the help window, on `topic` when given."""
    dialog = getattr(window, "help_dialog", None)
    if dialog is None:
        dialog = window.help_dialog = HelpDialog(window)
    dialog.search.clear()
    dialog.refresh()
    if topic is not None:
        ids = [item["id"] for item in dialog._shown]
        if topic in ids:
            dialog.topics.setCurrentRow(ids.index(topic))
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    return dialog


__all__ = ["HelpDialog", "show_help"]
