"""Regressions from the first external Hermes composition session."""
import copy
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import wave
from contextlib import redirect_stdout, redirect_stderr

from tracker4agents import audio, cli, demo, mod, project
from tracker4agents.model import Module, Pattern, Sample, ValidationError, cell


class AgentDiagnosticsTests(unittest.TestCase):
    def invoke(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_collision_identifies_both_writers_even_for_empty_first_cell(self):
        score = project.to_dict(demo.create())
        score['patterns'][0]['events'] = [
            {'row': 56, 'channel': 0},
            {'row': 56, 'channel': 0, 'note': 'A-2', 'sample': 2, 'effect': 'C20'},
        ]
        with self.assertRaisesRegex(ValidationError, r'events\[0\].*--- 00 000.*events\[1\].*A-2 02 C20'):
            project.from_dict(score)

    def test_accidental_note_explains_correct_syntax(self):
        with self.assertRaisesRegex(ValidationError, 'G#3, A#2'):
            cell('G#-3')
        self.assertEqual(cell('G#3').note, 'G#3')

    def test_estimator_and_long_project_warning_agree(self):
        code, out, err = self.invoke('estimate', '--orders', '18')
        self.assertEqual(code, 0, err)
        estimate = json.loads(out)
        self.assertEqual(estimate['duration_seconds'], 138.24)
        self.assertEqual(estimate['seconds_per_order'], 7.68)
        module = Module('Long', [Sample('', ())], [Pattern()], [0] * 18)
        description = cli.describe(module)
        self.assertEqual(description['duration_seconds'], estimate['duration_seconds'])
        self.assertIn('--seconds', description['warnings'][0])
        self.assertEqual(audio.duration_warnings(120), [])
        self.assertEqual(self.invoke('estimate', '--orders', '0')[0], 2)
        self.assertEqual(self.invoke('estimate', '--orders', '1', '--bpm', '32')[0], 2)

    def test_report_collects_independent_errors_without_mutating_source(self):
        score = project.to_dict(demo.create())
        score['title'] = 'This title is much too long'
        score['samples'][0]['volume'] = 100
        score['patterns'][0]['events'] = [
            {'row': 0, 'channel': 0, 'note': 'G#-3'},
            {'row': 1, 'channel': 0, 'effect': 'C41'},
            {'row': 1, 'channel': 0, 'effect': 'F06'},
        ]
        original = copy.deepcopy(score)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'broken.json'
            project.write_json(path, score)
            before = path.read_bytes()
            code, out, err = self.invoke('validate', str(path), '--report')
            self.assertEqual(code, 2)
            self.assertEqual(out, '')
            report = json.loads(err)
            self.assertEqual(report['error_count'], 5)
            self.assertEqual({e['path'] for e in report['errors']}, {
                'title', 'samples[0]', 'patterns[0].events[0]',
                'patterns[0].events[1]', 'patterns[0].events[2]'})
            self.assertEqual(path.read_bytes(), before)
        self.assertEqual(score, original)

    def test_report_handles_malformed_containers_and_valid_scores(self):
        for data in (None, {}, {'samples': 'bad', 'patterns': [None], 'orders': [[]]}):
            self.assertTrue(project.diagnose(data))
        score = project.to_dict(demo.create())
        self.assertEqual(project.diagnose(score), [])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'valid.json'
            project.write_json(path, score)
            code, out, err = self.invoke('validate', str(path), '--report')
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out)['errors'], [])


class PartialRenderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        # Order 1 starts at row 10 via D10, inheriting speed, BPM and sounding
        # instrument from order 0. Slicing the order list would lose them all.
        sample = Sample('Loop', (80, 0, -80, 0), loop_length=4)
        first = Pattern(cells={(0, 0): cell('C-2', 1, 'F03'),
                               (0, 1): cell(effect='F64'), (1, 0): cell(effect='D10')})
        second = Pattern(cells={(12, 1): cell(effect='B00')})
        self.module = Module('Excerpt', [sample], [first, second], [0, 1])
        self.source = self.directory / 'song.mod'
        self.source.write_bytes(mod.encode(self.module))

    def check_slice(self, engine):
        full = self.directory / f'{engine}-full.wav'
        part = self.directory / f'{engine}-part.wav'
        audio.render(self.source, full, engine, seconds=0.375)
        result = audio.render(self.source, part, engine, from_order=1)
        self.assertEqual(result['start_seconds'], 0.15)
        self.assertEqual(result['requested_seconds'], 0.225)
        with wave.open(str(full)) as reader:
            reader.setpos(7200)
            expected = reader.readframes(10800)
        with wave.open(str(part)) as reader:
            self.assertEqual(reader.getnframes(), 10800)
            self.assertEqual(reader.readframes(10800), expected)
        self.assertGreater(result['audio']['peak'], 0.01)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg unavailable')
    def test_openmpt_excerpt_matches_full_render_with_inherited_state(self):
        self.check_slice('openmpt')

    def test_xmp_excerpt_matches_full_render_with_inherited_state(self):
        try:
            audio.default_xmp_library()
        except audio.RenderError as exc:
            self.skipTest(str(exc))
        self.check_slice('xmp')

    def test_invalid_or_unreachable_order_preserves_existing_output(self):
        output = self.directory / 'existing.wav'
        output.write_bytes(b'preserve')
        for order in (-1, 2, True):
            with self.assertRaises(ValidationError):
                audio.render(self.source, output, from_order=order)
        self.module.patterns[0].put(1, 0, cell(effect='B00'))
        self.source.write_bytes(mod.encode(self.module))
        with self.assertRaisesRegex(ValidationError, "n'est pas atteint"):
            audio.render(self.source, output, from_order=1)
        self.assertEqual(output.read_bytes(), b'preserve')

    def test_excessive_preroll_is_bounded(self):
        self.module.orders = [0] * 100 + [1]
        self.module.patterns[0] = Pattern()
        self.source.write_bytes(mod.encode(self.module))
        with self.assertRaisesRegex(ValidationError, 'prélecture'):
            audio.render(self.source, self.directory / 'large.wav', seconds=1, from_order=100)
