"""严格提取对应版本的中文发布说明，供离线测试及 CI 使用。"""
import argparse
import re
from pathlib import Path


def release_notes(text, version):
    match = re.search(r"^## \[" + re.escape(version) + r"\][^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not match or not match[1].strip():
        raise ValueError(f"CHANGELOG.md 中没有版本 {version} 的说明")
    return match[1].strip() + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    text = (Path(__file__).resolve().parents[1] / "CHANGELOG.md").read_text(encoding="utf-8")
    Path(args.out).write_text(release_notes(text, args.version), encoding="utf-8", newline="\n")
