import os
import stat
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

    @unittest.skipIf(os.name == "nt", "Windows 不使用 POSIX 权限位")
    def test_existing_permissions_survive_replacement(self):
        for mode in (0o644, 0o640, 0o600):
            with self.subTest(mode=oct(mode)):
                self.path.write_text("old", encoding="utf-8")
                self.path.chmod(mode)
                atomic_write_text(self.path, "new")
                self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), mode)

    @unittest.skipIf(os.name == "nt", "Windows 不使用 POSIX umask")
    def test_new_file_permissions_follow_umask(self):
        original = os.umask(0o027)
        try:
            atomic_write_text(self.path, "new")
            self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o640)
        finally:
            os.umask(original)


if __name__ == "__main__":
    unittest.main()
