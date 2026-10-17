# X 分析工作台

每周自动分析 X 账号 @0xfaheng 的数据，跟踪「原创内容奖励」资格进度，并给出下一周的调整建议。

## 日常使用：双击「X分析工作台.app」

- 原生 Mac 应用，不打开浏览器。左侧是历次周报（门槛进度、目标达成数，「待写建议」表示这期还没有助手建议），右侧显示报告：指标卡、图表、完整周报。
- 报告里的帖子链接会用系统默认方式打开原帖。
- 工具栏：
  - **生成完整周报**：让 mirasim 立即运行每周定时任务（采集 → 助手写下周建议 → 生成报告并发到 mirasim 对话），约 5–15 分钟，完成后应用自动显示。需要 mirasim 和 ego lite 都在运行。
  - **仅更新数据**：只采集和统计，不写建议，约 1–2 分钟。
  - **运行日志**、**更多**（打开文件夹、报告原文、策略基线、阶段目标配置）。
- 应用每 20 秒自动检查新报告，所以每周一定时任务跑完后，打开应用就能看到新一期。
- 如果应用被拷贝到别处，它会去桌面的 `X分析工作台` 文件夹找数据。

## 数据从哪来

macOS 默认通过 **ego lite 浏览器里已登录的 X 账号** 在后台读取，所以 ego lite 要在运行并保持登录。Mac 应用本身不依赖浏览器显示。macOS 命令行需要 Python 3.10+ 和 `markdown`（`python3 -m pip install 'Markdown>=3.7,<4'`）；沿用 `./scripts/run_weekly.sh`，仍优先使用 `XWB_PYTHON` 指定且能导入 markdown 的解释器。

Windows 通过 Python Playwright 驱动系统 Microsoft Edge，使用工作台独立配置目录，复用用户手动登录的账号。两个后端产出相同的原始文件，分析、渲染均在当前 Python 进程执行。程序只读，不输入账号密码、不发帖、不修改账号设置。

## Windows 使用（命令行）

安装 Python 3.10 或更新版本，安装时勾选加入 PATH，并确认系统已安装 Microsoft Edge。在工作台根目录打开终端：

```powershell
pip install -r requirements.txt
python scripts\run_weekly.py --login
python scripts\run_weekly.py
```

首次在弹出的专用浏览器里手动登录 `config.json` 中的账号。检测到目标 `@handle` 后自动关闭窗口；提前关闭且未确认登录时退出码为 3。以后复用 `browser-profile/` 中的登录态。`--login` 始终使用 Playwright 专用窗口，强制显示窗口，只处理登录，不采集或生成报告。

默认 `channel="msedge"`，不需要 `playwright install` 或额外下载浏览器。没有 Edge 时请先安装 Edge；也可在本机配置中选择已安装的 `chrome`。只有将 `browser_channel` 设为 `""` 使用 Playwright Chromium 时，才需另行运行 `python -m playwright install chromium`。本轮仅提供运行层，Windows 桌面应用及 PyInstaller 打包在第 3 轮完成。

常用参数（Mac 的 `.sh` 入口也原样透传）：

```powershell
python scripts\run_weekly.py --skip-collect --date 2026-10-17
python scripts\run_weekly.py --backend playwright --root "D:\X分析工作台"
```

`--backend auto|ego|playwright` 覆盖配置；`auto` 在 macOS 找得到 ego-browser 时选 ego，其余情况选 Playwright。ego 的查找顺序为 PATH、`~/.local/bin/ego-browser`。根目录优先级为显式 `--root`、环境变量 `XWB_ROOT`、入口脚本上级目录。`--login` 不能与 `--skip-collect` 同时使用。

## 本机配置与退出码

`config.json` 保存公共规则。可在根目录新增 `config.local.json`，按字典递归合并覆盖；数组、标量整体替换，未覆盖的字段保留。例如：

```json
{
  "collector": {
    "backend": "auto",
    "browser_channel": "msedge",
    "profile_dir": "browser-profile",
    "headless": false,
    "base_url": "https://x.com"
  }
}
```

`profile_dir` 可用相对根目录的路径或绝对路径，勿指向日常个人浏览器配置。默认显示窗口但不主动置顶；可设 `headless: true`，X 可能对无头模式降级。`base_url` 支持本地模拟站点及路径前缀。以上浏览器选项只用于 Playwright，ego 后端沿用现有行为。`config.local.json` 和默认 `browser-profile/` 不入 git；自定义配置目录请放到仓库外。Swift 应用仍从原有 `app.mirasim_*` 字段读取定时任务配置，不依赖 Windows 上存在该 Mac 目录。

入口在 `<root>/data/.run.lock` 记录 PID 与开始时间，登录模式也持锁；进程不存在或超过 2 小时自动回收记录。`.run.lock.guard` 是用于安全回收的常驻小文件，不表示任务仍运行。Playwright 另外检查专用配置目录的占用；占用时请关闭该目录的浏览器再重试。CSV 被 Excel 占用时会保留旧文件并提示关闭 Excel。

| 退出码 | 含义 |
|---|---|
| 0 | 成功（登录模式已确认目标账号） |
| 2 | 参数或配置错误 |
| 3 | X 未登录目标账号；或登录窗口关闭但未确认登录 |
| 4 | 采集失败、浏览器连接/页面异常，或分析渲染输入/文件错误 |
| 5 | 缺少 markdown 依赖（Mac 包装找不到可用 Python 也返回 5） |
| 6 | 缺少 Playwright，或找不到配置指定的 Edge/Chrome/Chromium |
| 7 | 已有采集/分析或登录任务在运行 |

## 其他

- 策略和规则：`docs/策略基线.md`；每周执行步骤：`docs/周报流程.md`。
- 命令行手动运行：`./scripts/run_weekly.sh`（采集 + 分析 + 生成网页）→ 在 `reports/<日期>/report.md` 写建议 → `python3 scripts/render.py --root .`
- 配置：`config.json` 与可选 `config.local.json`（分类关键词、风险规则、阶段目标、采集器、mirasim 定时任务 ID）。
- 修改应用后重新编译：`app/build.sh`（源码 `app/Sources/main.swift`）。
- 离线测试：`/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m unittest discover -s tests`（使用临时合成数据，不采集、不改真实报告；网页渲染需安装 `markdown`）。Node 与 zsh 可用时还会检查脚本语法，Node 也用于执行网页脚本的 DOM 替身测试。
- `index.html` 是同一份报告的网页版，没有应用时也可以用浏览器打开。

## 目录

| 路径 | 内容 |
|---|---|
| `X分析工作台.app` | 桌面应用 |
| `app/` | 应用源码、图标和编译脚本 |
| `scripts/collect.mjs` | ego-browser 采集脚本（只读） |
| `scripts/collect_playwright.py` | Playwright + 系统 Edge 采集后端（只读） |
| `scripts/run_weekly.py` | 跨平台采集 + 同进程分析和网页生成入口 |
| `scripts/run_weekly.sh` | Mac Python 选择与兼容包装 |
| `scripts/config_utils.py`、`scripts/run_lock.py` | 配置合并与跨进程运行锁 |
| `requirements.txt` | Python 依赖范围（Mac ego 路线只需 markdown） |
| `scripts/analyze.py` | 统计、目标检查、风险标记，生成报告草稿 |
| `scripts/render.py` | 生成单期报告页和 `index.html` |
| `data/raw/<日期>/` | 每期原始 CSV 与页面快照 |
| `data/history.json` | 历次周报关键指标 |
| `reports/<日期>/` | 每期 `report.md`、`report.html`、`analysis.json` |
| `browser-profile/` | Playwright 专用登录态，不入 git |
