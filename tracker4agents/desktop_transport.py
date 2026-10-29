"""Song and sample playback in the ChipLoom window: the transport and its two engines.

`TransportMixin` drives playback through the real-time libxmp transport (`window.rt`, a `RealtimeTransport` from
`desktop_playback`) when it can run, otherwise through rendered WAVs played by QMediaPlayer (`prepare_audio`,
`_media_status`, looping). It owns play, pause, stop and seek, order selection, the playhead and level meter
(`_sync_position`, called by window.timer), the take heard in place of the document (`listen_to`), sample auditions
(`play_sample`, `audition_wav`), and the real-time switch and audio buffer (`_setup_realtime`, `set_realtime`,
`set_audio_buffer`). Relies on: window.player/sample_player/output/sample_output, window.cache, window.plan/times,
window.monitor_module, the audio state flags set in `TrackerWindow.__init__` (_audio_token, _loading_audio,
_audio_ready, _await_media, _want_play, _resume_ms, _last_position, _loop_epoch, _debounce_play, _rt_notice),
the transport widgets, `submit`, `audible`, `message` and `t`.
"""

from __future__ import annotations

import bisect
import hashlib
import os
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtMultimedia import QMediaPlayer

from . import project
from .desktop_playback import BUFFER_CHOICES, LIBXMP_HINT, RealtimeTransport, unavailable_reason, valid_buffer
from .desktop_widgets import clock, media_call
from .realtime import RealtimeError


class TransportMixin:
    """Playback, seeking and the real-time engine (see the module docstring)."""
    def prepare_audio(self, play=False, position=0):
        if not self.document:
            return
        self.debounce.stop()
        self._audio_token += 1
        if self.rt is not None:
            try:
                self.rt.prepare(play, position)
            except RealtimeError as exc:
                self._realtime_failed(exc)
            else:
                self._loading_audio = self._await_media = self._want_play = False
                self._audio_ready = True
                self._resume_ms = position
                self.play_button.setEnabled(True)
                self.seek.setMaximum(round(self.plan["duration_seconds"] * 1000))
                self._transport_labels()
                self.message('Ready to play')
                return
        token = self._audio_token
        self._loading_audio, self._audio_ready, self._await_media = True, False, False
        self._last_position = -1  # the playhead jumps while a new render loads; that is not a seek
        self._want_play, self._resume_ms = play, position
        self.meter.reset()
        media_call(self.player, "stop")
        media_call(self.player, "setSource", QUrl())
        self.play_button.setText(self.t('Preparing…'))
        self.play_button.setEnabled(False)
        self.message('Preparing playback…')
        module, audible = self.listening_module(), self.audible()

        def operation():
            return self.cache.prepare(module, audible) if token == self._audio_token else None

        def success(path):
            if token != self._audio_token or path is None:
                return
            self._await_media = True
            media_call(self.player, "setSource", QUrl.fromLocalFile(str(path)))

        def failure(text):
            if token == self._audio_token:
                self._loading_audio = False
                self.play_button.setText(self.t('Play'))
                self.play_button.setEnabled(True)
                self.message("Audio unavailable: {detail}", True, detail=text)

        self.submit(operation, success, failure)

    def _media_status(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia and self.loop.isChecked() and self._audio_ready:
            # Let the backend finish its end-of-stream transition before seeking.
            # Reentrant restart here can leave Qt's renderer blocked on stop().
            token, epoch = self._audio_token, self._loop_epoch
            QTimer.singleShot(0, lambda: self._restart_loop(token, epoch))
            return
        if self._await_media and status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia):
            self._await_media = False
            self._loading_audio, self._audio_ready = False, True
            self.player.setPosition(min(self._resume_ms, max(0, self.player.duration() - 1)))
            self.play_button.setEnabled(True)
            self._transport_labels()
            self.message(self._rt_notice or 'Ready to play')
            self._rt_notice = None  # the real-time notice is shown once
            if self._want_play:
                self.player.play()

    def _restart_loop(self, token, epoch):
        if (token == self._audio_token and epoch == self._loop_epoch
                and self._audio_ready and self.loop.isChecked()
                and self.player.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia):
            self.meter.reset()
            self.player.setPosition(round(self.plan["loop_start_seconds"] * 1000))
            self.player.play()

    def _media_error(self, text):
        self._loading_audio = self._await_media = False
        self._audio_ready = False
        self.play_button.setText(self.t('Play'))
        self.play_button.setEnabled(self.document is not None)
        self.message("Playback failed: {detail}", True, detail=text)

    def _transport_labels(self):
        self.play_button.setText(self.t("Preparing…" if self._loading_audio else
            "Pause" if self.is_playing() else "Play"))

    def _volume(self, volume):
        self.output.setVolume(volume / 100)
        self.sample_output.setVolume(volume / 100)
        if self.rt is not None:
            self.rt.set_volume(volume / 100)

    def toggle_play(self):
        if not self.document or self._loading_audio:
            return
        self.sample_browser.cancel_preview()
        media_call(self.sample_player, "stop")
        if self.rt is not None:
            self.rt.pause() if self.rt.playing else self.rt.play()
        elif not self._audio_ready:
            self.prepare_audio(True, self._resume_ms)
        elif self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def stop(self):
        self.sample_browser.cancel_preview()
        self._loop_epoch += 1
        self._want_play = False
        self._resume_ms = 0
        media_call(self.player, "stop")
        if self.rt is not None:
            self.rt.stop()
        media_call(self.sample_player, "stop")
        self.meter.reset()

    def seek_to(self, milliseconds):
        self._loop_epoch += 1
        self.meter.reset()
        self._resume_ms = milliseconds
        if self.rt is not None:
            self.rt.seek_ms(milliseconds)
        elif self._audio_ready:
            self.player.setPosition(milliseconds)

    def seek_row(self, row):
        target = next((entry for entry in self.plan["timeline"] if entry["order"] == self.current_order and entry["row"] == row), None)
        if target:
            self.seek_to(round(target["seconds"] * 1000))

    def select_order(self, order):
        if self._refreshing or not self.document or order < 0:
            return
        self.current_order = order
        self.pattern_model.refresh(self.document.module.orders[order])
        self.order_editor.refresh()
        self.live.context_changed()
        target = next((entry for entry in self.plan["timeline"] if entry["order"] == order), None)
        if target:
            self.seek_to(round(target["seconds"] * 1000))
        else:
            self.message("This order is not reached in the module's playback cycle.")

    def _sync_position(self):
        playing = self.is_playing()
        active = (playing or self.sample_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
                  or (self.rt is not None and self.rt.jam_active))
        marker = None
        if self.rt is not None:
            levels = self.rt.heard_levels()   # the song's, or the notes played from the keyboard
            if levels:
                self.meter.feed_levels(*levels)
        for player, wav in self.wav_levels:
            if player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                levels = wav.at(player.source().toLocalFile(), player.position())
                if levels:
                    self.meter.feed_levels(*levels)
                break
        self.meter.tick(active, self.volume.value() / 100)
        if not self.document or self._loading_audio:
            return
        if self.rt is not None:
            milliseconds, marker = self.rt.heard()
            duration = round(self.plan["duration_seconds"] * 1000)
        else:
            milliseconds, duration = self.player.position(), self.player.duration()
        if not self.seek.isSliderDown():
            self.seek.setValue(milliseconds)
        self.position_label.setText(f"{clock(milliseconds)} / {clock(duration)}")
        if not self.times:
            return
        # In real-time mode the row comes from the marker of the audio being heard, not from the clock.
        entry = marker or self.plan["timeline"][max(0, bisect.bisect_right(self.times, milliseconds / 1000) - 1)]
        # Follow the playhead while it moves (playing or seeking), but let a paused view be browsed
        # and edited: order edits and agent selections must not be pulled back to the playhead.
        moving = (self._last_position >= 0 and milliseconds != self._last_position) or playing
        self._last_position = milliseconds
        if self.follow.isChecked() and moving and entry["order"] != self.current_order:
            self._refreshing = True
            self.current_order = entry["order"]
            self.orders.setCurrentIndex(self.current_order)
            self.pattern_model.refresh(entry["pattern"])
            self.order_editor.refresh()
            self._refreshing = False
        if entry["pattern"] == self.pattern_model.pattern:
            self.pattern_model.highlight(entry["row"])
            if self.follow.isChecked() and playing:
                self.table.scroll_to_row(entry["row"])   # vertically only: a grid scrolled sideways stays where it is

    def play_sample(self):
        if not self.document or not self.samples.currentItem():
            return
        try:
            index = self.samples.currentItem().data(Qt.ItemDataRole.UserRole)
            path = self.cache.sample(self.document.module, index)
            self.meter.reset()
            self.pause_playback()
            media_call(self.sample_player, "setSource", QUrl.fromLocalFile(str(path)))
            self.sample_player.play()
        except (OSError, ValueError, RuntimeError) as exc:
            self.message(str(exc), True)

    def audition_wav(self, wav: bytes) -> Path:
        """Play a short in-memory WAV (an edit preview, a recipe audition) without touching the song."""
        path = self.cache.directory / f"audition-{hashlib.sha1(wav).hexdigest()[:20]}.wav"
        if not path.is_file():
            project.atomic_bytes(path, wav)
        self.meter.reset()
        self.pause_playback()
        media_call(self.sample_player, "stop")
        media_call(self.sample_player, "setSource", QUrl.fromLocalFile(str(path)))
        self.sample_player.play()
        return path

    # --- real-time playback -------------------------------------------------------------
    def _setup_realtime(self):
        """Use the libxmp transport when it can run, otherwise the rendered WAV path (and say why, once)."""
        wanted = self.state.values.get("realtime") is not False
        reason = unavailable_reason(wanted)
        self.rt = None
        if reason is None:
            try:
                self.rt = RealtimeTransport(self, latency_ms=dict(BUFFER_CHOICES)[self.audio_buffer])
            except RealtimeError:
                reason = "libxmp"
        if self.rt is not None:
            self.rt.state_changed.connect(self._transport_labels)
            self.rt.state_changed.connect(self.live.context_changed)
            self.rt.finished.connect(self.meter.reset)
            self.rt.failed.connect(self._rt_failed)
            self.rt.set_volume(self.volume.value() / 100)
        self._rt_notice = {"libxmp": LIBXMP_HINT,
                           "output": "Real-time playback needs an audio output device: playing rendered audio instead."
                           }.get(reason)
        forced = os.environ.get("CHIPLOOM_PLAYBACK", "").lower() == "rendered"
        self.realtime_action.blockSignals(True)
        self.realtime_action.setChecked(self.rt is not None)
        self.realtime_action.setEnabled(not forced)
        self.realtime_action.blockSignals(False)
        self._rt_unavailable = reason
        self._update_buffer_ui()

    def set_realtime(self, on: bool):
        """Switch between real-time (libxmp) and rendered (WAV + media player) playback."""
        self.state.values["realtime"] = bool(on)
        if self.document:
            self.stop()
        if self.rt is not None:
            self.rt.shutdown()
            self.rt.deleteLater()
        self._setup_realtime()
        self._save_preferences()
        if self.document:
            self.prepare_audio(False, 0)

    def _realtime_failed(self, exc):
        """libxmp refused the module: finish this session on the rendered path."""
        if self.rt is not None:
            self.rt.shutdown()
            self.rt.deleteLater()
            self.rt = None
        self.realtime_action.blockSignals(True)
        self.realtime_action.setChecked(False)
        self.realtime_action.blockSignals(False)
        self._rt_notice = "Real-time playback failed ({detail}): playing rendered audio instead."
        self._rt_notice = self.t(self._rt_notice, detail=exc)
        self._update_buffer_ui()
        self.play_button.setToolTip(self._rt_notice)

    def _rt_failed(self, message: str, fatal: bool):
        """The audio thread reported a problem: a module libxmp cannot load ends real-time playback."""
        if fatal and self.rt is not None:
            self._realtime_failed(message)
            self.prepare_audio(False, self._resume_ms)
        elif not fatal:
            self.message("Real-time playback failed: {detail}", True, detail=message)

    def set_audio_buffer(self, key: str):
        """Resize the audio queue and the sink now; a playing song continues on the row being heard."""
        self.audio_buffer = valid_buffer(key)
        if self.rt is not None:
            self.rt.set_latency(dict(BUFFER_CHOICES)[self.audio_buffer])
        self._update_buffer_ui()
        self._save_preferences()

    def _update_buffer_ui(self):
        """Check the current choice and show the latency in the tooltips."""
        for key, milliseconds in BUFFER_CHOICES:
            action = self.buffer_actions[key]
            action.blockSignals(True)
            action.setChecked(key == self.audio_buffer)
            action.blockSignals(False)
            action.setToolTip(self.t("Audio latency about {ms} ms. A larger buffer rides out window moves and heavy "
                                     "redraws without crackling, but sound reacts a little later to edits.", ms=milliseconds))
        milliseconds = dict(BUFFER_CHOICES)[self.audio_buffer]
        if self.rt is not None:
            self.play_button.setToolTip(self.t("Real-time playback (libxmp) · audio buffer {ms} ms", ms=milliseconds))
        else:
            self.play_button.setToolTip(self.t(self._rt_notice) if self._rt_notice else "")

    def is_playing(self) -> bool:
        if self.rt is not None:
            return self.rt.playing
        return self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def playback_ms(self) -> int:
        return self.rt.position_ms() if self.rt is not None else self.player.position()

    def listening_module(self):
        """What the transport plays: the take being compared, otherwise the document's module."""
        return self.monitor_module if self.monitor_module is not None else self.document.module

    def listen_to(self, module=None):
        """Hear `module` (a take) at the current song position, or the document again with `None`.
        Playback state and position are kept; the document is never touched."""
        if module is self.monitor_module:
            return
        playing = self._want_play if self._loading_audio else self.is_playing()
        position = self._resume_ms if self._loading_audio else self.playback_ms()
        self.monitor_module = module
        media_call(self.sample_player, "stop")
        if self.rt is not None:
            self.rt.reload()   # the audio thread swaps the module in on the row being played
        else:
            self.prepare_audio(playing, position)
        self._update_title()

    def pause_playback(self):
        """Pause the song (used before a sample audition or a proposal listening)."""
        if self.rt is not None:
            self.rt.pause()
        else:
            self.player.pause()

    def start_playback(self):
        if not self.document:
            return
        if self._loading_audio:
            self._want_play = True
        elif not self.is_playing():
            self.toggle_play()

    def _debounced_audio(self):
        play, self._debounce_play = self._debounce_play, False
        position = self.player.position() if play and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState \
            else self._resume_ms
        self.prepare_audio(play, position)
