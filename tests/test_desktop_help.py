"""The help window and the tab icons: short cards in both languages, a search, an icon on every tab."""
from __future__ import annotations

import importlib
import shutil
import unittest

try:
    from PySide6.QtWidgets import QApplication
    from tracker4agents.desktop_help import show_help
except ModuleNotFoundError:
    QApplication = None

from tracker4agents import help_content

PACKAGE = __package__ + "." if __package__ else ""
base = importlib.import_module(PACKAGE + "test_desktop_08")


class HelpContentTests(unittest.TestCase):
    def test_both_languages_say_the_same_things_briefly(self):
        english, french = help_content.topics("en"), help_content.topics("fr")
        self.assertEqual([topic["id"] for topic in english], [topic["id"] for topic in french])
        for left, right in zip(english, french):
            self.assertEqual(len(left["items"]), len(right["items"]), left["id"])
            self.assertLessEqual(len(left["items"]), 6, left["id"])
            for gesture, text in left["items"] + right["items"]:
                self.assertLessEqual(len(text), 220, text)
        self.assertEqual(help_content.topics("de")[0]["title"], "Getting started")

    def test_search_keeps_the_matching_items(self):
        found = help_content.search("wav", "en")
        self.assertEqual([topic["id"] for topic in found], ["bank"])
        self.assertEqual(len(found[0]["items"]), 1)
        self.assertEqual(len(help_content.search("tuning", "en")[0]["items"]), 4)   # a title match keeps the topic
        self.assertEqual(help_content.search("zzz", "fr"), [])


@unittest.skipUnless(QApplication is not None and shutil.which("ffmpeg"), "PySide6 and FFmpeg required")
class HelpWindowTests(base.WindowCase):
    def test_every_tab_has_an_icon(self):
        tabs = self.window.sample_tabs
        for index in range(tabs.count()):
            self.assertFalse(tabs.tabIcon(index).isNull(), tabs.tabText(index))

    def test_the_help_opens_from_the_menu_searches_and_follows_the_language(self):
        window = self.window
        self.assertEqual(window.help_action.shortcut().toString(), "Ctrl+F1")
        window.help_action.trigger()
        dialog = window.help_dialog
        self.assertTrue(dialog.isVisible())
        self.assertFalse(dialog.isModal())
        titles = [dialog.topics.item(index).text() for index in range(dialog.topics.count())]
        self.assertEqual(titles[0], "Getting started")
        self.assertIn("Keyboard shortcuts", titles)
        self.assertIn("Open a song", dialog.text())
        dialog.search.setText("ctrl+m")
        shown = [dialog.topics.item(index).text() for index in range(dialog.topics.count())]
        self.assertIn("Working with your agent", shown)
        self.assertIn("Keyboard shortcuts", shown)
        dialog.search.setText("nothing-like-this")
        self.assertEqual(dialog.topics.count(), 0)
        self.assertIn("Nothing matches", dialog.text())
        window.set_language("fr")
        dialog = show_help(window, "agent")
        self.assertEqual(dialog.windowTitle(), "Aide de ChipLoom")
        self.assertIn("Écrire à ton agent", dialog.text())
        window.set_language("en")
        dialog.close()


if __name__ == "__main__":
    unittest.main()
