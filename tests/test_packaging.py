import importlib.util
import unittest
from support import ROOT

spec = importlib.util.spec_from_file_location("xwb_release_notes", ROOT / "packaging/release_notes.py")
notes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notes)


class ReleaseNotesTests(unittest.TestCase):
    def test_extracts_only_exact_version(self):
        text = "# 更新\n\n## [2.0.0] - 日期\n\n中文条目\n\n## [1.1.0]\n旧条目\n"
        self.assertEqual(notes.release_notes(text, "2.0.0"), "中文条目\n")
        self.assertEqual(notes.release_notes(text, "1.1.0"), "旧条目\n")
        with self.assertRaises(ValueError):
            notes.release_notes(text, "2.0")

    def test_current_version_has_release_notes(self):
        from version import __version__
        self.assertTrue(notes.release_notes((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), __version__))
