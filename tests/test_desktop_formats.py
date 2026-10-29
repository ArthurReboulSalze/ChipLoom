"""The window with every module the core supports: MOD with 2 to 32 channels, and the XM profile.

Small modules built in code, saved as temporary projects. The window runs on the rendered path (FFmpeg) unless a test
says real-time, which then uses the fake sound card of test_desktop_realtime. Keys are real Qt key events sent to the
pattern grid.
"""
from __future__ import annotations

import importlib
import shutil
import unittest
from unittest.mock import patch
import wave

try:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QColor, QGuiApplication, QKeyEvent
    from PySide6.QtWidgets import QApplication
    from tracker4agents import desktop_playback
    from tracker4agents.desktop_widgets import XM_REFUSED_TIP
except ModuleNotFoundError:
    QApplication = None

from tracker4agents import formats
from tracker4agents.desktop_mixer import JamMixer, Voice, render_wav
from tracker4agents.document import Document, fingerprint
from tracker4agents.model import Module, Pattern, Sample, ValidationError, cell
from tracker4agents.realtime import find_library
from tracker4agents.web import brand

PACKAGE = __package__ + "." if __package__ else ""
base = importlib.import_module(PACKAGE + "test_desktop_08")
PCM = (0, 0) + (60, 0, -60, 0) * 16
KEY_PRESS = QEvent.Type.KeyPress if QApplication else None
KEY_RELEASE = QEvent.Type.KeyRelease if QApplication else None
NO_MODIFIER = Qt.KeyboardModifier.NoModifier if QApplication else None


def mod_song(channels: int, title: str = "Wide") -> Module:
    """A looped Kick (slot 1) and Lead (slot 2): the Lead in the last channel, the Kick in the first."""
    samples = [Sample("Kick", PCM, 64, 0, 2, 64), Sample("Lead", PCM, 48, 0, 2, 64)]
    last = channels - 1
    cells = {(0, 0): cell("C-2", 1), (0, last): cell("C-2", 2), (4, last): cell("E-2", 1, "C20"),
             (4, 0): cell("G-2", 1), (2, 0): cell("D-2", 1)}
    return Module(title, samples, [Pattern(name="Intro", cells=cells), Pattern(name="Verse")], [0, 1, 0], {}, channels)


def last_channel_song(channels: int) -> Module:
    """Only the last channel plays (a note held through the pattern): muting it silences everything."""
    sample = Sample("Lead", (0, 0) + (100, 0, -100, 0) * 16, 64, 0, 2, 64)
    cells = {(0, channels - 1): cell("C-2", 1), (63, 0): cell(effect="D00")}
    return Module("Held", [sample], [Pattern(cells=cells)], [0], {}, channels)


def xm_song(title: str = "XM song") -> Module:
    """Six channels, an 8-bit loop, a 16-bit ping-pong instrument; patterns of 32 and 7 rows with a volume column,
    an effect letter and a key off."""
    wide = tuple(value * 100 for value in PCM)
    samples = [Sample("Lead", PCM, 64, 0, 2, 64), Sample("Pad", wide, 48, 12, 2, 64, None, 16, "pingpong", 64, -3)]
    samples += [Sample("", (), 64) for _ in range(8)]   # ten instruments: typed numbers up to 0A refer to one
    first = Pattern("Pattern 00", {}, 32)
    first.put(0, 0, cell("C-4", 1, "000", "xm", 0x40))
    first.put(1, 1, cell("E-4", 2, "A0F", "xm", 0xC8))
    first.put(2, 2, cell("G#5", 1, "G40", "xm"))
    first.put(3, 0, cell("===", 0, "K00", "xm"))
    first.put(5, 5, cell("C-5", 2, "000", "xm", 0x20))
    second = Pattern("Pattern 01", {}, 7)
    second.put(0, 0, cell("C-4", 1, "000", "xm"))
    return Module(title, samples, [first, second], [0, 1, 0], {}, 6, "xm")


class FormatCase(base.WindowCase):
    """Window helpers shared by the format tests."""

    def setUp(self):
        super().setUp()
        window = self.window
        window.keyboard_combo.setCurrentIndex(window.keyboard_combo.findData("qwerty"))
        window.edit_step.setValue(1)

    def press(self, text, key=None, modifiers=NO_MODIFIER):
        key = ord(text.upper()) if key is None else key
        for kind in (KEY_PRESS, KEY_RELEASE):
            QApplication.sendEvent(self.table, QKeyEvent(kind, key, modifiers, text))

    def type_keys(self, text):
        for char in text:
            self.press(char)

    def go(self, row, channel, part="note"):
        self.table.setCurrentIndex(self.model.index(row, self.model.column_of(channel, part)))

    def export_to(self, name):
        """Export through the window's own action, with the file dialog answered."""
        destination = self.directory / name
        with patch.object(self.window, "_save_path", return_value=destination) as chooser:
            self.window.export_mod()
        self.pause(.05)
        return destination, chooser

    def colour(self, row, channel, part="note"):
        index = self.model.index(row, self.model.column_of(channel, part))
        return self.model.data(index, Qt.ItemDataRole.ForegroundRole).name()


@unittest.skipUnless(base.TrackerWindow is not None and shutil.which("ffmpeg"), "PySide6 and FFmpeg required")
class EightChannelTests(FormatCase):
    make_song = staticmethod(lambda: mod_song(8, "Eight"))

    def test_open_and_display_eight_channels(self):
        window, model = self.window, self.model
        self.assertEqual((model.rowCount(), model.columnCount()), (64, 24))
        self.assertEqual((len(window.mutes), len(window.solos), len(window.channel_strip.groups)), (8, 8, 8))
        self.assertEqual(window.audible(), (True,) * 8)
        self.assertIn("MOD", window.format_label.text())
        self.assertIn("8 CHANNELS", window.format_label.text())
        self.assertEqual(window.export_action.text(), "Export MOD…")
        self.assertEqual([model.headerData(column, Qt.Orientation.Horizontal) for column in (21, 22, 23)],
                         ["Note", "Smp", "Effect"])
        self.assertEqual(model.data(model.index(0, model.column_of(7, "note"))), "C-2")
        self.assertEqual(model.data(model.index(0, model.column_of(7, "sample"))), "02")
        self.assertEqual(model.data(model.index(4, model.column_of(7, "effect"))), "C20")
        self.assertEqual(model.channel_of(23), 7)
        self.assertEqual(model.part_of(23), "effect")

    def test_a_wide_grid_scrolls_sideways_and_the_track_headers_follow_it(self):
        window, table, strip = self.window, self.table, self.window.channel_strip
        bar = table.horizontalScrollBar()
        self.assertGreater(bar.maximum(), 0)   # eight channels do not fit in the minimum window
        x, width = table.channel_span(7)
        self.assertGreater(x + width, table.viewport().width())
        bar.setValue(bar.maximum())
        self.pause(.05)
        for channel in range(8):
            x, width = table.channel_span(channel)
            self.assertEqual(strip.groups[channel].geometry().x(), x)
            self.assertEqual(strip.groups[channel].geometry().width(), width)
        x, width = table.channel_span(7)
        self.assertEqual(x + width, table.viewport().width())   # the last channel ends at the edge of the grid
        self.assertEqual(strip.clip.geometry().x(), table.viewport().geometry().x())
        window.mutes[7].click()   # a header scrolled into view still works
        self.assertFalse(window.audible()[7])

    def test_channel_colours_are_the_web_studios(self):
        window = self.window
        for channel in (0, 3, 4, 7):
            self.assertEqual(self.colour(0, channel), QColor(brand.channel_color(window.theme, channel)).name())
            self.assertIn(brand.channel_color(window.theme, channel), window.mutes[channel].styleSheet())
        self.assertNotEqual(self.colour(0, 3), self.colour(0, 7))   # beyond four the colours are tinted variants
        window.set_theme("light")
        self.assertEqual(self.colour(0, 7), QColor(brand.channel_color("light", 7)).name())
        window.mutes[7].click()   # a muted channel greys out
        self.assertEqual(self.colour(0, 7), QColor(window.palette_colors["disabled"]).name())

    def test_editing_a_cell_in_the_last_channel_by_field_hex_digits_and_piano_keys(self):
        window, model = self.window, self.model
        index = model.index(2, model.column_of(7, "effect"))
        self.assertTrue(model.setData(index, "c20"))
        self.assertEqual(self.cell(2, 7).effect, "C20")
        self.assertEqual(window.live.session.changes()["entries"][-1]["label"], "Edit cell")
        window.set_edit_mode(True)
        window.edit_octave.setValue(2)
        window.samples.setCurrentRow(1)   # the Lead
        self.go(5, 7)
        self.press("z")
        self.assertEqual(self.cell(5, 7), cell("C-2", 2))
        self.assertEqual(self.table.currentIndex().row(), 6)   # the edit step
        self.go(6, 7, "effect")
        self.type_keys("c")
        self.assertEqual(model.data(model.index(6, model.column_of(7, "effect"))), "C__")
        self.type_keys("10")
        self.assertEqual(self.cell(6, 7).effect, "C10")
        self.go(7, 7, "sample")
        self.type_keys("2")   # 2-F cannot start a sample number: it becomes 02
        self.assertEqual(self.cell(7, 7).sample, 2)
        self.go(5, 7)
        self.press("", key=int(Qt.Key.Key_Backspace))
        self.assertEqual(self.cell(5, 7).note, None)
        self.assertEqual(self.cell(5, 7).sample, 2)   # only the note field is cleared
        self.go(5, 7)
        self.press("q")   # C-3, an octave above the lower row
        self.assertEqual(self.cell(5, 7), cell("C-3", 2))

    def test_blocks_copy_move_and_transpose_in_the_last_channels(self):
        window, table = self.window, self.table
        table.select_block(0, 5, 6, 2)
        self.assertEqual(table.selection_block(), (0, 5, 6, 2))
        self.assertTrue(table.copy_block())
        text = QGuiApplication.clipboard().text()
        self.assertEqual(len(text.splitlines()), 5)
        table.select_block(10, 1, 7, 1)   # one channel from the edge: the pasted block shifts back to fit
        self.assertTrue(table.paste_block())
        self.assertEqual((self.cell(10, 6), self.cell(10, 7)), (cell(), cell("C-2", 2)))
        self.assertEqual(self.cell(14, 7), cell("E-2", 1, "C20"))
        self.assertEqual(table.selection_block(), (10, 5, 6, 2))
        table.select_block(0, 1, 7, 1)
        self.assertTrue(table.move_block(0, -1))
        self.assertEqual((self.cell(0, 6), self.cell(0, 7)), (cell("C-2", 2), cell()))
        self.assertEqual(table.selection_block(), (0, 1, 6, 1))
        table.select_block(0, 1, 6, 1)
        self.assertTrue(table.move_block(0, 1))
        self.assertFalse(table.move_block(0, 1))   # already in the last channel
        self.assertIn("edge", window.statusBar().currentMessage())
        table.select_block(0, 1, 7, 1)
        self.assertTrue(table.transpose_block(12))
        self.assertEqual(self.cell(0, 7), cell("C-3", 2))
        self.assertTrue(table.clear_block())
        self.assertEqual(self.cell(0, 7), cell())
        table.select_block(0, 1, 7, 1)
        self.assertTrue(table.paste_block())   # what was copied (channels 6-7 of rows 0-4) lands back
        self.assertEqual(self.cell(0, 7), cell("C-2", 2))

    def test_mute_and_solo_cover_all_eight_channels_and_reach_the_live_context(self):
        window, session = self.window, self.window.live.session
        window.mutes[7].click()
        self.assertEqual(window.audible(), (True,) * 7 + (False,))
        self.assertEqual(window.mutes[7].text(), "Track 8 · MUTED")
        self.assertEqual(window.mutes[7].toolTip(), "Click to unmute track 8\nCtrl+click: every track audible again")
        self.wait_until(lambda: session.context()["audible"] == [True] * 7 + [False])
        window.mutes[7].click()
        window.solos[6].click()
        self.assertEqual(window.audible(), (False,) * 6 + (True, False))
        self.wait_until(lambda: session.context()["audible"] == [False] * 6 + [True, False])
        window.mutes[6].click()
        self.assertEqual(window.audible(), (False,) * 8)   # solo + mute: nothing audible
        window.mutes[6].click()
        window.solos[6].click()
        self.assertEqual(window.audible(), (True,) * 8)

    def test_the_context_carries_the_channel_of_the_cursor_and_the_selection(self):
        session = self.window.live.session
        self.go(3, 7, "sample")
        self.table.select_block(2, 3, 6, 2)
        self.wait_until(lambda: (session.context().get("selection") or {}).get("channel") == 6)
        self.assertEqual(session.context()["selection"], {"pattern": 0, "row": 2, "rows": 3, "channel": 6, "channels": 2})
        self.assertEqual(session.context()["channel"], 6)   # the current cell stays where the selection starts
        self.assertEqual(session.context()["audible"], [True] * 8)
        self.call("select", pattern=0, row=0, rows=2, channel=7, channels=1)
        self.assertEqual(self.table.selection_block(), (0, 2, 7, 1))

    def test_export_round_trip_keeps_eight_channels_and_the_edits(self):
        window = self.window
        self.model.setData(self.model.index(9, self.model.column_of(7, "note")), "G-2")
        destination, chooser = self.export_to("eight.mod")
        self.assertEqual(chooser.call_args.args[0], ".mod")
        exported = formats.read(destination)
        self.assertEqual((exported.format, exported.channels), ("mod", 8))
        self.assertEqual(exported.patterns[0].get(9, 7), cell(note="G-2"))
        self.assertEqual(exported.patterns[0].get(0, 7), cell("C-2", 2))
        self.assertEqual(window.statusBar().currentMessage(), "MOD exported: eight.mod")
        self.assertTrue(window.open_document(destination, ask=False))   # and it opens again as eight channels
        self.assertEqual((len(window.mutes), self.model.columnCount()), (8, 24))
        self.assertEqual(self.cell(9, 7).note, "G-2")

    def test_the_rendered_path_renders_every_channel_and_the_mutes(self):
        window = self.window
        self.assertIsNone(window.rt)
        every = window.cache.prepare(window.document.module, window.audible())
        silenced = window.cache.prepare(window.document.module, (True,) * 7 + (False,))
        self.assertTrue(every.is_file() and silenced.is_file())
        self.assertNotEqual(every, silenced)
        self.assertEqual(wave.open(str(every)).getframerate(), 48000)
        window.mutes[7].click()   # the window re-renders for the new mutes and is ready again
        self.wait_until(lambda: window._audio_ready and not window._loading_audio)
        self.assertEqual(window.player.source().toLocalFile(), str(silenced).replace("\\", "/"))

    def test_the_jam_plays_what_the_cursor_channel_holds(self):
        window = self.window
        window.edit_octave.setValue(2)
        window.set_edit_mode(False)
        self.go(0, 7)   # the Lead in the last channel
        self.assertEqual(window.instrument_slot(), 2)
        self.press("z")
        self.assertEqual((window.jam.log[-1]["name"], window.jam.log[-1]["note"], window.jam.log[-1]["source"]),
                         ("Lead", "C-2", "pattern"))
        self.go(0, 0)   # then the Kick in the first
        self.assertEqual(window.instrument_slot(), 1)
        self.press("x")
        self.assertEqual((window.jam.log[-1]["name"], window.jam.log[-1]["note"]), ("Kick", "D-2"))
        self.assertEqual(self.cell(0, 7), cell("C-2", 2))   # nothing was written
        self.assertEqual(window.jam.note_for("z"), "C-2")

    def test_thirty_two_channels_open_scroll_and_get_tinted_colours(self):
        window, model = self.window, self.model
        self.assertTrue(window.open_module(mod_song(32, "Full")))
        self.assertEqual((len(window.mutes), model.columnCount()), (32, 96))
        self.assertEqual(window.audible(), (True,) * 32)
        self.assertEqual(len({self.colour(0, channel) for channel in range(32)}), len({brand.channel_color(window.theme, c)
                                                                                         for c in range(32)}))
        self.assertGreater(len({self.colour(0, channel) for channel in range(32)}), 4)
        self.assertEqual(self.colour(0, 31), QColor(brand.channel_color(window.theme, 31)).name())
        self.assertIn("32 CHANNELS", window.format_label.text())
        window.table.horizontalScrollBar().setValue(window.table.horizontalScrollBar().maximum())
        self.go(0, 31)
        self.assertTrue(self.table.visualRect(self.table.currentIndex()).isValid())
        window.mutes[31].click()
        self.assertEqual(window.audible()[31], False)


@unittest.skipUnless(base.TrackerWindow is not None and shutil.which("ffmpeg"), "PySide6 and FFmpeg required")
class TwoChannelTests(FormatCase):
    make_song = staticmethod(lambda: mod_song(2, "Duo"))

    def test_two_channels_fill_the_grid_without_scrolling(self):
        window, model, table = self.window, self.model, self.table
        self.assertEqual((model.rowCount(), model.columnCount(), len(window.mutes)), (64, 6, 2))
        self.assertIn("2 CHANNELS", window.format_label.text())
        self.assertEqual(table.horizontalScrollBar().maximum(), 0)
        self.assertEqual(sum(table.columnWidth(column) for column in range(6)), table.viewport().width())
        x, width = table.channel_span(1)
        self.assertEqual((x, x + width), (table.columnViewportPosition(3), table.viewport().width()))
        self.assertEqual(window.channel_strip.groups[1].geometry().x(), x)

    def test_edit_mute_solo_and_export_in_the_last_channel(self):
        window = self.window
        self.model.setData(self.model.index(3, self.model.column_of(1, "note")), "A-2")
        self.assertEqual(self.cell(3, 1), cell(note="A-2"))
        self.assertTrue(self.table.transpose_block(2) in (True, False))   # no selection yet: the current cell
        window.solos[1].click()
        self.assertEqual(window.audible(), (False, True))
        window.solos[1].click()
        window.mutes[0].click()
        self.assertEqual(window.audible(), (False, True))
        window.mutes[0].click()
        self.assertEqual(window.audible(), (True, True))
        destination, _ = self.export_to("duo.mod")
        exported = formats.read(destination)
        self.assertEqual((exported.channels, exported.patterns[0].get(3, 1).note), (2, "A-2"))
        self.assertEqual(self.cell(0, 1), cell("C-2", 2))

    def test_the_buttons_follow_the_module_when_the_channel_count_changes(self):
        window = self.window
        window.mutes[1].click()
        window.solos[0].click()
        self.assertTrue(window.open_module(mod_song(8)))   # a new module starts with nothing muted
        self.assertEqual((len(window.mutes), len(window.solos)), (8, 8))
        self.assertFalse(any(control.isChecked() for control in window.mutes + window.solos))
        window.mutes[5].click()
        agent = Document(mod_song(4, "Quartet"))
        window.apply_external(agent.module, "reload", [])   # the file was replaced by a four-channel module
        self.assertEqual((len(window.mutes), self.model.columnCount()), (4, 12))
        self.assertEqual(window.audible(), (True,) * 4)
        self.assertEqual(len(window.channel_strip.groups), 4)
        window.undo()   # undo brings the eight channels back, with the states the channels shared
        self.assertEqual((len(window.mutes), self.model.columnCount()), (8, 24))


@unittest.skipUnless(base.TrackerWindow is not None and shutil.which("ffmpeg"), "PySide6 and FFmpeg required")
class XmTests(FormatCase):
    make_song = staticmethod(xm_song)

    def test_open_and_display_an_xm(self):
        window, model = self.window, self.model
        self.assertEqual(window.document.module.format, "xm")
        self.assertEqual((model.rowCount(), model.columnCount(), len(window.mutes)), (32, 24, 6))
        self.assertEqual(window.format_label.text(), "XM · 6 CHANNELS")   # no PAL: that is a MOD clock
        self.assertEqual(window.export_action.text(), "Export XM…")
        self.assertEqual(window.export_button.text(), "Export XM…")
        self.assertEqual([model.headerData(column, Qt.Orientation.Horizontal) for column in range(4)],
                         ["Note", "Ins", "Vol", "Effect"])
        self.assertEqual([model.data(model.index(0, column)) for column in range(4)], ["C-4", "01", "40", "000"])
        self.assertEqual([model.data(model.index(2, model.column_of(2, part))) for part in ("note", "sample", "volume", "effect")],
                         ["G#5", "01", "--", "G40"])
        self.assertEqual(model.data(model.index(3, 0)), "===")   # key off
        self.assertIn("effect letters 0-9 then A-Z", model.data(model.index(0, 0), Qt.ItemDataRole.ToolTipRole))
        self.assertTrue(window.xm_hint.isVisible() or not window.isVisible())
        self.assertIn("key off", window.xm_hint.text())
        self.assertEqual((window.edit_octave.minimum(), window.edit_octave.maximum(), window.edit_octave.value()), (0, 7, 4))
        self.assertEqual(window.jam.note_for("z"), "C-4")

    def test_each_pattern_has_its_own_row_count(self):
        window, model = self.window, self.model
        self.assertEqual(model.rowCount(), 32)
        window.orders.setCurrentIndex(1)   # the pattern of 7 rows
        self.assertEqual((model.pattern, model.rowCount(), model.headerData(6, Qt.Orientation.Vertical)), (1, 7, "06"))
        self.go(6, 0)
        self.press("", key=int(Qt.Key.Key_Down))
        self.assertEqual(self.table.currentIndex().row(), 6)   # the last row is the last row
        window.orders.setCurrentIndex(2)
        self.assertEqual((model.pattern, model.rowCount()), (0, 32))
        self.table.select_block(30, 2, 0, 1)
        self.assertEqual(self.table.selection_block(), (30, 2, 0, 1))
        self.assertTrue(self.table.move_block(-1, 0))   # inside the pattern
        self.table.select_block(0, 1, 0, 1)
        self.assertFalse(self.table.move_block(-1, 0))
        self.table.select_block(30, 2, 0, 1)
        self.assertFalse(self.table.move_block(1, 0))   # the pattern ends at row 31, not 63

    def test_the_volume_column_is_edited_by_field_and_by_hex_digits(self):
        window, model = self.window, self.model
        index = model.index(4, model.column_of(3, "volume"))
        self.assertTrue(model.setData(index, "48"))
        self.assertEqual(self.cell(4, 3).volume, 0x48)
        self.assertEqual(model.data(index), "48")
        self.assertTrue(model.setData(index, "--"))
        self.assertEqual(self.cell(4, 3).volume, 0)
        window.set_edit_mode(True)
        self.go(6, 3, "volume")
        self.press("5")
        self.assertEqual(model.data(model.index(6, model.column_of(3, "volume"))), "5_")
        self.press("0")
        self.assertEqual(self.cell(6, 3).volume, 0x50)
        self.assertEqual(self.table.currentIndex().row(), 7)
        self.go(7, 3, "volume")
        self.press("c")   # any hexadecimal digit may start a volume byte
        self.press("8")
        self.assertEqual(self.cell(7, 3).volume, 0xC8)
        self.go(7, 3, "volume")
        self.press("", key=int(Qt.Key.Key_Backspace))
        self.assertEqual(self.cell(7, 3).volume, 0)
        self.assertEqual(window.live.session.changes()["entries"][-1]["label"], "Clear field")

    def test_instruments_notes_effect_letters_and_key_off_by_keyboard(self):
        window, model = self.window, self.model
        window.set_edit_mode(True)
        window.samples.setCurrentRow(1)   # the 16-bit Pad (instrument 2)
        self.go(8, 4)
        self.press("z")
        self.assertEqual(self.cell(8, 4), cell("C-4", 2, "000", "xm"))   # an XM label C-4, with the Pad
        self.assertEqual(self.table.currentIndex().row(), 9)
        self.go(9, 4)
        self.press("1")    # key off: the key before 2
        self.assertEqual(self.cell(9, 4).period, 97)
        self.assertEqual(self.cell(9, 4).sample, 0)
        self.assertEqual(model.data(model.index(9, model.column_of(4, "note"))), "===")
        self.go(10, 4, "sample")
        self.press("0")   # a first digit 0-8 waits for the second (instruments run up to 80)
        self.assertEqual(model.data(model.index(10, model.column_of(4, "sample"))), "0_")
        self.press("7")
        self.assertEqual(self.cell(10, 4).sample, 7)
        self.go(11, 4, "sample")
        self.press("9")   # 9-F cannot start an instrument number up to 80: it becomes 09
        self.assertEqual(self.cell(11, 4).sample, 9)
        self.go(12, 4, "effect")
        self.type_keys("k00")   # an effect letter beyond F starts the effect
        self.assertEqual(self.cell(12, 4).effect, "K00")
        self.go(13, 4, "effect")
        self.type_keys("g4")
        self.assertEqual(model.data(model.index(13, model.column_of(4, "effect"))), "G4_")
        self.type_keys("0")
        self.assertEqual(self.cell(13, 4).effect, "G40")
        self.go(14, 4, "effect")
        self.type_keys("a0")
        self.type_keys("k")   # a letter beyond F is not a digit: ignored after the first character
        self.assertEqual(model.data(model.index(14, model.column_of(4, "effect"))), "A0_")
        self.press("f")
        self.assertEqual(self.cell(14, 4).effect, "A0F")
        window.keyboard_combo.setCurrentIndex(window.keyboard_combo.findData("azerty"))
        self.go(15, 4)
        self.press("&")    # the key before 2 on an AZERTY keyboard
        self.assertEqual(self.cell(15, 4).period, 97)
        self.go(16, 4)
        window.edit_octave.setValue(7)
        self.press("p")   # the last key of the upper row is 28 semitones up: E-9, beyond B-7
        self.assertEqual(self.cell(16, 4).period, 0)
        self.assertIn("C-0..B-7", window.statusBar().currentMessage())

    def test_blocks_carry_the_volume_column_and_refuse_the_other_format(self):
        window, table = self.window, self.table
        table.select_block(0, 4, 0, 2)
        self.assertTrue(table.copy_block())
        text = QGuiApplication.clipboard().text()
        self.assertIn("C-4 01 40 ... | --- -- -- ...", text)
        self.assertIn("=== -- -- K00", text)
        table.select_block(10, 1, 2, 1)
        self.assertTrue(table.paste_block())
        self.assertEqual((self.cell(10, 2), self.cell(11, 3)), (cell("C-4", 1, "000", "xm", 0x40), cell("E-4", 2, "A0F", "xm", 0xC8)))
        self.assertEqual(self.cell(13, 2), cell("===", 0, "K00", "xm"))
        self.assertEqual(table.selection_block(), (10, 4, 2, 2))
        before = fingerprint(window.document.module)
        table.clipboard = (text, table.clipboard[1], "mod")
        self.assertFalse(table.paste_block())
        self.assertEqual(fingerprint(window.document.module), before)
        self.assertIn("cannot be pasted into a XM module", window.statusBar().currentMessage())
        QGuiApplication.clipboard().setText("C-4 01 40 A0F | --- -- -- ...\nC-4 01 40 A0F | bad")   # an agent's grid text
        table.clipboard = None
        self.assertFalse(table.paste_block())
        QGuiApplication.clipboard().setText("10 | G-5 01 40 A0F | --- -- -- ... | --- 02 -- 000 | --- -- -- ... | --- -- -- ... | --- -- -- ...")
        table.select_block(20, 1, 0, 1)
        self.assertTrue(table.paste_block())
        self.assertEqual(self.cell(20, 0), cell("G-5", 1, "A0F", "xm", 0x40))
        self.assertEqual(self.cell(20, 2).sample, 2)

    def test_transposing_leaves_key_off_alone(self):
        table = self.table
        table.select_block(0, 4, 0, 1)
        self.assertTrue(table.transpose_block(2))
        self.assertEqual((self.cell(0, 0), self.cell(3, 0)), (cell("D-4", 1, "000", "xm", 0x40), cell("===", 0, "K00", "xm")))
        table.select_block(0, 1, 0, 1)
        self.assertTrue(table.transpose_block(-50))   # C-0 is the lowest note: D-4 is 50 semitones above it
        self.assertEqual(self.cell(0, 0), cell("C-0", 1, "000", "xm", 0x40))
        self.assertFalse(table.transpose_block(-1))   # nothing below C-0: refused, nothing changes
        self.assertEqual(self.cell(0, 0).note, "C-0")
        self.go(0, 0)
        self.window.transpose(2)   # the track buttons transpose the whole channel, key off included as it is
        self.assertEqual((self.cell(0, 0).note, self.cell(3, 0)), ("D-0", cell("===", 0, "K00", "xm")))

    def test_export_writes_an_xm_that_reads_back_identically(self):
        window = self.window
        destination, chooser = self.export_to("song.xm")
        self.assertEqual(chooser.call_args.args[0], ".xm")
        self.assertEqual(chooser.call_args.args[1], "Export XM module")
        exported = formats.read(destination)
        self.assertEqual((exported.format, exported.channels, [pattern.rows for pattern in exported.patterns]),
                         ("xm", 6, [32, 7]))
        self.assertEqual(exported.patterns[0].get(0, 0), cell("C-4", 1, "000", "xm", 0x40))
        self.assertEqual(exported.patterns[0].get(3, 0), cell("===", 0, "K00", "xm"))
        self.assertEqual(exported.patterns[0].get(2, 2), cell("G#5", 1, "G40", "xm"))
        self.assertEqual([(sample.bits, sample.loop_mode, sample.relative_note) for sample in exported.samples[:2]],
                         [(8, "forward", 0), (16, "pingpong", -3)])
        self.assertEqual(window.statusBar().currentMessage(), "XM exported: song.xm")
        self.assertTrue(window.open_document(destination, ask=False))   # the exported file is a module the window opens
        self.assertEqual((window.document.module.format, len(window.mutes), self.model.columnCount()), ("xm", 6, 24))
        self.assertEqual(self.cell(0, 0), cell("C-4", 1, "000", "xm", 0x40))
        self.assertEqual(window.document.path.suffix, ".xm")

    def test_an_export_to_the_wrong_extension_is_refused_in_words(self):
        window = self.window
        destination, _ = self.export_to("wrong.mod")
        self.assertFalse(destination.exists())
        self.assertTrue(window.statusBar().currentMessage())

    def test_sample_operations_the_core_refuses_are_disabled_with_the_reason(self):
        window = self.window
        editor, tip = window.sample_workshop.editor, XM_REFUSED_TIP
        for control in (*editor.listen.values(), *editor.apply.values(), editor.loop_start, editor.trim_end,
                        editor.gain_db, editor.fade_in, *editor.selection_buttons, editor.wave):
            self.assertFalse(control.isEnabled())
        for control in (*editor.listen.values(), *editor.apply.values(), editor.loop_start, editor.gain_db):
            self.assertEqual(control.toolTip(), tip)
        for control in (editor.volume, editor.finetune, editor.play_button, editor.apply_button):
            self.assertTrue(control.isEnabled())
        self.assertNotEqual(window.sample_browser.add_button.toolTip(), tip)   # inserting into an XM works
        self.assertTrue(window.create_panel.add_button.isEnabled())
        self.assertFalse(window.create_panel.pcm.isEnabled())           # plain drawn PCM stays a MOD sample edit
        self.assertEqual(window.create_panel.pcm.toolTip(), tip)
        self.assertFalse(window.instrument_panel.apply_button.isEnabled())
        self.assertEqual(window.instrument_panel.apply_button.toolTip(), tip)
        self.assertIsNone(window.instrument_panel.apply_at_cursor())   # Ctrl+I says so as well
        self.assertEqual(window.instrument_panel.status.text(), tip)
        window.sample_workshop.show_page(1)
        levels = window.sample_workshop.levels
        self.assertEqual(levels.rows, [])
        self.assertIn("XM module", levels.empty.text())
        with self.assertRaises(ValidationError) as caught:   # and the core agrees
            window.run_patch([{"op": "sample_gain", "slot": 1, "db": 1}], "Gain")
        self.assertEqual(caught.exception.code, "XM_OP_UNSUPPORTED")
        revision = window.document.revision
        for operation in ({"op": "sample_trim", "slot": 1, "start": 0, "end": 10}, {"op": "recipe_sample", "name": "x", "recipe": {}}):
            with self.assertRaises(ValidationError):
                window.run_patch([operation], "Refused")
        self.assertEqual(window.document.revision, revision)

    def test_what_an_xm_sample_allows_still_works_and_its_facts_are_shown(self):
        window = self.window
        editor = window.sample_workshop.editor
        self.assertEqual((editor.finetune.minimum(), editor.finetune.maximum()), (-128, 127))
        self.assertIn("8-bit", window.sample_info.text())
        self.assertIn("panning 128", window.sample_info.text())
        window.samples.setCurrentRow(1)
        text = window.sample_info.text()
        for fact in ("132 bytes", "16-bit", "(pingpong)", "panning 64", "relative note -3", "C-4 preview"):
            self.assertIn(fact, text)
        editor.finetune.setValue(-100)
        editor.volume.setValue(30)
        window.apply_sample()
        sample = window.document.module.samples[1]
        self.assertEqual((sample.finetune, sample.volume), (-100, 30))
        self.assertEqual((sample.bits, sample.panning, sample.relative_note), (16, 64, -3))
        window.samples.setCurrentRow(0)
        window.samples.setCurrentRow(1)
        self.assertEqual(editor.finetune.value(), -100)

    def test_samples_play_at_the_xm_rate_and_the_song_renders_as_an_xm(self):
        window = self.window
        preview = window.cache.sample(window.document.module, 1)   # the 16-bit Pad, relative note -3, fine tune 12
        with wave.open(str(preview)) as stream:
            self.assertEqual(stream.getframerate(), round(8363 * 2 ** (-3 / 12 + 12 / 1536)))
            self.assertEqual(stream.getsampwidth(), 2)
        other = window.cache.sample(window.document.module, 0)
        self.assertNotEqual(preview, other)
        wide = window.document.module.samples[1]
        again = Sample(wide.name, tuple(value + 1 for value in wide.pcm), *[getattr(wide, name) for name in
                       ("volume", "finetune", "loop_start", "loop_length", "recipe", "bits", "loop_mode", "panning", "relative_note")])
        module = window.document.module
        module.samples[1] = again   # two 16-bit samples differing only in their high bytes must not share a preview
        self.assertEqual(window.cache.sample(module, 1), window.cache.sample(module, 1))
        rendered = window.cache.prepare(window.document.module, window.audible())
        self.assertEqual(rendered.suffix, ".wav")
        self.assertTrue(any(path.suffix == ".xm" for path in window.cache.directory.iterdir()))
        silenced = window.cache.prepare(window.document.module, (False,) * 6)
        self.assertNotEqual(rendered, silenced)
        window.mutes[2].click()   # the window's own re-render of an XM
        self.wait_until(lambda: window._audio_ready and not window._loading_audio)
        self.assertTrue(window.play_button.isEnabled())

    def test_the_jam_plays_xm_notes_at_the_xm_rate(self):
        window = self.window
        window.set_edit_mode(False)
        window.samples.setCurrentRow(1)
        self.go(0, 0)
        window.samples.setCurrentRow(1)
        self.press("z")
        self.assertEqual((window.jam.log[-1]["note"], window.jam.log[-1]["engine"]), ("C-4", "fallback"))
        wavs = window.jam._wavs
        self.assertEqual(len(wavs), 1)
        wav = next(iter(wavs.values()))
        self.assertTrue(wav.startswith(b"RIFF"))
        self.assertEqual(window.jam.note_for("q"), "C-5")
        window.edit_octave.setValue(0)
        self.assertEqual(window.jam.note_for("z"), "C-0")
        self.assertEqual(window.jam.note_for(","), "C-1")
        window.edit_octave.setValue(7)
        self.assertEqual(window.jam.note_for("z"), "C-7")
        self.assertIsNone(window.jam.note_for("p"))   # E-8 is out of the XM's range

    def test_french_names_the_xm_columns_and_the_reason(self):
        window = self.window
        window.set_language("fr")
        self.assertEqual(window.format_label.text(), "XM · 6 VOIES")
        self.assertEqual(window.export_action.text(), "Exporter le XM…")
        self.assertEqual([self.model.headerData(column, Qt.Orientation.Horizontal) for column in range(4)],
                         ["Note", "Ins", "Vol", "Effet"])
        self.assertEqual(window.mutes[5].text(), "Voie 6")
        self.assertIn("MOD 8 bits", window.sample_workshop.editor.apply["gain"].toolTip())
        self.assertIn("panoramique 128", window.sample_info.text())
        self.assertIn("lettres d'effet", self.model.data(self.model.index(0, 0), Qt.ItemDataRole.ToolTipRole))
        self.assertIn("touche 1", window.xm_hint.text())
        window.set_language("en")

    def test_going_back_to_a_mod_restores_the_mod_window(self):
        window = self.window
        self.assertTrue(window.open_module(mod_song(6, "Six")))
        self.assertEqual(window.module_format, "mod")
        self.assertEqual((window.export_action.text(), window.export_button.text()), ("Export MOD…", "Export MOD…"))
        self.assertEqual((window.edit_octave.minimum(), window.edit_octave.maximum(), window.edit_octave.value()), (1, 3, 2))
        self.assertIn("6 CHANNELS", window.format_label.text())
        self.assertTrue(window.format_label.text().endswith("PAL"))
        editor = window.sample_workshop.editor
        self.assertTrue(all(control.isEnabled() for control in (*editor.apply.values(), editor.loop_start, editor.wave)))
        self.assertEqual((editor.finetune.minimum(), editor.finetune.maximum()), (-8, 7))
        self.assertTrue(window.create_panel.add_button.isEnabled())
        self.assertTrue(window.create_panel.pcm.isEnabled())
        self.assertEqual(window.create_panel.pcm.toolTip(), "")
        self.assertFalse(window.xm_hint.isVisible())
        self.assertEqual(self.model.headerData(1, Qt.Orientation.Horizontal), "Smp")
        self.assertIn("mono 8-bit", window.sample_info.text())


class XmJamMixerTests(unittest.TestCase):
    """The keyboard mixer plays an XM sample at the FastTracker II rate (no Qt)."""

    @staticmethod
    def sample(**changes) -> Sample:
        values = dict(name="Lead", pcm=(0, 0) + (100,) * 62, volume=64, finetune=0, loop_start=2, loop_length=62)
        values.update(changes)
        return Sample(**values)

    def test_the_pitch_follows_the_xm_note_relative_note_and_fine_tune(self):
        mixer = JamMixer()
        middle = mixer.note_on(1, "C-4", self.sample(), fmt="xm")
        self.assertAlmostEqual(middle.step, 8363 / mixer.rate)
        self.assertAlmostEqual(mixer.note_on(2, "C-5", self.sample(), fmt="xm").step / middle.step, 2)
        self.assertAlmostEqual(mixer.note_on(3, "C-4", self.sample(relative_note=-12), fmt="xm").step / middle.step, .5)
        self.assertAlmostEqual(mixer.note_on(4, "C-4", self.sample(finetune=128), fmt="xm").step / middle.step, 2 ** (1 / 12))
        self.assertAlmostEqual(mixer.note_on(5, "C-0", self.sample(), fmt="xm").step / middle.step, 2 ** -4)
        self.assertIsNone(mixer.note_on(6, "C-8", self.sample(), fmt="xm"))
        self.assertIsNone(mixer.note_on(6, "C-4", self.sample()))   # a MOD does not know C-4
        self.assertIsNotNone(mixer.note_on(7, "C-2", self.sample()))
        self.assertIsNone(mixer.note_on(8, "C-0", self.sample()))   # nor does it know C-0

    def test_a_16_bit_sample_keeps_its_depth_and_a_ping_pong_loop_runs_back(self):
        mixer = JamMixer()
        eight = mixer.note_on(1, "C-4", self.sample(pcm=(0, 100, 200, 300)), fmt="xm")
        sixteen = mixer.note_on(2, "C-4", self.sample(pcm=(0, 100, 200, 300), bits=16), fmt="xm")
        self.assertEqual(eight.scaled[1] // sixteen.scaled[1], 256)
        self.assertEqual(sixteen.scaled[1], int(100 * 0.8))
        slow = JamMixer(rate=8363)   # one sample per output frame
        pcm = (0, 1000, 2000, 3000)
        ping = slow.note_on(1, "C-4", self.sample(pcm=pcm, loop_start=0, loop_length=4, bits=16, loop_mode="pingpong"), fmt="xm")
        self.assertEqual([value // 800 for value in ping.render(8)], [0, 1, 2, 3, 3, 2, 1, 0])
        forward = slow.note_on(2, "C-4", self.sample(pcm=pcm, loop_start=0, loop_length=4, bits=16), fmt="xm")
        self.assertEqual([value // 800 for value in forward.render(8)], [0, 1, 2, 3, 0, 1, 2, 3])
        again = Voice(3, "C-4", "t", [0, 10, 20, 30], 1.0, 0, 4, pingpong=True)
        self.assertEqual(again.render(10), [0, 10, 20, 30, 30, 20, 10, 0, 0, 10])

    def test_the_fallback_wav_is_a_stereo_render_of_one_note(self):
        wav = render_wav(self.sample(), "C-4", "xm", .1)
        self.assertTrue(wav.startswith(b"RIFF"))
        self.assertGreater(len(wav), 4800 * 4)
        with self.assertRaises(ValidationError):
            render_wav(self.sample(), "C-8", "xm")
        self.assertTrue(render_wav(self.sample(), "C-2", "mod", .1).startswith(b"RIFF"))


@unittest.skipUnless(base.TrackerWindow is not None and find_library(), "PySide6 and libxmp required")
class RealtimeFormatTests(FormatCase):
    """The audio thread plays 8-channel MODs and XMs, with the window's mutes, behind the fake sound card."""

    playback = "realtime"
    make_song = staticmethod(lambda: last_channel_song(8))

    def extra_patches(self):
        rt_tests = importlib.import_module(PACKAGE + "test_desktop_realtime")
        self.fake, self.peak = rt_tests.FakeSink, staticmethod(rt_tests.peak)
        self.fake.instances.clear()
        return [patch.object(desktop_playback, "make_sink", rt_tests.FakeSink),
                patch.object(desktop_playback, "output_available", lambda: True)]

    def written(self, seconds=.4):
        self.wait_until(lambda: bool(self.fake.instances))   # the sink opens in the audio thread when play starts
        before = len(self.fake.instances[-1].writes)
        self.pause(seconds)
        return b"".join(data for _, data in self.fake.instances[-1].writes[before:])

    def open_song(self, module, name):
        path = self.directory / name
        Document(module).save_project(path)
        self.fake.instances.clear()   # the next play opens a new sink: `written` must watch that one
        self.assertTrue(self.window.open_document(path, ask=False))
        self.assertTrue(self.window.rt.wait_idle())

    def test_eight_channels_play_and_the_mutes_reach_the_engine(self):
        window, rt = self.window, self.window.rt
        self.assertIsNotNone(rt)
        self.assertEqual(rt.audible, (True,) * 8)
        self.assertTrue(rt.wait_idle())
        self.assertEqual((rt.core.engine.channels, rt.core.engine.audible), (8, (True,) * 8))
        window.toggle_play()
        self.assertGreater(self.peak(self.written()), 0)
        reloads = rt.reloads
        window.mutes[7].click()   # the only channel that sounds
        self.assertEqual(rt.audible, (True,) * 7 + (False,))
        self.assertTrue(rt.wait_idle())
        self.assertEqual(rt.core.engine.audible, (True,) * 7 + (False,))
        self.written(.3)
        self.assertEqual(self.peak(self.written()), 0)
        window.mutes[7].click()
        window.solos[7].click()
        self.assertEqual(rt.audible, (False,) * 7 + (True,))
        self.assertGreater(self.peak(self.written(.5)), 0)
        window.solos[7].click()
        self.assertEqual((rt.reloads, rt.playing), (reloads, True))   # no reload, no render
        window.stop()
        self.assertIsNotNone(window.rt)

    def test_the_level_meter_and_the_position_follow_eight_channels(self):
        window, rt = self.window, self.window.rt
        window.toggle_play()
        self.pause(.8)
        self.assertTrue(rt.playing)
        milliseconds, marker = rt.heard()
        self.assertGreater(milliseconds, 0)
        self.assertEqual((marker["order"], marker["pattern"]), (0, 0))
        self.assertGreater(max(window.meter.raw_peaks), 0)   # the note of the eighth channel is on the meter
        window.mutes[7].click()
        self.pause(1.0)
        self.assertLess(max(window.meter.raw_peaks), .001)
        self.assertTrue(rt.playing)

    def test_following_the_playhead_does_not_undo_the_sideways_scroll(self):
        window, bar = self.window, self.table.horizontalScrollBar()
        self.assertTrue(window.follow.isChecked())
        bar.setValue(bar.maximum())
        scrolled = bar.value()
        self.assertGreater(scrolled, 0)
        window.toggle_play()
        self.pause(.8)
        self.assertGreater(window.rt.heard()[1]["row"], 0)   # the playhead moved
        self.assertEqual(bar.value(), scrolled)

    def test_opening_a_module_with_another_channel_count_keeps_the_audio_thread_alive(self):
        window, rt = self.window, self.window.rt
        self.open_song(last_channel_song(2), "two.project.json")
        self.assertEqual((rt.core.engine.channels, rt.core.engine.audible, len(window.mutes)), (2, (True, True), 2))
        window.toggle_play()
        self.assertGreater(self.peak(self.written()), 0)
        window.mutes[1].click()
        self.assertTrue(rt.wait_idle())
        self.assertEqual(rt.core.engine.audible, (True, False))
        self.open_song(last_channel_song(6), "six.project.json")   # muted states belong to the old module
        self.assertEqual((rt.core.engine.channels, rt.core.engine.audible), (6, (True,) * 6))
        self.assertIs(window.rt, rt)
        window.toggle_play()
        self.assertGreater(self.peak(self.written()), 0)

    def test_a_file_replaced_by_another_channel_count_reloads_in_place(self):
        window, rt = self.window, self.window.rt
        window.toggle_play()
        window.mutes[2].click()
        self.assertTrue(rt.wait_idle())
        window.apply_external(last_channel_song(4), "reload", [])
        self.assertTrue(rt.wait_idle())
        self.assertEqual((len(window.mutes), rt.core.engine.channels), (4, 4))
        self.assertEqual(rt.core.engine.audible, (True, True, False, True))   # the channels both modules have keep their state
        self.assertIs(window.rt, rt)
        window.undo()
        self.assertTrue(rt.wait_idle())
        self.assertEqual((len(window.mutes), rt.core.engine.channels, len(rt.core.engine.audible)), (8, 8, 8))
        self.assertEqual(rt.core.engine.audible[:4], (True, True, False, True))

    def test_an_xm_plays_in_real_time_with_its_mutes(self):
        window, rt = self.window, self.window.rt
        sample = Sample("Lead", (0, 0) + (100, 0, -100, 0) * 16, 64, 0, 2, 64)
        song = Module("Held XM", [sample], [Pattern("P", {(0, 5): cell("C-4", 1, "000", "xm", 0x40),
                                                          (15, 0): cell(None, 0, "D00", "xm")}, 16)], [0], {}, 6, "xm")
        self.open_song(song, "held.project.json")
        self.assertEqual((rt.core.engine.channels, len(rt.audible)), (6, 6))
        window.toggle_play()
        self.assertGreater(self.peak(self.written()), 0)
        window.mutes[5].click()
        self.assertTrue(rt.wait_idle())
        self.assertEqual(rt.core.engine.audible, (True,) * 5 + (False,))
        self.written(.3)
        self.assertEqual(self.peak(self.written()), 0)
        window.mutes[5].click()
        self.assertGreater(self.peak(self.written(.5)), 0)
        self.assertIs(window.rt, rt)

    def test_the_jam_starts_xm_voices_in_the_audio_thread(self):
        window, rt = self.window, self.window.rt
        sample = Sample("Lead", (0, 0) + (100, 0, -100, 0) * 16, 64, 0, 2, 64, None, 16, "pingpong", 128, 4)
        song = Module("Jam XM", [sample], [Pattern("P", {(0, 0): cell("C-4", 1, "000", "xm")}, 16)], [0], {}, 6, "xm")
        self.open_song(song, "jam.project.json")
        window.set_edit_mode(False)
        self.go(0, 0)
        self.press("z")
        self.assertTrue(rt.wait_idle())
        voices = rt.jam_voices()
        self.assertEqual([(voice["note"], voice["name"]) for voice in voices], [("C-4", "Lead")])
        self.assertEqual(window.jam.log[-1]["engine"], "rt")


if __name__ == "__main__":
    unittest.main()
