"""Order-list editor: insert, create, duplicate, remove, reorder and rename patterns.

Every action is one `Document.patch` transaction through `TrackerWindow.apply_patch`.
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QInputDialog, QLineEdit

from .desktop_widgets import button


class OrderEditor:
    def __init__(self, window):
        self.window = window
        self.buttons = {}

    def build(self, layout: QHBoxLayout):
        """Add the compact buttons next to the order combo."""
        window = self.window
        specs = (("insert", "Insert", self.insert_current, "Insert the current pattern after this order"),
                 ("new", "New", self.new_pattern, "Insert a new empty pattern after this order"),
                 ("duplicate", "Duplicate", self.duplicate_pattern, "Insert a copy of the current pattern after this order"),
                 ("remove", "Remove", self.remove_order, "Remove this order (the pattern stays in the song)"),
                 ("up", "↑", lambda: self.move_order(-1), "Move this order up"),
                 ("down", "↓", lambda: self.move_order(1), "Move this order down"),
                 ("rename", "Rename…", lambda: self.rename_pattern(), "Rename the current pattern"))
        for key, text, callback, tip in specs:
            name = f"order_{key}"
            # Arrows are symbols, not translated words.
            control = button(text, callback, name) if len(text) == 1 else window._button(text, callback, name)
            control.setProperty("compact", True)
            window._bind(control, tip, "setToolTip")
            window._bind(control, tip, "setAccessibleName")
            self.buttons[key] = control
            layout.addWidget(control)

    def refresh(self):
        """Enable only the actions that make sense for the current order."""
        document, window = self.window.document, self.window
        count = len(document.module.orders) if document else 0
        enabled = {"insert": count > 0, "new": count > 0, "duplicate": count > 0, "rename": count > 0,
                   "remove": count > 1, "up": window.current_order > 0, "down": window.current_order < count - 1}
        for key, control in self.buttons.items():
            control.setEnabled(bool(document) and enabled[key])

    def _current(self):
        window = self.window
        if not window.document:
            return None
        return window.current_order, window.document.module.orders[window.current_order]

    def insert_current(self) -> bool:
        current = self._current()
        if not current:
            return False
        order, pattern = current
        return self.window.apply_patch([{"op": "insert_order", "pattern": pattern, "at": order + 1}],
                                       "Insert order", order=order + 1)

    def new_pattern(self) -> bool:
        current = self._current()
        return bool(current) and self.window.apply_patch(
            [{"op": "add_pattern", "insert_order": current[0] + 1}], "New pattern", order=current[0] + 1)

    def duplicate_pattern(self) -> bool:
        current = self._current()
        if not current:
            return False
        order, pattern = current
        name = self.window.document.module.patterns[pattern].name
        op = {"op": "add_pattern", "copy_of": pattern, "insert_order": order + 1}
        if name:
            op["name"] = f"{name[:58]} copy"
        return self.window.apply_patch([op], "Duplicate pattern", order=order + 1)

    def remove_order(self) -> bool:
        """Remove the current order. A module must still use its last stored pattern, so a trailing
        pattern that nothing plays any more is dropped in the same transaction (Ctrl+Z restores both)."""
        current = self._current()
        window = self.window
        if not current or len(window.document.module.orders) < 2:
            window.message("A song keeps at least one order.")
            return False
        order = current[0]
        remaining = window.document.module.orders[:order] + window.document.module.orders[order + 1:]
        count, dropped = len(window.document.module.patterns), []
        while count > 1 and count - 1 not in remaining:
            count -= 1
            dropped.append(count)
        ops = [{"op": "remove_order", "at": order}] + [{"op": "remove_pattern", "pattern": index} for index in dropped]
        done = window.apply_patch(ops, "Remove order", order=min(order, len(remaining) - 1))
        if done and dropped:
            window.message("Order removed; pattern {number} was no longer used and was removed too · Ctrl+Z to undo",
                           number=f"{dropped[0]:02X}")
        return done

    def move_order(self, delta: int) -> bool:
        current = self._current()
        if not current:
            return False
        target = current[0] + delta
        if not 0 <= target < len(self.window.document.module.orders):
            return False
        return self.window.apply_patch([{"op": "move_order", "at": current[0], "to": target}], "Move order", order=target)

    def rename_pattern(self, name: str | None = None) -> bool:
        current = self._current()
        if not current:
            return False
        pattern = current[1]
        if name is None:
            old = self.window.document.module.patterns[pattern].name
            name, accepted = QInputDialog.getText(self.window, self.window.t("Rename pattern"),
                                                  self.window.t("Name of pattern {number}", number=f"{pattern:02X}"),
                                                  QLineEdit.EchoMode.Normal, old)
            if not accepted:
                return False
        return self.window.apply_patch([{"op": "rename_pattern", "pattern": pattern, "name": name.strip()}], "Rename pattern")
