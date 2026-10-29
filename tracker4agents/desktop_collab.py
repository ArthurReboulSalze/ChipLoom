"""Live-collaboration glue of the ChipLoom window: what the window does for the live session.

The session itself lives in `desktop_live` (`LiveBridge` as window.live, `AgentPanel` as window.agent_panel) and
the browser dialog in `desktop_browser`. `CollaborationMixin` connects the window's state to the bridge
(`_connect_live`), toggles collaboration (`set_live`), opens the browser dialog (`open_browser`), shows an order or
pattern on request (`show_order`, `show_pattern`), starts playback for an agent (`start_playback`, in
`desktop_transport`), and presents a change made through the session by an agent or a browser (`agent_changed`).
Relies on: window.live, window.state, window.live_action, window.table, window.player, window.loop, window.rt,
window.orders, window.pattern_model, window.order_editor, window.debounce, the audio state flags,
`refresh_document`, `is_playing`, `message` and `_save_preferences`.
"""

from __future__ import annotations

from .desktop_browser import BrowserDialog
from .desktop_live import HUMAN_AUTHORS
from .desktop_widgets import media_call


class CollaborationMixin:
    """The window's side of the live session (see the module docstring)."""
    # --- live collaboration -------------------------------------------------------------
    def _connect_live(self):
        """Report cursor, selection, order, playback and dirty state to the live session (debounced)."""
        self.table.selectionModel().selectionChanged.connect(self.live.context_changed)
        self.table.selectionModel().currentChanged.connect(self.live.context_changed)
        self.player.playbackStateChanged.connect(self.live.context_changed)
        self.loop.toggled.connect(lambda on: self.rt.set_loop(on) if self.rt is not None else None)
        self.live.enabled = type(self.state.values.get("live")) is not bool or self.state.values["live"]
        self.live_action.blockSignals(True)
        self.live_action.setChecked(self.live.enabled)
        self.live_action.blockSignals(False)
        self.live.update_status()

    def open_browser(self):
        """Agent menu, "Open in a browser...": address, LAN switch and connected browsers."""
        if self.browser_dialog is None:
            self.browser_dialog = BrowserDialog(self)
        self.browser_dialog.open()
        return self.browser_dialog

    def set_live(self, enabled: bool):
        self.live.set_enabled(enabled)
        self._save_preferences()

    def show_order(self, order: int):
        """Display an order without seeking the audio (used by agent requests and proposal previews)."""
        self._refreshing = True
        self.orders.setCurrentIndex(order)
        self._refreshing = False
        self.current_order = order
        self.pattern_model.refresh(self.document.module.orders[order])
        self.order_editor.refresh()
        self.live.context_changed()

    def show_pattern(self, pattern: int):
        orders = self.document.module.orders
        if self.pattern_model.pattern == pattern:
            return
        if pattern in orders:
            self.show_order(orders.index(pattern))
        else:
            self.pattern_model.refresh(pattern)

    def _announce_change(self, entry: dict):
        """Status line for someone else's edit: an agent's, or a browser's (named as such)."""
        summary = "; ".join(entry["summary"][:2]) or "—"
        if entry["author"] in HUMAN_AUTHORS:
            self.message("Edit from a browser ({author}): {label} · {summary}", author=entry["author"],
                         label=entry["label"], summary=summary)
        else:
            self.message("{author}: {label} · {summary}", author=entry["author"], label=entry["label"], summary=summary)

    def agent_changed(self, entry: dict):
        """Someone else (an agent, an accepted proposal, a browser) changed the document through the session."""
        kind = "human_change" if entry["author"] in HUMAN_AUTHORS else "agent_change"
        if self.rt is not None:
            media_call(self.sample_player, "stop")
            self.refresh_document()
            self.pattern_model.flash(entry["diff"].get("cells", []), kind)
            self.rt.reload()
            self._announce_change(entry)
            self.live.context_changed()
            return
        playing = self._want_play if self._loading_audio else self.is_playing()
        if not self._loading_audio:
            self._resume_ms = self.player.position()
        self._debounce_play = self._debounce_play or playing
        self._audio_token += 1
        self._loading_audio = self._await_media = self._audio_ready = False
        media_call(self.sample_player, "stop")
        self.refresh_document()
        self.pattern_model.flash(entry["diff"].get("cells", []), kind)
        self.debounce.start()
        self._announce_change(entry)
        self.live.context_changed()
