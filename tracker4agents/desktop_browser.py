"""Open the song in a browser: address, local network switch and the list of connected browsers.

The browser studio (`tracker4agents/web`) lets a tablet or another browser listen to the open song and edit it
as `human-web`. There is no code to type: this dialog shows where to point the browser (with Copy and Open),
can open the studio to the private network (plain HTTP, hence the warning) and lists the browsers that joined.
Nothing here holds a token: the live server does.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from .model import ValidationError

REFRESH_MS = 1000


class BrowserDialog(QDialog):
    COLUMNS = ("Device", "Browser", "Network", "Last seen")

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setObjectName("browserDialog")
        self.setModal(False)
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)
        self.heading = window._label("Open in a browser", "section")
        self.heading.setStyleSheet("padding-top:0;font-size:16px")
        layout.addWidget(self.heading)
        self.intro = window._label("Open this address in a browser to listen to this song and edit it with the agent, "
                                   "as \"human-web\". No code is needed. The agent keeps its own access.", "muted")
        self.intro.setWordWrap(True)
        layout.addWidget(self.intro)
        self.unavailable = window._label("", "muted")
        self.unavailable.setWordWrap(True)
        layout.addWidget(self.unavailable)

        address = QHBoxLayout()
        address.addWidget(window._label("Address", "muted"))
        self.url = QLabel()
        self.url.setObjectName("browserUrl")
        self.url.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.url.setTextFormat(Qt.TextFormat.PlainText)
        self.url.setWordWrap(True)
        address.addWidget(self.url, 1)
        self.copy_button = window._button("Copy", self.copy_url, "copyBrowserUrl")
        self.copy_button.setProperty("compact", True)
        address.addWidget(self.copy_button)
        self.open_button = window._button("Open", self.open_url, "openBrowserUrl")
        self.open_button.setProperty("compact", True)
        address.addWidget(self.open_button)
        layout.addLayout(address)

        self.lan = QCheckBox()
        self.lan.setObjectName("allowLan")
        window._bind(self.lan, "Allow devices on my local network", "setText")
        window._bind(self.lan, "Opens the studio (and only the studio) to this computer's private network addresses.",
                     "setToolTip")
        self.lan.toggled.connect(self.set_lan)
        layout.addWidget(self.lan)
        self.warning = QLabel()
        self.warning.setObjectName("browserWarning")
        self.warning.setWordWrap(True)
        self.warning.setTextFormat(Qt.TextFormat.PlainText)
        self.warning.setProperty("error", True)
        layout.addWidget(self.warning)

        layout.addWidget(window._label("CONNECTED BROWSERS", "section"))
        self.devices_table = QTableWidget(0, len(self.COLUMNS))
        self.devices_table.setObjectName("connectedBrowsers")
        self.devices_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.devices_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.devices_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.devices_table.verticalHeader().hide()
        self.devices_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.devices_table.setMinimumHeight(110)
        layout.addWidget(self.devices_table, 1)
        self.empty = window._label("No browser is connected yet.", "muted")
        layout.addWidget(self.empty)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.close_button = window._button("Close", self.close, "closeBrowserDialog")
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

        self.timer = QTimer(self)
        self.timer.setInterval(REFRESH_MS)
        self.timer.timeout.connect(self.tick)
        self.retranslate()

    # --- the session -----------------------------------------------------------------------
    @property
    def server(self):
        return self.window.live.server

    @property
    def session(self):
        return self.window.live.session

    def running(self) -> bool:
        return self.server is not None and self.server.running and self.session is not None

    def retranslate(self):
        self.setWindowTitle(self.window.t("Open in a browser"))
        self.devices_table.setHorizontalHeaderLabels([self.window.t(name) for name in self.COLUMNS])
        self.refresh()

    def open(self):
        self.refresh()
        self.timer.start()
        self.show()
        self.raise_()
        self.activateWindow()

    def done(self, result):
        self.timer.stop()
        super().done(result)

    # --- address, LAN ----------------------------------------------------------------------------
    def urls(self) -> dict:
        return self.server.web_urls() if self.running() else {"local": "", "lan": [], "lan_enabled": False}

    def refresh(self):
        window, running = self.window, self.running()
        for control in (self.lan, self.copy_button, self.open_button):
            control.setEnabled(running)
        self.unavailable.setVisible(not running)
        self.unavailable.setText("" if running else window.t(
            "Live collaboration is off: turn it on in the Agent menu to open the song in a browser."))
        urls = self.urls()
        shown = (urls["lan"][:1] or [urls["local"]])[0] if running else ""
        self.url.setText(shown)
        self.url.setToolTip(window.t("This computer only") if running and not urls["lan"] else "\n".join(urls["lan"]))
        self.lan.blockSignals(True)
        self.lan.setChecked(bool(urls["lan_enabled"]))
        self.lan.blockSignals(False)
        self.update_warning()
        self.update_devices()

    def update_warning(self):
        text = ""
        if self.running() and self.lan.isChecked():
            text = self.server.web_info().get("warning", "")
        self.warning.setText(self.window.t(text) if text else "")
        self.warning.setVisible(bool(text))

    def set_lan(self, on: bool):
        """Open or close the studio to the private network; the choice is remembered for the next start."""
        if not self.running():
            return
        try:
            self.server.enable_lan(bool(on))
        except ValidationError as exc:   # LIVE_LAN (no private address, port taken) or LIVE_HOST
            self.lan.blockSignals(True)
            self.lan.setChecked(False)
            self.lan.blockSignals(False)
            self.warning.setText(self.window.t("The local network could not be opened: {detail}", detail=exc))
            self.warning.setVisible(True)
            self.window.state.values["web_lan"] = False
            self.window._save_preferences()
            return
        self.window.state.values["web_lan"] = bool(on)
        self.window._save_preferences()
        self.refresh()

    def copy_url(self):
        QGuiApplication.clipboard().setText(self.url.text())
        self.window.message("Address copied")

    def open_url(self) -> bool:
        """Open the address in the computer's default browser."""
        address = self.url.text()
        return bool(address) and QDesktopServices.openUrl(QUrl(address))

    # --- devices ---------------------------------------------------------------------------------
    def devices(self) -> list[dict]:
        return self.session.web_devices() if self.running() else []

    def update_devices(self):
        devices = self.devices()
        table = self.devices_table
        table.setRowCount(len(devices))
        for row, device in enumerate(devices):
            network = self.window.t("local network" if device.get("listener") == "lan" else "this computer")
            for column, text in enumerate((device.get("name") or device["id"], device.get("agent", ""), network,
                                           device.get("last_seen", ""))):
                item = QTableWidgetItem(text)
                item.setToolTip(device.get("agent", ""))
                table.setItem(row, column, item)
        self.empty.setVisible(not devices)
        table.setVisible(bool(devices))

    def tick(self):
        self.update_devices()
        self.window.live.update_status()
