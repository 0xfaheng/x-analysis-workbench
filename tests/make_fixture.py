"""为冻结包冒烟生成与单测相同的合成数据，不读取真实账号数据。"""
import argparse
from pathlib import Path

from support import REPORT_DATE, write_fixture

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    parser.add_argument("--print-date", action="store_true")
    args = parser.parse_args()
    if args.print_date:
        print(REPORT_DATE)
    elif args.out:
        write_fixture(args.out)
        print(f"合成夹具：{args.out}，报告日期：{REPORT_DATE}")
    else:
        parser.error("需要 --out 或 --print-date")
