import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support import ROOT
from file_utils import atomic_write_text


class AtomicWriteTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="x-atomic-test-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.path = self.root / "中文文件.json"

    def test_create_utf8_lf(self):
        atomic_write_text(self.path, "中文\n第二行\n")
        self.assertEqual(self.path.read_bytes(), "中文\n第二行\n".encode("utf-8"))
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_replacement_is_complete_and_in_same_directory(self):
        self.path.write_bytes(b"old")
        replace = os.replace

        def checked_replace(src, dst):
            self.assertEqual(Path(src).parent, self.path.parent)
            self.assertEqual(self.path.read_bytes(), b"old")
            self.assertEqual(Path(src).read_bytes(), "新数据\n".encode("utf-8"))
            replace(src, dst)

        with mock.patch("file_utils.os.replace", side_effect=checked_replace):
            atomic_write_text(self.path, "新数据\n")
        self.assertEqual(self.path.read_bytes(), "新数据\n".encode("utf-8"))
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_replace_failure_preserves_original_and_cleans_temp(self):
        self.path.write_bytes(b"old")
        with mock.patch("file_utils.os.replace", side_effect=OSError("模拟替换失败")):
            with self.assertRaises(OSError):
                atomic_write_text(self.path, "新数据")
        self.assertEqual(self.path.read_bytes(), b"old")
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_encoding_failure_preserves_original_and_cleans_temp(self):
        self.path.write_bytes(b"old")
        with self.assertRaises(UnicodeEncodeError):
            atomic_write_text(self.path, "\ud800")
        self.assertEqual(self.path.read_bytes(), b"old")
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_missing_parent_does_not_create_partial_file(self):
        with self.assertRaises(FileNotFoundError):
            atomic_write_text(self.root / "absent" / "file", "合成数据")
        self.assertEqual(list(self.root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
