import shutil
import subprocess
import unittest

from support import ROOT


class ScriptSyntaxTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "需要 Node 做采集脚本语法检查")
    def test_collect_syntax_only(self):
        # 仅解析，绝不执行采集代码或调用 ego。
        source = 'const OUT_DIR = "/unused"; const HANDLE = "test_account";\n'
        source += (ROOT / "scripts" / "collect.mjs").read_text(encoding="utf-8")
        result = subprocess.run([shutil.which("node"), "--check", "--input-type=module"],
                                input=source, text=True, encoding="utf-8", capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("zsh"), "需要 zsh 做入口脚本语法检查")
    def test_shell_syntax_only(self):
        result = subprocess.run([shutil.which("zsh"), "-n", str(ROOT / "scripts" / "run_weekly.sh")],
                                text=True, encoding="utf-8", capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
