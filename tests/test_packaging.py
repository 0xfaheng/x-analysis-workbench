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


class MacPackagingTests(unittest.TestCase):
    def test_spec_builds_arm64_bundle_and_excludes_personal_files(self):
        import runpy
        import sys
        from types import SimpleNamespace
        from unittest import mock
        hooks = SimpleNamespace(collect_all=lambda _: ([], [], []), collect_submodules=lambda _: [])
        analysis = SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[])
        constructors = {name: mock.Mock(return_value=analysis) for name in ("Analysis", "PYZ", "EXE", "COLLECT", "BUNDLE")}
        with mock.patch.dict(sys.modules, {"PyInstaller": SimpleNamespace(), "PyInstaller.utils": SimpleNamespace(),
                                           "PyInstaller.utils.hooks": hooks}), mock.patch.object(sys, "platform", "darwin"):
            runpy.run_path(str(ROOT / "packaging/xworkbench.spec"), init_globals={
                "SPECPATH": str(ROOT / "packaging"), **constructors})
        bundle = constructors["BUNDLE"].call_args.kwargs
        from version import __version__
        self.assertEqual(bundle["name"], "XWorkbench.app")
        self.assertEqual(bundle["bundle_identifier"], "io.github.0xfaheng.xworkbench")
        self.assertEqual(bundle["info_plist"]["CFBundleDisplayName"], "X分析工作台")
        self.assertEqual(bundle["info_plist"]["CFBundleShortVersionString"], __version__)
        self.assertEqual(constructors["EXE"].call_args.kwargs["target_arch"], "arm64")
        datas = constructors["Analysis"].call_args.kwargs["datas"]
        sources = [str(path) for path, _ in datas]
        self.assertIn(str(ROOT / "docs/策略基线.template.md"), sources)
        self.assertNotIn(str(ROOT / "docs/策略基线.md"), sources)
        self.assertFalse(any("config.local.json" in p or "开发记录" in p for p in sources))
        icon = (ROOT / "packaging/icon.icns").read_bytes()
        self.assertEqual(icon[:4], b"icns")
        self.assertEqual(int.from_bytes(icon[4:8], "big"), len(icon))
