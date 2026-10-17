"""只读 Playwright 采集；仅在执行采集或手动登录时加载可选依赖。"""
import json
import os
import re
import socket
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from file_utils import atomic_write_text
from run_lock import LockBusyError, RunLock, pid_exists

# 所有等待集中在这里，下一轮可用本地模拟页面缩短等待。
NAVIGATION_TIMEOUT_MS = 45000
ACTION_TIMEOUT_MS = 25000
DOWNLOAD_TIMEOUT_MS = 45000
LOGIN_WAIT_MS = 25000
LOGIN_POLL_MS = 1000
LOGIN_TIMEOUT_SECONDS = 15 * 60
ELIGIBILITY_WAIT_MS = 7000
OVERVIEW_WAIT_MS = 8000
CONTENT_WAIT_MS = 8000
AUDIENCE_WAIT_MS = 7000
RANGE_WAIT_MS = 4000
VERIFIED_WAIT_MS = 5000

ACCOUNT_SELECTOR = "[data-testid='SideNav_AccountSwitcher_Button']"
MAIN_TEXT_JS = "() => (document.querySelector('main') || document.body).innerText"
ELIGIBILITY_JS = """() => {
  const main = document.querySelector('main') || document.body;
  const STATUS = ['M12 1.75C6.34', 'M12 3.75c'];
  const items = [...main.querySelectorAll('svg')]
    .map(s => ({s, d: s.querySelector('path')?.getAttribute('d') || ''}))
    .filter(({d}) => STATUS.some(pre => d.startsWith(pre)))
    .map(({s, d}) => {
      let c = s.parentElement;
      while (c && c !== main && !c.querySelector('p')) c = c.parentElement;
      return {text: c?.querySelector('p')?.innerText.trim() || '', icon: d.slice(0, 16)};
    }).filter(it => it.text);
  return {text: main.innerText, items};
}"""


class BrowserDependencyError(RuntimeError):
    pass


class ProfileOccupiedError(RuntimeError):
    pass


def build_url(base_url, route):
    parts = urlsplit(base_url)
    if parts.scheme not in ("http", "https") or not parts.netloc or parts.query or parts.fragment:
        raise ValueError("collector.base_url 必须是无查询参数的 http/https 地址")
    return base_url.rstrip("/") + "/" + route.lstrip("/")


def is_logged_in(account_seen, handle):
    # 避免 @test 误认成 @test_other；用户名本身大小写不敏感。
    return bool(account_seen and re.search(
        r"(?<![\w@])@" + re.escape(handle) + r"(?![A-Za-z0-9_])", account_seen, re.I))


def new_meta(handle):
    return {"started_at": utc_now(), "handle": handle, "files": {}, "warnings": [],
            "backend": "playwright", "space_id": None}


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def write_meta(raw, meta, **extra):
    atomic_write_text(raw / "meta.json", json.dumps({**meta, **extra}, ensure_ascii=False, indent=2))


def browser_settings(root, config, login_mode=False):
    channel = config.get("browser_channel", "msedge")
    if channel not in ("msedge", "chrome", "", None):
        raise ValueError("collector.browser_channel 只能是 msedge、chrome 或空字符串")
    if not isinstance(config.get("headless", False), bool):
        raise ValueError("collector.headless 必须是 true 或 false")
    profile = Path(config.get("profile_dir") or "browser-profile").expanduser()
    if not profile.is_absolute():
        profile = Path(root) / profile
    build_url(config.get("base_url", "https://x.com"), "home")
    options = {"headless": False if login_mode else config.get("headless", False),
               "accept_downloads": True,
               "args": ["--no-first-run", "--no-default-browser-check"]}
    if channel:
        options["channel"] = channel
    return profile.resolve(), options


def load_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise BrowserDependencyError("缺少 playwright，请运行 pip install -r requirements.txt；默认使用系统 Microsoft Edge，无需下载浏览器") from None
    return sync_playwright


def check_profile_available(profile):
    """检查 Chromium 的本地占用标记；跨工作台运行另由配置目录内的锁串行化。"""
    marker = profile / "SingletonLock"
    if marker.is_symlink():
        target = os.readlink(marker)
        host, _, pid = target.rpartition("-")
        if host != socket.gethostname() or not pid.isdigit() or pid_exists(int(pid)):
            raise ProfileOccupiedError(f"浏览器配置目录已被占用：{profile}，请关闭使用该目录的浏览器后重试")
    elif marker.exists():
        raise ProfileOccupiedError(f"浏览器配置目录已被占用：{profile}，请关闭使用该目录的浏览器后重试")
    if os.name == "nt" and (profile / "lockfile").exists():
        # Windows Chromium 用打开的 lockfile 保护配置目录；只探测，不删除标记。
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.CreateFileW(str(profile / "lockfile"), 0, 0, None, 3, 0, None)
        if handle == wintypes.HANDLE(-1).value:
            if ctypes.get_last_error() in (32, 33):
                raise ProfileOccupiedError(f"浏览器配置目录已被占用：{profile}，请关闭使用该目录的浏览器后重试")
        else:
            kernel.CloseHandle(handle)


def launch_context(playwright, profile, options):
    try:
        return playwright.chromium.launch_persistent_context(str(profile), **options)
    except Exception as error:
        message = str(error)
        if re.search(r"ProcessSingleton|profile.*in use|user data directory.*in use|SingletonLock", message, re.I):
            raise ProfileOccupiedError(f"浏览器配置目录已被占用：{profile}，请关闭使用该目录的浏览器后重试") from error
        if re.search(r"executable.*(doesn't exist|not found)|distribution.*not found|ENOENT|failed to find.*(chrome|edge)", message, re.I):
            channel = options.get("channel")
            hint = ("请安装 Microsoft Edge" if channel == "msedge" else "请安装 Google Chrome") if channel else "请运行 python -m playwright install chromium"
            raise BrowserDependencyError(f"找不到浏览器：{hint}；也可在 config.local.json 设置 collector.browser_channel") from error
        raise


def save_download(download, target):
    """先下载到同目录临时文件，再替换；失败保留原 CSV，并提示关闭 Excel。"""
    target = Path(target)
    fd, name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    os.close(fd)
    temp = Path(name)
    try:
        download.save_as(str(temp))
        os.replace(temp, target)
    except PermissionError as error:
        raise OSError(f"无法保存 CSV：{target}。请关闭占用该文件的 Excel 或其他程序后重试") from error
    finally:
        temp.unlink(missing_ok=True)


def account_text(page):
    return page.evaluate("() => document.querySelector(\"[data-testid='SideNav_AccountSwitcher_Button']\")?.innerText || null")


def main_text(page):
    text = page.evaluate(MAIN_TEXT_JS)
    if not text or not text.strip():
        raise RuntimeError("页面正文为空，可能未加载完成或 X 页面异常")
    return text


def select_range(page, label):
    page.get_by_text(label, exact=True).first.click()
    page.wait_for_timeout(RANGE_WAIT_MS)


def set_verified_only(page, meta, want):
    button = page.locator("main").get_by_role("button", name="Verified only", exact=True)
    if button.count() == 0:
        meta["warnings"].append("Verified only 开关未找到")
        return False
    state = button.get_attribute("aria-pressed")
    if state is None:
        meta["warnings"].append("Verified only 开关未找到")
        return False
    if (state == "true") != want:
        button.click()
        page.wait_for_timeout(VERIFIED_WAIT_MS)
    return True


def collect_pages(page, raw, handle, config, meta, set_step):
    base = config.get("base_url", "https://x.com")
    set_step("登录检查")
    page.goto(build_url(base, "home"))
    try:
        page.locator(ACCOUNT_SELECTOR).wait_for(timeout=LOGIN_WAIT_MS)
    except Exception:
        # 只容忍登录控件未出现；空白页、关闭窗口等错误仍由正文读取暴露。
        main_text(page)
    account = account_text(page)
    if not is_logged_in(account, handle):
        write_meta(raw, meta, ok=False, reason="not_logged_in", account_seen=account, finished_at=utc_now())
        return 3

    set_step("收益资格页")
    page.goto(build_url(base, "i/jf/creators/original_content_rewards"))
    page.wait_for_timeout(ELIGIBILITY_WAIT_MS)
    main_text(page)
    eligibility = page.evaluate(ELIGIBILITY_JS)
    atomic_write_text(raw / "eligibility.json", json.dumps(eligibility, ensure_ascii=False, indent=2))

    def download_csv(name):
        set_step(f"下载 {name}")
        with page.expect_download(timeout=DOWNLOAD_TIMEOUT_MS) as event:
            page.get_by_role("button", name="Download CSV", exact=True).first.click()
        download = event.value
        save_download(download, raw / name)
        meta["files"][name] = download.suggested_filename

    set_step("账号概览")
    page.goto(build_url(base, "i/account_analytics"))
    page.wait_for_timeout(OVERVIEW_WAIT_MS)
    set_verified_only(page, meta, False)
    select_range(page, "3M")
    atomic_write_text(raw / "overview_all_3m.txt", main_text(page))
    download_csv("overview_all.csv")
    set_step("认证用户概览")
    if set_verified_only(page, meta, True):
        atomic_write_text(raw / "overview_verified_3m.txt", main_text(page))
        download_csv("overview_verified.csv")
        set_step("恢复全部用户概览")
        set_verified_only(page, meta, False)

    set_step("帖子明细页")
    page.goto(build_url(base, "i/account_analytics/content?type=posts&sort=date&dir=desc&days=90"))
    page.wait_for_timeout(CONTENT_WAIT_MS)
    download_csv("content_90d.csv")

    set_step("受众画像")
    page.goto(build_url(base, "i/account_analytics/audience"))
    page.wait_for_timeout(AUDIENCE_WAIT_MS)
    try:
        select_range(page, "28D")
    except Exception:
        meta["warnings"].append("受众页 28D 切换失败，保留默认范围")
    atomic_write_text(raw / "audience.txt", main_text(page))
    set_step("保存采集结果")
    return 0


def run_browser(root, handle, config, action, login_mode=False):
    profile, options = browser_settings(root, config, login_mode)
    factory = load_playwright()
    with RunLock(profile / ".xwb.lock", f"已有采集/分析任务在运行，浏览器配置目录：{profile}"):
        check_profile_available(profile)
        with factory() as playwright:
            context = launch_context(playwright, profile, options)
            result = None
            try:
                context.set_default_timeout(ACTION_TIMEOUT_MS)
                context.set_default_navigation_timeout(NAVIGATION_TIMEOUT_MS)
                page = context.pages[0] if context.pages else context.new_page()
                result = action(page, context)
                return result
            finally:
                # 保留最初异常，避免关闭浏览器时掩盖采集原因。
                failed = sys.exc_info()[0] is not None
                try:
                    context.close()
                except Exception:
                    if not failed and result in (None, 0):
                        raise


def collect(root, raw, handle, config):
    raw = Path(raw)
    meta = new_meta(handle)
    step = "初始化"

    def set_step(value):
        nonlocal step
        step = value

    code = 4
    try:
        raw.mkdir(parents=True, exist_ok=True)
        write_meta(raw, meta, ok=False, reason="in_progress")
        step = "启动浏览器"
        code = run_browser(root, handle, config, lambda page, _: collect_pages(
            page, raw, handle, config, meta, set_step))
        if code == 0:
            write_meta(raw, meta, ok=True, finished_at=utc_now())
        return code
    except Exception as error:
        # 未登录的原因不能被关闭浏览器的次要错误覆盖。
        if code == 3:
            return 3
        try:
            write_meta(raw, meta, ok=False, reason="error", error=str(error), step=step, finished_at=utc_now())
        except OSError as meta_error:
            print(f"无法保存 meta.json：{meta_error}", file=sys.stderr)
        print(f"采集失败（{step}）：{error}", file=sys.stderr)
        return 6 if isinstance(error, BrowserDependencyError) else 7 if isinstance(error, LockBusyError) else 4


def login(root, handle, config):
    print(f"请在工作台专用浏览器中手动登录 @{handle}；识别到该账号或关闭窗口后退出。")

    def wait_for_login(page, context):
        closed = False

        def on_close(*_):
            nonlocal closed
            closed = True

        context.on("close", on_close)
        deadline = time.monotonic() + LOGIN_TIMEOUT_SECONDS
        try:
            page.goto(build_url(config.get("base_url", "https://x.com"), "home"))
        except Exception:
            # 登录跳转、窗口关闭都可能中断首次导航；交由轮询判断。
            pass
        while not closed and time.monotonic() < deadline:
            pages = [p for p in context.pages if not p.is_closed()]
            if not pages:
                try:
                    # 新标签可能稍晚出现；继续泵送事件，等待真正的 context.close。
                    context.wait_for_event("page", timeout=LOGIN_POLL_MS)
                except Exception:
                    pass
                continue
            page = pages[-1]
            try:
                if is_logged_in(account_text(page), handle):
                    print(f"已识别登录账号 @{handle}，登录态已保存在专用配置目录。")
                    return 0
            except Exception:
                # evaluate 在导航期会失去执行上下文；仅本次读取失败，不终止登录。
                pass
            try:
                page.wait_for_timeout(LOGIN_POLL_MS)
            except Exception:
                # 标签页切换或关闭后，下一轮重新取得最新页。
                time.sleep(0.05)
        if not closed:
            print("登录等待已超过 15 分钟，请重新点击「登录 X」。", file=sys.stderr)
            return 3
        print("浏览器已关闭，尚未确认目标 X 账号登录。", file=sys.stderr)
        return 3

    try:
        return run_browser(root, handle, config, wait_for_login, login_mode=True)
    except Exception as error:
        print(f"登录窗口失败：{error}", file=sys.stderr)
        return 6 if isinstance(error, BrowserDependencyError) else 7 if isinstance(error, LockBusyError) else 4
