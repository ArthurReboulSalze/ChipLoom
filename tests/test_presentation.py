from pathlib import Path
from string import Formatter
import tempfile
import unittest

from tracker4agents import project
from tracker4agents.desktop_services import AppState
from tracker4agents.i18n import FR, error_text, translate
from tracker4agents.themes import THEMES, stylesheet


class PresentationTests(unittest.TestCase):
    def test_translations_keep_all_template_parameters(self):
        for source, french in FR.items():
            fields = lambda text: {field for _, field, _, _ in Formatter().parse(text) if field}
            self.assertEqual(fields(source), fields(french), source)
        self.assertEqual(translate("en", "File"), "File")
        self.assertEqual(translate("fr", "File"), "Fichier")
        self.assertEqual(translate("en", "Unknown data {'field': 3}"), "Unknown data {'field': 3}")
        self.assertIn("Invalid MOD", error_text("en", "Taille MOD invalide pour le profil v1."))

    def test_preference_defaults_migration_and_invalid_values(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            self.assertEqual(AppState(directory).values["language"], "en")
            project.write_json(directory / "session.json", {"volume": 41, "last_file": "old.mod"})
            state = AppState(directory)
            self.assertEqual((state.values["language"], state.values["theme"]), ("en", "midnight"))
            self.assertEqual(state.values["volume"], 41)
            project.write_json(directory / "session.json", {"language": [], "theme": {}})
            state = AppState(directory)
            self.assertEqual((state.values["language"], state.values["theme"]), ("en", "midnight"))

    def test_theme_palettes_are_complete_and_text_remains_readable(self):
        def luminance(color):
            rgb = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
            linear = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4 for value in rgb]
            return sum(a * b for a, b in zip(linear, (.2126, .7152, .0722)))
        def contrast(a, b):
            light, dark = sorted((luminance(a), luminance(b)), reverse=True)
            return (light + .05) / (dark + .05)
        self.assertEqual(len(THEMES), 4)
        for key, theme in THEMES.items():
            self.assertIn(theme["bg"], stylesheet(key))
            for background in ("bg", "panel", "selected"):
                self.assertGreaterEqual(contrast(theme["text"], theme[background]), 4.5, (key, background))
            for color in theme["channels"]:
                self.assertGreaterEqual(contrast(color, theme["panel"]), 4.5, (key, color))


if __name__ == "__main__":
    unittest.main()
