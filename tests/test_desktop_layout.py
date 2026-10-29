"""Window layout gestures: the library panel folded away by dragging its divider, Ctrl+wheel zoom of the
track columns, and Ctrl+click on a Mute or Solo button to hear every track again.

Gestures are real Qt mouse and wheel events, offscreen, on temporary projects (rendered playback; the
real-time engine side of Ctrl+click is covered in test_desktop_realtime).
"""
from __future__ import annotations

import importlib
import math
import shutil
import unittest
from unittest.mock import patch

try:
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from tracker4agents.desktop import TrackerWindow
    from tracker4agents.desktop_pattern import MIN_WIDTH, ZOOM_FLOOR, ZOOM_MAX, ZOOM_STEP, valid_zoom
    from tracker4agents.desktop_services import AppState
except ModuleNotFoundError:
    QApplication = None

PACKAGE = __package__ + "." if __package__ else ""
base = importlib.import_module(PACKAGE + "test_desktop_08")
formats = importlib.import_module(PACKAGE + "test_desktop_formats")
CTRL = Qt.KeyboardModifier.ControlModifier if QApplication else None
NO_MODIFIER = Qt.KeyboardModifier.NoModifier if QApplication else None


class LayoutCase(base.WindowCase):
    make_song = staticmethod(lambda: formats.mod_song(8, "Eight"))

    def wheel(self, notches, modifiers=CTRL, x=None):
        viewport = self.table.viewport()
        pos = QPointF(viewport.width() // 2 if x is None else x, viewport.height() // 2)
        event = QWheelEvent(pos, QPointF(viewport.mapToGlobal(pos.toPoint())), QPoint(), QPoint(0, 120 * notches),
                            Qt.MouseButton.NoButton, modifiers, Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(viewport, event)
        self.app.processEvents()

    def drag_divider(self, to_x):
        splitter = self.window.workspace
        handle = splitter.handle(1)
        start = QPoint(handle.width() // 2, handle.height() // 2)
        QTest.mousePress(handle, Qt.MouseButton.LeftButton, NO_MODIFIER, start)
        end = handle.mapFrom(splitter, QPoint(to_x, handle.y() + start.y()))
        QTest.mouseMove(handle, end)
        QTest.mouseRelease(handle, Qt.MouseButton.LeftButton, NO_MODIFIER, end)
        self.app.processEvents()

    def strip_aligned(self):
        strip = self.window.channel_strip
        for channel, group in enumerate(strip.groups):
            x, width = self.table.channel_span(channel)
            self.assertEqual((group.geometry().x(), group.geometry().width()), (x, width))

    def saved(self):
        return AppState(self.directory / "state").values


@unittest.skipUnless(QApplication is not None and shutil.which("ffmpeg"), "PySide6 and FFmpeg required")
class LibraryPanelTests(LayoutCase):
    def test_dragging_the_divider_to_the_left_edge_folds_the_library_and_dragging_back_reopens_it(self):
        window, splitter = self.window, self.window.workspace
        self.assertGreater(splitter.sizes()[0], 0)
        grid = self.table.viewport().width()
        self.drag_divider(0)
        self.assertEqual(splitter.sizes()[0], 0)
        self.assertTrue(window.library_hidden())
        self.assertIs(self.saved()["library_hidden"], True)
        self.pause(.05)
        self.assertGreater(self.table.viewport().width(), grid)   # the tracker takes the room
        self.drag_divider(220)
        self.assertGreater(splitter.sizes()[0], 0)
        self.assertFalse(window.library_hidden())
        self.assertIs(self.saved()["library_hidden"], False)

    def test_a_folded_library_stays_folded_in_the_next_window(self):
        self.drag_divider(0)
        self.window.close()
        again = TrackerWindow(self.path, self.directory / "state", restore=False)
        try:
            again.output.setMuted(True)
            again.show()
            self.wait_until(lambda: again.document is not None and again._audio_ready)
            self.assertEqual(again.workspace.sizes()[0], 0)
            self.drag_divider_of(again, 220)
            self.assertGreater(again.workspace.sizes()[0], 0)
        finally:
            again.close()
            again.pool.waitForDone(10000)
            again.deleteLater()
            self.app.processEvents()

    def drag_divider_of(self, window, to_x):
        previous, self.window = self.window, window
        try:
            self.drag_divider(to_x)
        finally:
            self.window = previous

    def test_the_grid_column_cannot_be_folded(self):
        splitter = self.window.workspace
        self.drag_divider(splitter.width())
        self.assertGreater(splitter.sizes()[1], 0)
        self.assertGreater(self.table.viewport().width(), 0)


@unittest.skipUnless(QApplication is not None and shutil.which("ffmpeg"), "PySide6 and FFmpeg required")
class ColumnZoomTests(LayoutCase):
    def test_ctrl_wheel_narrows_and_widens_the_tracks_and_the_headers_follow(self):
        table, header = self.table, self.table.horizontalHeader()
        natural = header.length()
        self.assertGreater(table.horizontalScrollBar().maximum(), 0)   # eight channels do not fit at first
        self.wheel(-2)
        self.assertLess(table.column_zoom, 1.0)
        self.assertLess(header.length(), natural)
        self.pause(.05)
        self.strip_aligned()
        self.wheel(4)
        self.assertGreater(table.column_zoom, 1.0)
        self.assertGreater(header.length(), natural)
        self.pause(.05)
        self.strip_aligned()
        self.wheel(-2)
        self.assertEqual(table.column_zoom, 1.0)   # the notches come back to the plain fit
        self.assertEqual(header.length(), natural)

    def test_the_zoom_is_clamped_and_text_stays_readable(self):
        table, header = self.table, self.table.horizontalHeader()
        self.wheel(-30)
        floor = table.column_zoom
        for column in range(self.model.columnCount()):
            self.assertGreaterEqual(header.sectionSize(column), round(MIN_WIDTH[self.model.part_of(column)] * ZOOM_FLOOR))
        self.wheel(-1)
        self.assertEqual(table.column_zoom, floor)   # no dead notches beyond the floor
        self.wheel(1)
        self.assertGreater(table.column_zoom, floor)   # the first notch back in already widens
        self.wheel(round(-math.log(table.column_zoom, ZOOM_STEP)))
        self.assertEqual(table.column_zoom, 1.0)   # whole notches: the way back lands on the plain fit
        self.wheel(60)
        self.assertEqual(table.column_zoom, ZOOM_MAX)

    def test_plain_wheel_still_scrolls_rows_and_the_zoom_is_remembered(self):
        table = self.table
        rows = table.verticalScrollBar()
        self.assertEqual(rows.value(), 0)
        self.wheel(-3, NO_MODIFIER)
        self.assertGreater(rows.value(), 0)
        self.assertEqual(table.column_zoom, 1.0)
        self.wheel(2)
        zoom = table.column_zoom
        self.assertAlmostEqual(self.saved()["column_zoom"], zoom)
        self.window.close()
        again = TrackerWindow(self.path, self.directory / "state", restore=False)
        try:
            again.output.setMuted(True)
            again.show()
            self.wait_until(lambda: again.document is not None and again._audio_ready)
            self.assertAlmostEqual(again.table.column_zoom, zoom)
            self.assertFalse(again.library_hidden())
        finally:
            again.close()
            again.pool.waitForDone(10000)
            again.deleteLater()
            self.app.processEvents()

    def test_a_remembered_zoom_is_checked(self):
        self.assertEqual(valid_zoom(None), 1.0)
        self.assertEqual(valid_zoom("2"), 1.0)
        self.assertEqual(valid_zoom(True), 1.0)
        self.assertEqual(valid_zoom(float("nan")), 1.0)
        self.assertEqual(valid_zoom(100), ZOOM_MAX)
        self.assertEqual(valid_zoom(1.21), ZOOM_STEP ** 2)

    def test_the_point_under_the_mouse_stays_in_place(self):
        table, bar = self.table, self.table.horizontalScrollBar()
        bar.setValue(bar.maximum() // 2)
        x = table.viewport().width() // 3
        channel = self.model.channel_of(table.columnAt(x))
        self.wheel(3, x=x)
        self.assertEqual(self.model.channel_of(table.columnAt(x)), channel)


@unittest.skipUnless(QApplication is not None and shutil.which("ffmpeg"), "PySide6 and FFmpeg required")
class AgentTabHeightTests(LayoutCase):
    def test_the_agent_tab_buttons_fit_without_scrolling_in_a_common_window(self):
        from PySide6.QtWidgets import QScrollArea
        window = self.window
        window.sample_tabs.setCurrentIndex(window.sample_tabs.indexOf(window.agent_panel))
        window.resize(1366, 768)
        for _ in range(5):
            self.app.processEvents()
        area = window.agent_panel.findChild(QScrollArea)
        self.assertEqual(area.verticalScrollBar().maximum(), 0)     # nothing below the fold
        viewport = area.viewport().height()
        for button in (window.agent_panel.accept_button, window.agent_panel.open_button,
                       window.comment_panel.resolve_button):
            top = button.mapTo(area.viewport(), button.rect().topLeft()).y()
            self.assertTrue(0 <= top and top + button.height() <= viewport, button.objectName())
        self.assertIn("Proposals from the agent", window.agent_panel.empty_hint.toolTip())   # the full hint stays in reach


class ClearMonitorTests(LayoutCase):
    def test_ctrl_click_on_any_mute_or_solo_makes_every_track_audible_with_one_render(self):
        window = self.window
        full = window.player.source()
        window.mutes[0].click()
        window.solos[3].click()
        window.solos[5].click()
        self.wait_until(lambda: window._audio_ready)
        self.assertEqual(window.audible(), (False, False, False, True, False, True, False, False))
        with patch.object(window, "prepare_audio", wraps=window.prepare_audio) as prepare:
            QTest.mouseClick(window.mutes[6], Qt.MouseButton.LeftButton, CTRL)
            self.assertEqual(prepare.call_count, 1)   # one change, not one per button
        self.assertEqual(window.audible(), (True,) * 8)
        self.assertFalse(any(control.isChecked() for control in window.mutes + window.solos))
        self.assertFalse(window.mutes[6].isChecked())   # the clicked button did not toggle itself
        self.assertEqual(window.mutes[0].text(), "Track 1")
        self.assertIn("audible again", window.statusBar().currentMessage())
        self.wait_until(lambda: window._audio_ready)
        self.assertEqual(window.player.source(), full)   # the full mix is heard again
        window.solos[2].click()
        QTest.mouseClick(window.solos[2], Qt.MouseButton.LeftButton, CTRL)   # the soloed button itself works too
        self.assertEqual(window.audible(), (True,) * 8)

    def test_ctrl_click_with_nothing_muted_changes_nothing_and_a_plain_click_still_toggles(self):
        window = self.window
        with patch.object(window, "prepare_audio", wraps=window.prepare_audio) as prepare:
            QTest.mouseClick(window.solos[1], Qt.MouseButton.LeftButton, CTRL)
            prepare.assert_not_called()
        QTest.mouseClick(window.mutes[1], Qt.MouseButton.LeftButton)
        self.assertFalse(window.audible()[1])

    def test_the_help_names_both_gestures_in_both_languages(self):
        window = self.window
        self.assertIn("Ctrl+click", window.mutes[0].toolTip())
        self.assertIn("Ctrl+click", window.solos[0].toolTip())
        keys = [keys for keys, _ in window.shortcut_popup.rows]
        self.assertIn("Ctrl+wheel", keys)
        self.assertIn("Ctrl+click Mute / Solo", keys)
        window.set_language("fr")
        self.assertIn("Ctrl+clic", window.mutes[0].toolTip())
        popup = window.show_shortcuts()
        try:
            texts = [popup.grid.itemAt(index).widget().text() for index in range(popup.grid.count())]
            self.assertIn("Ctrl+molette", texts)
            self.assertIn("Ctrl+clic Voie / Solo", texts)
        finally:
            popup.hide()
