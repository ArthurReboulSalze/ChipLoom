"""Keyboard note audition ("jam"): the piano keys play sounds as they are pressed.

The mixer is tested on its own (Qt-free); the window tests send real key events and inspect the voices the audio
thread holds, never the speakers. The real-time engine runs behind the fake sound card of test_desktop_realtime.
"""
from __future__ import annotations

from array import array
import contextlib
import importlib
import shutil
import unittest
from unittest.mock import Mock, patch

try:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication
    from tracker4agents import desktop_playback
except ModuleNotFoundError:
    QApplication = None

from tracker4agents.desktop_mixer import MAX_VOICES, SAMPLE_RATE, JamMixer
from tracker4agents.document import fingerprint
from tracker4agents.model import NOTE_TO_PERIOD, PAL_CLOCK, Module, Pattern, Sample, cell
from tracker4agents.realtime import find_library

PACKAGE = __package__ + "." if __package__ else ""
base = importlib.import_module(PACKAGE + "test_desktop_08")
KEY_PRESS = QEvent.Type.KeyPress if QApplication else None
KEY_RELEASE = QEvent.Type.KeyRelease if QApplication else None
NOMOD = Qt.KeyboardModifier.NoModifier if QApplication else None


def block(value: int, frames: int = 480) -> bytes:
    """A block of stereo int16 PCM holding `value` in both channels."""
    return array("h", [value] * (2 * frames)).tobytes()


def values(pcm: bytes) -> list[int]:
    data = array("h")
    data.frombytes(pcm)
    return list(data)


def tone(volume=64, loop=True, length=66) -> Sample:
    pcm = (0, 0) + (100,) * (length - 2)
    return Sample("Tone", pcm, volume, 0, 2 if loop else 0, length - 2 if loop else 0)


class MixerTests(unittest.TestCase):
    def test_a_voice_plays_at_the_protracker_rate_of_its_note_and_fine_tune(self):
        mixer = JamMixer()
        voice = mixer.note_on(1, "C-2", tone(), "Tone")
        self.assertAlmostEqual(voice.step, PAL_CLOCK / NOTE_TO_PERIOD["C-2"] / SAMPLE_RATE)
        higher = mixer.note_on(2, "C-3", tone())
        self.assertAlmostEqual(higher.step / voice.step, 2, places=1)
        tuned = mixer.note_on(3, "C-2", Sample("T", tone().pcm, 64, 7, 2, 64))
        self.assertAlmostEqual(tuned.step / voice.step, 2 ** (7 / 96))
        self.assertIsNone(mixer.note_on(4, "H-9", tone()))
        self.assertIsNone(mixer.note_on(4, "C-2", Sample("Empty", (), 64)))

    def test_mix_adds_the_voice_to_the_stream_and_saturates_to_int16(self):
        mixer = JamMixer()
        mixer.note_on(1, "C-2", tone(volume=32))
        out = values(mixer.mix(block(1000, 64)))
        voice = 100 * 256 * 32 / 64 * 0.8
        self.assertEqual(len(out), 128)
        self.assertTrue(all(abs(value - (1000 + int(voice))) <= 1 for value in out[40:]))   # both channels, once past the two leading zero bytes
        self.assertEqual(out[0::2], out[1::2])
        loud = JamMixer()
        for key in range(4):
            loud.note_on(key, "C-2", tone())
        top = values(loud.mix(block(30000, 64)))
        self.assertEqual(max(top), 32767)
        negative = JamMixer()
        negative.note_on(1, "C-2", Sample("Neg", (0, 0) + (-128,) * 64, 64, 0, 2, 64))
        for key in range(2, 6):
            negative.note_on(key, "C-2", Sample("Neg", (0, 0) + (-128,) * 64, 64, 0, 2, 64))
        self.assertEqual(min(values(negative.mix(block(-30000, 64)))), -32768)

    def test_silence_in_means_the_voices_alone_and_no_voices_means_the_block_untouched(self):
        mixer = JamMixer()
        quiet = block(5, 32)
        self.assertEqual(mixer.mix(quiet), quiet)
        mixer.note_on(1, "C-2", tone())
        self.assertGreater(max(values(mixer.mix(block(0, 100)))), 1000)
        self.assertEqual(len(mixer.mix(block(0, 100))), 400)

    def test_releasing_a_looped_voice_fades_it_out_in_about_ten_milliseconds_and_a_one_shot_plays_on(self):
        mixer = JamMixer()
        mixer.note_on(1, "C-2", tone(loop=True))
        mixer.note_on(2, "C-3", tone(loop=False, length=4000))
        mixer.mix(block(0, 256))
        self.assertEqual(mixer.note_off(1), 1)
        self.assertEqual(mixer.note_off(2), 0)                  # a one-shot is not released
        fade = values(mixer.mix(block(0, 480)))[0::2]
        self.assertEqual(sorted(item["key"] for item in mixer.snapshot()), [2])    # the looped voice is gone
        self.assertGreater(fade[0], 0)
        self.assertEqual(mixer.snapshot()[0]["note"], "C-3")
        for _ in range(40):
            mixer.mix(block(0, 480))
        self.assertEqual(mixer.snapshot(), [])                  # and the one-shot ended by itself

    def test_the_fade_is_a_ramp_to_silence(self):
        mixer = JamMixer()
        mixer.note_on(1, "C-2", tone(loop=True))
        mixer.mix(block(0, 100))
        mixer.note_off(1)
        ramp = values(mixer.mix(block(0, 480)))[0::2]
        self.assertGreater(ramp[0], 10000)
        self.assertLess(abs(ramp[-1]), ramp[0] // 50)
        self.assertTrue(all(a >= b - 400 for a, b in zip(ramp, ramp[1:])) or ramp[0] > ramp[-1])

    def test_polyphony_keeps_the_newest_voices_and_steals_the_oldest(self):
        self.assertGreaterEqual(MAX_VOICES, 4)
        mixer = JamMixer()
        for key in range(MAX_VOICES):
            mixer.note_on(key, "C-2", tone())
        self.assertEqual(len(mixer.snapshot()), MAX_VOICES)
        mixer.note_on(99, "D-2", tone())
        keys = [item["key"] for item in mixer.snapshot()]
        self.assertEqual(len(keys), MAX_VOICES)
        self.assertNotIn(0, keys)                              # the oldest went
        self.assertEqual(keys[-1], 99)

    def test_scaled_samples_are_cached_per_sample_and_volume(self):
        mixer = JamMixer()
        first = mixer.note_on(1, "C-2", tone(volume=40))
        second = mixer.note_on(2, "E-2", tone(volume=40))
        third = mixer.note_on(3, "C-2", tone(volume=20))
        self.assertIs(first.scaled, second.scaled)
        self.assertIsNot(first.scaled, third.scaled)


def song() -> Module:
    loud = Sample("Loud", (0, 0) + (120, 0, -120, 0) * 16, 64, 0, 2, 64)               # looped, slot 1
    long_shot = Sample("Shot", (0, 0) + (40, -40) * 10000, 40)                          # one-shot, 20002 bytes, slot 2
    cells = {(0, 0): cell("C-2", 1), (1, 0): cell("E-2", 2)}
    return Module("Jam", [loud, long_shot], [Pattern(name="Intro", cells=cells)], [0])


class JamCase(base.WindowCase):
    make_song = staticmethod(song)

    def key(self, widget, kind, key, text="", repeat=False, modifiers=NOMOD):
        QApplication.sendEvent(widget, QKeyEvent(kind, key, modifiers, text, repeat))

    def tap(self, widget, text, key=None, hold=False):
        key = ord(text.upper()) if key is None else key
        self.key(widget, KEY_PRESS, key, text)
        if not hold:
            self.key(widget, KEY_RELEASE, key, text)

    def voices(self):
        self.assertTrue(self.window.rt.wait_idle())
        return self.window.rt.jam_voices()


@unittest.skipUnless(base.TrackerWindow is not None and find_library(), "PySide6 and libxmp required")
class RealtimeJamTests(JamCase):
    playback = "realtime"

    def extra_patches(self):
        rt_tests = importlib.import_module(PACKAGE + "test_desktop_realtime")
        self.fake = rt_tests.FakeSink
        self.fake.instances.clear()
        return [patch.object(desktop_playback, "make_sink", rt_tests.FakeSink),
                patch.object(desktop_playback, "output_available", lambda: True)]

    def setUp(self):
        super().setUp()
        window = self.window
        self.assertIsNotNone(window.rt)
        window.keyboard_combo.setCurrentIndex(window.keyboard_combo.findData("qwerty"))
        window.edit_octave.setValue(2)
        window.edit_step.setValue(0)
        window.samples.setCurrentRow(0)
        window.table.setFocus()
        window.table.setCurrentIndex(self.model.index(4, 0))
        window.cache.prepare = Mock(side_effect=AssertionError("a WAV was rendered"))

    def played(self):
        return [(item["note"], item["name"], item["source"]) for item in self.window.jam.log]

    # --- the pattern ----------------------------------------------------------------------
    def test_edit_mode_enters_the_note_and_plays_it_with_the_sample_it_writes(self):
        window, table = self.window, self.window.table
        window.set_edit_mode(True)
        before = window.document.revision
        self.tap(table, "z", hold=True)
        self.assertEqual(window.document.module.patterns[0].get(4, 0).note, "C-2")
        self.assertEqual(window.document.module.patterns[0].get(4, 0).sample, 1)
        self.assertEqual(window.document.revision, before + 1)
        self.assertEqual(self.played(), [("C-2", "Loud", "pattern")])
        voices = self.voices()
        self.assertEqual([(item["note"], item["name"], item["looped"]) for item in voices], [("C-2", "Loud", True)])
        self.assertFalse(window.rt.playing)                       # the song is stopped: the sink runs for the voice alone
        self.pause(.15)
        written = b"".join(chunk for _, chunk in self.fake.instances[-1].writes)
        self.assertGreater(max(values(written)), 1000)
        self.key(table, KEY_RELEASE, ord("Z"), "z")

    def test_trying_notes_by_ear_on_one_cell_leaves_the_last_one_entered(self):
        window, table = self.window, self.window.table
        window.set_edit_mode(True)
        for text in ("z", "x", "c"):
            self.tap(table, text)
        self.assertEqual(window.document.module.patterns[0].get(4, 0).note, "E-2")
        self.assertEqual([item[0] for item in self.played()], ["C-2", "D-2", "E-2"])
        window.undo()
        self.assertEqual(window.document.module.patterns[0].get(4, 0).note, "D-2")

    def test_the_instrument_chosen_in_the_list_is_the_one_entered_and_heard(self):
        window, table = self.window, self.window.table
        window.set_edit_mode(True)
        window.samples.setCurrentRow(1)
        self.tap(table, "z")
        self.assertEqual(window.document.module.patterns[0].get(4, 0).sample, 2)
        self.assertEqual(self.played(), [("C-2", "Shot", "pattern")])

    def test_without_edit_mode_the_keys_only_play_and_write_nothing(self):
        window, table = self.window, self.window.table
        window.set_edit_mode(False)
        state = (fingerprint(window.document.module), window.document.revision)
        self.tap(table, "z", hold=True)
        self.tap(table, "g", hold=True)
        self.assertEqual(self.played(), [("C-2", "Loud", "pattern"), ("F#2", "Loud", "pattern")])
        self.assertEqual(len(self.voices()), 2)
        self.assertEqual((fingerprint(window.document.module), window.document.revision), state)
        self.assertFalse(window.document.dirty)
        self.assertEqual(table.currentIndex().row(), 4)           # and the cursor stays
        before = len(window.jam.log)
        self.tap(table, " ", key=int(Qt.Key.Key_Space))           # Space is not a note
        self.assertEqual(len(window.jam.log), before)
        self.tap(table, "é")                                      # nor is a key without a note on this layout
        self.assertEqual(len(window.jam.log), before)

    def test_the_cells_own_sample_is_used_when_no_instrument_is_chosen(self):
        window, table = self.window, self.window.table
        window.samples.setCurrentRow(-1)
        self.assertEqual(window.instrument_slot(), 0)
        window.table.setCurrentIndex(self.model.index(1, 0))      # that cell holds sample 2 (and selecting it selects it)
        self.tap(table, "z")
        self.assertEqual(self.played(), [("C-2", "Shot", "pattern")])

    def test_releasing_a_looped_note_stops_it_and_a_one_shot_plays_on(self):
        window, table = self.window, self.window.table
        self.tap(table, "z", hold=True)
        self.assertEqual(len(self.voices()), 1)
        self.key(table, KEY_RELEASE, ord("Z"), "z")
        self.pause(.25)
        self.assertEqual(self.voices(), [])                       # the 10 ms fade is over
        window.samples.setCurrentRow(1)
        self.tap(table, "x", hold=True)
        self.key(table, KEY_RELEASE, ord("X"), "x")
        self.pause(.25)
        self.assertEqual([item["name"] for item in self.voices()], ["Shot"])   # a one-shot is left to finish
        window.rt.jam_clear()
        self.assertEqual(self.voices(), [])

    def test_the_sink_closes_when_the_last_note_has_sounded(self):
        window, table = self.window, self.window.table
        self.tap(table, "z")
        self.pause(.4)
        self.assertTrue(window.rt.wait_idle())
        self.wait_until(lambda: not window.rt.jam_active, 5)
        self.assertFalse(window.rt.core.jamming)

    def test_key_auto_repeat_is_ignored(self):
        window, table = self.window, self.window.table
        self.tap(table, "z", hold=True)
        for _ in range(5):
            self.key(table, KEY_PRESS, ord("Z"), "z", repeat=True)
            self.key(table, KEY_RELEASE, ord("Z"), "z", repeat=True)    # a repeat is a release followed by a press
        self.assertEqual(len(window.jam.log), 1)
        self.assertEqual(len(self.voices()), 1)
        self.assertFalse(self.voices()[0]["releasing"])
        window.set_edit_mode(True)
        window.jam.release_all()
        revision = window.document.revision
        self.tap(table, "z", hold=True)
        for _ in range(3):
            self.key(table, KEY_PRESS, ord("Z"), "z", repeat=True)
        self.assertEqual(window.document.revision, revision + 1)        # entered once
        self.assertEqual(len(window.jam.log), 2)

    def test_at_least_four_notes_sound_together_and_the_oldest_is_stolen_beyond_the_limit(self):
        window, table = self.window, self.window.table
        texts = "zxcvbnm,"
        for index, text in enumerate(texts[:4]):
            self.tap(table, text, hold=True)
        self.assertEqual([item["note"] for item in self.voices()], ["C-2", "D-2", "E-2", "F-2"])
        for text in texts[4:]:
            self.tap(table, text, hold=True)
        voices = self.voices()
        self.assertEqual(len(voices), MAX_VOICES)
        self.assertEqual([item["note"] for item in voices], ["E-2", "F-2", "G-2", "A-2", "B-2", "C-3"][-MAX_VOICES:])
        self.assertNotIn("C-2", [item["note"] for item in voices])
        window.jam.release_all()

    def test_jam_notes_join_a_playing_song(self):
        window, table = self.window, self.window.table
        window.toggle_play()
        self.assertTrue(window.rt.playing)
        self.pause(.2)
        self.tap(table, "z", hold=True)
        self.assertEqual(len(self.voices()), 1)
        self.pause(.3)
        self.assertTrue(window.rt.playing)
        window.jam.release_all()

    def test_the_level_meter_and_the_window_volume_follow_the_jam_audio(self):
        window, table = self.window, self.window.table
        window.volume.setValue(50)
        self.tap(table, "z", hold=True)
        self.pause(.3)
        window._sync_position()
        self.assertGreater(window.meter.buffer_count, 0)
        self.assertGreater(max(window.meter.raw_peaks), 0)
        self.assertAlmostEqual(self.fake.instances[-1].volume, 0.5)
        window.jam.release_all()

    # --- layouts and octave -------------------------------------------------------------------------------
    def test_azerty_and_the_octave_keys(self):
        window, table = self.window, self.window.table
        window.keyboard_combo.setCurrentIndex(window.keyboard_combo.findData("azerty"))
        self.assertEqual(window.keys_hint.text(), "Octave 2 · Keyboard AZERTY")
        self.tap(table, "w")                                      # AZERTY bottom row starts with W
        self.tap(table, "a")                                      # the top row starts an octave higher
        self.assertEqual([item[0] for item in self.played()], ["C-2", "C-3"])
        self.key(table, KEY_PRESS, int(Qt.Key.Key_F3), "")
        self.key(table, KEY_RELEASE, int(Qt.Key.Key_F3), "")
        self.assertEqual(window.edit_octave.value(), 3)
        self.assertEqual(window.keys_hint.text(), "Octave 3 · Keyboard AZERTY")
        self.tap(table, "w")
        self.assertEqual(self.played()[-1][0], "C-3")
        self.tap(table, "a")                                      # C-4 does not exist: nothing plays
        count = len(window.jam.log)
        self.tap(table, "a")
        self.assertEqual(len(window.jam.log), count)
        window.keyboard_combo.setCurrentIndex(window.keyboard_combo.findData("qwerty"))
        self.assertEqual(window.keys_hint.text(), "Octave 3 · Keyboard QWERTY")
        window.set_language("fr")
        self.assertEqual(window.keys_hint.text(), "Octave 3 · Clavier QWERTY")
        self.assertIn("F1-F3", window.keys_hint.toolTip())

    # --- the other tabs -----------------------------------------------------------------------------------------
    def focus(self, widget):
        return contextlib.nullcontext()          # the keys are sent to the widget itself: that is what holds the focus

    def test_song_samples_tab_plays_the_selected_sample_and_leaves_the_song_alone(self):
        window = self.window
        window.samples.setCurrentRow(1)
        state = (fingerprint(window.document.module), window.document.revision)
        with self.focus(window.samples):
            self.tap(window.samples, "x", hold=True)
            self.key(window.samples, KEY_PRESS, int(Qt.Key.Key_F1), "")
        self.assertEqual(self.played(), [("D-2", "Shot", "samples")])
        self.assertEqual(window.edit_octave.value(), 1)
        self.assertEqual((fingerprint(window.document.module), window.document.revision), state)
        self.assertEqual(window.samples.currentRow(), 1)           # the list did not type-ahead

    def test_text_fields_keep_their_keys(self):
        window = self.window
        for widget in (window.title_edit, window.sample_workshop.editor.volume, window.create_panel.name,
                       window.instrument_panel.search, window.instrument_panel.phrase):
            with self.focus(widget):
                self.tap(widget, "z")
        self.assertEqual(window.jam.log, [])

    def test_the_tab_bar_counts_as_the_page_it_shows(self):
        window = self.window
        window.sample_tabs.setCurrentIndex(2)                       # Create
        with self.focus(window.sample_tabs.tabBar()):
            self.tap(window.sample_tabs.tabBar(), "z")
        self.assertEqual(self.played()[-1][2], "create")
        window.sample_tabs.setCurrentIndex(4)                       # Agent: no sound there
        count = len(window.jam.log)
        with self.focus(window.sample_tabs.tabBar()):
            self.tap(window.sample_tabs.tabBar(), "z")
        self.assertEqual(len(window.jam.log), count)

    def test_the_library_tab_plays_the_selected_entry(self):
        window = self.window
        browser = window.sample_browser
        with self.focus(browser.results):
            self.tap(browser.results, "z")                          # nothing selected: silence
            self.assertEqual(window.jam.log, [])
            browser.entry = {"id": "SMP-0001", "name": "Library kick"}
            browser._jam = Sample("Library kick", (0, 0) + (90, 30, -30, -90) * 10, 48)
            self.tap(browser.results, "x")
        self.assertEqual(self.played(), [("D-2", "Library kick", "library")])

    def test_the_create_tab_plays_the_recipe_being_edited(self):
        window, create = self.window, self.window.create_panel
        window.sample_tabs.setCurrentIndex(2)
        create.timer.stop()
        create.kind.setCurrentIndex(create.kind.findData("wave"))
        create.set_value("frequency", 440)
        create.name.setText("Made here")
        create.timer.stop()
        with self.focus(create.kind):
            self.tap(create.kind, "c")
        self.assertEqual(self.played(), [("E-2", "Made here", "create")])
        with self.focus(create.slot):
            self.tap(create.slot, "v")
        self.assertEqual(self.played()[-1], ("F-2", "Made here", "create"))
        create.kind.setCurrentIndex(create.kind.findData("kick"))
        create.timer.stop()
        with self.focus(create.kind):
            self.tap(create.kind, "v")
        self.assertEqual(self.played()[-1][1], "Made here")         # the one-shot kick is a sample too
        self.assertEqual(window.document.revision, 0)

    def test_the_instrument_panel_plays_the_selected_instrument(self):
        window, panel = self.window, self.window.instrument_panel
        panel.set_folder(self.directory / "instruments")
        window.samples.setCurrentRow(0)
        panel.name.setText("Buzz")
        panel.save_instrument()
        panel.list.setCurrentRow(0)
        with self.focus(panel.list):
            self.tap(panel.list, "b", hold=True)
        self.assertEqual(self.played(), [("G-2", "Buzz", "instruments")])
        self.assertEqual([item["name"] for item in self.voices()], ["Buzz"])
        with self.focus(panel.list):
            self.key(panel.list, KEY_RELEASE, ord("B"), "b")


@unittest.skipUnless(base.TrackerWindow is not None and shutil.which("ffmpeg"), "PySide6 and FFmpeg required")
class FallbackJamTests(JamCase):
    """Without the real-time engine the sample player plays one rendered note at a time."""

    def setUp(self):
        super().setUp()
        window = self.window
        self.assertIsNone(window.rt)
        window.keyboard_combo.setCurrentIndex(window.keyboard_combo.findData("qwerty"))
        window.edit_octave.setValue(2)
        window.samples.setCurrentRow(0)
        window.table.setFocus()
        window.table.setCurrentIndex(self.model.index(4, 0))

    def test_keys_play_through_the_sample_player_one_note_at_a_time(self):
        window, table = self.window, self.window.table
        window.set_edit_mode(False)
        state = fingerprint(window.document.module)
        with patch.object(window, "audition_wav", wraps=window.audition_wav) as audition:
            self.tap(table, "z", hold=True)
            self.assertEqual(self.played_engines(), ["fallback"])
            first = window.sample_player.source()
            self.assertTrue(first.toLocalFile().endswith(".wav"))
            self.tap(table, "x", hold=True)
            self.assertEqual(audition.call_count, 2)
            self.assertNotEqual(window.sample_player.source(), first)    # monophonic: the new note replaces it
            self.assertEqual(fingerprint(window.document.module), state)
            with patch.object(window.sample_player, "stop") as stop:
                self.key(table, KEY_RELEASE, ord("X"), "x")                # a looped sample stops with its key
            stop.assert_called_once()
            self.key(table, KEY_RELEASE, ord("Z"), "z")
        self.tap(table, "z")                                              # the same note again comes from the cache
        self.assertEqual(len(window.jam._wavs), 2)

    def test_edit_mode_still_enters_the_note(self):
        window, table = self.window, self.window.table
        window.set_edit_mode(True)
        self.tap(table, "z")
        self.assertEqual(window.document.module.patterns[0].get(4, 0).note, "C-2")
        self.assertEqual(self.played_engines(), ["fallback"])

    def test_a_one_shot_is_not_cut_by_its_key_release(self):
        window, table = self.window, self.window.table
        window.samples.setCurrentRow(1)
        self.tap(table, "z", hold=True)
        with patch.object(window.sample_player, "stop") as stop:
            self.key(table, KEY_RELEASE, ord("Z"), "z")
        stop.assert_not_called()

    def test_the_other_tabs_use_the_fallback_too(self):
        window = self.window
        self.tap(window.samples, "c")
        self.assertEqual((self.window.jam.log[-1]["source"], self.window.jam.log[-1]["engine"]), ("samples", "fallback"))

    def played_engines(self):
        return [item["engine"] for item in self.window.jam.log]


if __name__ == "__main__":
    unittest.main()
