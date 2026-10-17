"""检查公开源码；不扫描或改写个人数据。"""
import json
import subprocess
import unittest

from support import ROOT


class PublicRepositoryTests(unittest.TestCase):
    @unittest.skipUnless((ROOT / ".git").exists(), "源码归档没有 git 索引")
    def test_tracked_text_files_have_no_private_machine_markers(self):
        forbidden = ("/" + "Users/", "rulan" + "lai", "41e3" + "1642", "封" + "阳", "CLAUDE" + ".md")
        result = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
        hits = []
        for raw_name in result.stdout.split(b"\0"):
            if not raw_name:
                continue
            path = ROOT / raw_name.decode("utf-8")
            data = path.read_bytes()
            if b"\0" in data:
                continue
            try:
                text = data.decode("utf-8-sig")
            except UnicodeDecodeError:
                continue
            # 用户明确指定的公开品牌头衔允许出现在首页；其他文件仍检查个人痕迹。
            if path == ROOT / "README.md":
                text = text.replace("上海封" + "阳科技创始人", "")
            for marker in forbidden:
                if marker in text:
                    hits.append(f"{path.relative_to(ROOT)}: {marker}")
        self.assertEqual(hits, [], "个人痕迹：\n" + "\n".join(hits))

    def test_public_defaults_do_not_depend_on_owner_configuration(self):
        cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["handle"], "")
        self.assertNotIn("app", cfg)
        self.assertNotIn("assistant", cfg)
        self.assertEqual(cfg["collector"]["browser_channel"], "auto")
        self.assertIn("docs/策略基线.md", (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines())
