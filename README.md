# X 分析工作台

跨平台查看与分析 X 账号 @0xfaheng 的周报，跟踪「原创内容奖励」资格进度。程序只读 X，不发帖、不修改设置、不代填密码；下周建议由助手撰写。

| 平台 | 日常入口 | 安装与运行 |
|---|---|---|
| macOS | 现有 Swift 原生 `X分析工作台.app` | 保持现有应用与 ego / mirasim 流程 |
| Windows 10 / 11（64 位） | GitHub Releases 的安装包 | 下载 `XWorkbench-Setup-版本号.exe` → 安装 → 双击使用，无需 Python |

Windows 用户请看 [Windows 安装与使用](docs/Windows安装与使用.md)。私有仓库先登录有访问权限的 GitHub 账号；安装包未签名，SmartScreen 提示时确认来源后点“更多信息 → 仍要运行”。也提供解压即用的便携版 ZIP。

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

## Windows 桌面版

首次点“登录 X”，在专用 Edge 窗口手动登录目标账号，再点“仅更新数据”。左侧列出历史周报、门槛进度、目标达成及待写建议；右侧应用内显示报告，外部链接交给默认浏览器。每 20 秒刷新时保留当前选择，运行日志实时显示子进程输出。“重新生成网页”使用选中期已有数据，适合补写建议后刷新。

“生成完整周报”仅在检测到 mirasim CLI（Windows 为 mirasim.exe），且 `app.mirasim_schedule_id`、有效本机 `app.mirasim_workspace`、`app.mirasim_port` 齐全时启用；否则提示“需要 mirasim，目前由 Mac 定时任务完成”。可把 report.md 交给任意 AI 按 [周报流程](docs/周报流程.md) 第 3 步写建议，再重新生成网页。

桌面数据目录优先级：`XWB_ROOT` → 冻结程序同级有 config.json 的便携目录 → 源码运行的仓库根目录 → `~/Documents/X分析工作台`。首次只复制缺失的默认 config 和用户文档，创建 data/reports；升级、卸载均保留用户数据，默认浏览器配置随 root 放在 browser-profile 中。

## 源码运行与命令行

安装 Python 3.10 或更新版本，安装时勾选加入 PATH，并确认系统已安装 Microsoft Edge。在工作台根目录打开终端：

```powershell
pip install -r requirements.txt
python scripts\run_weekly.py --login
python scripts\run_weekly.py
```

首次在弹出的专用浏览器里手动登录 `config.json` 中的账号。检测到目标 `@handle` 后自动关闭窗口；提前关闭且未确认登录时退出码为 3。以后复用 `browser-profile/` 中的登录态。`--login` 始终使用 Playwright 专用窗口，强制显示窗口，只处理登录，不采集或生成报告。

默认 `channel="msedge"`，不需要 `playwright install` 或额外下载浏览器。没有 Edge 时请先安装 Edge；也可在本机配置中选择已安装的 `chrome`。只有将 `browser_channel` 设为 `""` 使用 Playwright Chromium 时，才需另行运行 `python -m playwright install chromium`。

开发桌面界面可安装 `packaging/requirements-windows.txt`，运行 `python desktop/app.py`。冻结后任务入口为 `XWorkbench.exe --run-weekly <参数>`，源码为 `python desktop/app.py --run-weekly <参数>`，不初始化 WebView 窗口。

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
| 3 | X 未登录目标账号；或登录窗口关闭但未确认登录；或登录超过 15 分钟 |
| 4 | 采集失败、浏览器连接/页面异常，或分析渲染输入/文件错误 |
| 5 | 缺少 markdown 依赖（Mac 包装找不到可用 Python 也返回 5） |
| 6 | 缺少 Playwright，或找不到配置指定的 Edge/Chrome/Chromium |
| 7 | 已有采集/分析或登录任务在运行 |

## 开发者：测试与 Windows 构建

```powershell
python -m unittest discover -s tests
./packaging/build_windows.ps1
```

构建脚本安装依赖、跑测试、PyInstaller onedir/windowed 构建、合成夹具冻结包冒烟、Inno Setup 安装包、便携 ZIP；输出 `dist/XWorkbench-Setup-版本号.exe` 与 `dist/XWorkbench-版本号-portable.zip`。不打包浏览器，Playwright 的 Node 驱动随包。找不到 Inno Setup 6 时用 Chocolatey 安装。

普通离线测试不启动浏览器。仅明确设置 `XWB_BROWSER_TESTS=1` 时，`tests/test_collect_mock.py` 启动 headless 浏览器访问本地模拟站点；`XWB_BROWSER_CHANNEL` 默认为 msedge。CI 的 Windows 任务必须开启，Ubuntu 默认跳过。测试使用临时合成数据，覆盖资格图标、认证开关、CSV 下载、28D 受众和未登录退出码 3；不登录真实 X。

## 开发者：发布新版本

1. 修改唯一版本来源 `scripts/version.py`，并在 `CHANGELOG.md` 添加对应版本段落。
2. 本地测试后提交修改，再执行 `git tag vX.Y.Z && git push --tags`（此前需已配置 GitHub 远程并推送代码）。
3. Actions 在 Windows 上测试、构建并上传安装包与便携 ZIP，再从 CHANGELOG 提取该版本说明创建 Release。标签与版本不一致会直接失败。
4. 手动运行 release 工作流只生成 artifact，不创建 Release。首发需检查 Actions、下载附件，并在真实 Windows 上完成首次登录及安装/升级/卸载验收。私有仓库的 Release 同样仅对有权限的账号开放。

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
| `desktop/` | Python 桌面入口、可测试的任务/文件服务、中文 UI |
| `packaging/` | 图标、PyInstaller spec、Inno Setup、Windows 构建与发布说明提取 |
| `.github/workflows/` | 双平台测试、Windows 出包与标签发布 |
| `scripts/version.py`、`CHANGELOG.md` | 共用版本号与中文更新记录 |
| `tests/` | 合成夹具、离线单测及显式开启的模拟采集集成测试 |
| `docs/` | 面向用户的 Windows 说明、策略和流程 |
| `docs/开发记录/` | 不随安装包分发的开发与验证记录 |
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
