"""通过本机 OpenCLI 桥复用日常 Chrome 登录态；只操作本任务创建的标签页。"""
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

from collect_playwright import ELIGIBILITY_JS, MAIN_TEXT_JS, build_url, is_logged_in, new_meta, utc_now, write_meta
from file_utils import atomic_write_text


class BridgeDependencyError(RuntimeError):
    pass


def cli_command():
    executable = shutil.which("opencli")
    if not executable:
        raise BridgeDependencyError("找不到 OpenCLI，请安装并连接 Chrome 扩展，运行 opencli doctor 检查")
    # Windows 的 npm .cmd shim 不能可靠传递含引号的 JavaScript，直接使用其 Node 入口。
    if Path(executable).suffix.lower() in (".cmd", ".bat", ".ps1"):
        package = Path(executable).parent / "node_modules/@jackwener/opencli"
        manifest = package / "package.json"
        node = shutil.which("node")
        if manifest.is_file() and node:
            bins = json.loads(manifest.read_text(encoding="utf-8"))["bin"]
            entry = package / (bins["opencli"] if isinstance(bins, dict) else bins)
            if entry.is_file():
                return [node, str(entry)]
        raise BridgeDependencyError("无法定位 OpenCLI 的 Node 入口，请重新安装 OpenCLI")
    return [executable]


class ChromeSession:
    def __init__(self):
        self.command = cli_command()
        self.name = "xwb-" + uuid.uuid4().hex[:12]
        self.opened = False

    def run(self, *args, decode=True):
        result = subprocess.run(
            [*self.command, "browser", self.name, *args], capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=100,
            creationflags=0x08000000 if sys.platform == "win32" else 0,
        )
        if result.returncode:
            raise RuntimeError((result.stderr or result.stdout).strip()[:1600])
        if not decode:
            return result.stdout
        try:
            return json.loads(result.stdout)
        except ValueError as error:
            raise RuntimeError("OpenCLI 未返回有效 JSON，请运行 opencli doctor 检查连接") from error

    def open(self, url):
        # 不绑定、不导航、不关闭用户已经打开的标签页。
        self.opened = True
        self.run("open", url, "--window", "background")

    def read(self, function):
        return self.run("eval", "(() => ({value: (" + function + ")()}))()").get("value")

    def wait(self, selector):
        self.run("wait", "selector", selector, "--timeout", "25000", decode=False)

    def click(self, *query):
        found = self.run("find", *query)
        entries = [entry for entry in found.get("entries", []) if entry.get("visible", True)]
        if len(entries) != 1:
            raise RuntimeError(f"页面控件不是唯一匹配：{query}，找到 {len(entries)} 个")
        self.run("click", str(entries[0]["ref"]))

    def close(self):
        if self.opened:
            self.run("close", decode=False)
            self.opened = False


def import_download(receipt, target, started):
    """只接收这次点击刚生成的完整 CSV；过期下载不能冒充本期数据。"""
    source = Path(receipt.get("filename", ""))
    if receipt.get("downloaded") is not True or receipt.get("state") != "complete":
        raise RuntimeError("Chrome 未完成 CSV 下载")
    if not source.is_absolute() or not source.is_file() or source.stat().st_mtime < started - 2:
        raise RuntimeError("下载文件不存在或属于此前的下载，保留原有数据")
    data = source.read_bytes()
    if not data or source.suffix.lower() != ".csv":
        raise RuntimeError("下载文件不是有效的非空 CSV")
    target = Path(target)
    temp = target.with_name("." + target.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temp.write_bytes(data)
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    return source.name


def logged_in(session, handle, config):
    session.open(build_url(config.get("base_url", "https://x.com"), "home"))
    try:
        session.wait("[data-testid='SideNav_AccountSwitcher_Button']")
    except RuntimeError:
        pass
    account = session.read("() => document.querySelector('[data-testid=SideNav_AccountSwitcher_Button]')?.innerText || null")
    return is_logged_in(account, handle), account


def collect(root, raw, handle, config):
    raw = Path(raw)
    raw.mkdir(parents=True, exist_ok=True)
    meta = new_meta(handle)
    meta["backend"] = "opencli"
    session = None
    step = "初始化 Chrome 桥"

    def checkpoint(value):
        nonlocal step
        step = value
        print(value, flush=True)
        write_meta(raw, meta, ok=False, reason="in_progress", step=step)

    def main_text():
        text = session.read(MAIN_TEXT_JS)
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("页面正文为空，请检查 Chrome 中的 X 页面")
        return text

    def verified(want):
        state = session.read("() => document.querySelector('main button[aria-label=\"Verified only\"]')?.getAttribute('aria-pressed') ?? null")
        if state is None:
            meta["warnings"].append("Verified only 开关未找到")
            return False
        if (state == "true") != want:
            session.click("--css", 'main button[aria-label="Verified only"]')
            time.sleep(5)
        return True

    def download(name):
        checkpoint("下载 " + name)
        started = time.time()
        session.click("--css", 'main button[aria-label="Download CSV"]')
        receipt = session.run("wait", "download", ".csv", "--timeout", "45000")
        meta["files"][name] = import_download(receipt, raw / name, started)

    base = config.get("base_url", "https://x.com")
    try:
        checkpoint(step)
        session = ChromeSession()
        checkpoint("检查日常 Chrome 登录账号")
        ok, account = logged_in(session, handle, config)
        if not ok:
            write_meta(raw, meta, ok=False, reason="not_logged_in", account_seen=account, finished_at=utc_now())
            return 3
        checkpoint("收益资格页")
        session.open(build_url(base, "i/jf/creators/original_content_rewards"))
        time.sleep(7)
        eligibility = session.read(ELIGIBILITY_JS)
        if not isinstance(eligibility, dict) or not eligibility.get("text", "").strip():
            raise RuntimeError("收益资格页正文为空")
        atomic_write_text(raw / "eligibility.json", json.dumps(eligibility, ensure_ascii=False, indent=2))
        checkpoint("账号概览")
        session.open(build_url(base, "i/account_analytics"))
        session.wait('main button[aria-label="Download CSV"]')
        verified(False)
        session.click("--role", "button", "--name", "3M")
        time.sleep(4)
        atomic_write_text(raw / "overview_all_3m.txt", main_text())
        download("overview_all.csv")
        checkpoint("认证用户概览")
        if verified(True):
            atomic_write_text(raw / "overview_verified_3m.txt", main_text())
            download("overview_verified.csv")
            verified(False)
        checkpoint("帖子明细页")
        session.open(build_url(base, "i/account_analytics/content?type=posts&sort=date&dir=desc&days=90"))
        session.wait('main button[aria-label="Download CSV"]')
        time.sleep(4)
        download("content_90d.csv")
        checkpoint("受众画像")
        session.open(build_url(base, "i/account_analytics/audience"))
        time.sleep(7)
        try:
            session.click("--role", "button", "--name", "28D")
            time.sleep(4)
        except RuntimeError:
            meta["warnings"].append("受众页 28D 切换失败，保留默认范围")
        atomic_write_text(raw / "audience.txt", main_text())
        write_meta(raw, meta, ok=True, reason="complete", finished_at=utc_now())
        return 0
    except Exception as error:
        write_meta(raw, meta, ok=False, reason="error", error=str(error), step=step, finished_at=utc_now())
        print(f"Chrome 采集失败（{step}）：{error}", file=sys.stderr)
        return 6 if isinstance(error, BridgeDependencyError) else 4
    finally:
        if session is not None:
            try:
                session.close()
            except Exception as error:
                print(f"本任务 Chrome 标签页未能自动关闭：{error}", file=sys.stderr)


def login(root, handle, config):
    session = None
    try:
        session = ChromeSession()
        ok, _ = logged_in(session, handle, config)
        print(f"已确认日常 Chrome 登录 @{handle}" if ok else f"请在日常 Chrome 中手动登录 @{handle}，再点「仅更新数据」")
        return 0 if ok else 3
    except Exception as error:
        print(f"Chrome 登录检查失败：{error}", file=sys.stderr)
        return 6 if isinstance(error, BridgeDependencyError) else 4
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                pass
