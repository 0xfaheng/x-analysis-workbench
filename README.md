# X 分析工作台

在自己的电脑上只读采集 X 数据，查看周报、内容表现与原创内容奖励资格进度。

## 功能

- 读取 Creator Studio 资格页和 Analytics 数据，保存原始 CSV 与页面快照。
- 查看曝光走势、认证粉丝、主帖表现、分类、风险提示与阶段目标。
- 桌面应用内查看历次周报、实时日志；补写建议后重新生成网页。
- Windows / Mac 安装包无需 Python；首次填写自己的 X 用户名即可配置。
- 可选连接本机 mirasim 定时任务，由助手撰写下周建议；默认数据更新不调用 AI 服务。

## 下载

从 [Releases 最新版](https://github.com/0xfaheng/x-analysis-workbench/releases/latest) 的 Assets 下载，勿选 Source code：

| 平台 | 下载文件 |
|---|---|
| Windows 10 / 11，64 位 | `XWorkbench-Setup-版本号.exe`；便携版为 `XWorkbench-版本号-portable.zip` |
| Mac，Apple Silicon（arm64），macOS 13.5+ | `XWorkbench-版本号-macOS-arm64.dmg`；备用为同名 `.zip`，不支持 Intel Mac |

详细步骤及常见问题：[Windows 安装与使用](docs/Windows安装与使用.md) · [Mac 安装与使用](docs/Mac安装与使用.md)。安装包未做平台认证签名，系统首次打开时可能提示拦截，处理方法见对应说明。

## 快速开始

1. **安装**：Windows 双击安装包；Mac 打开 DMG，将 `XWorkbench.app` 拖入「应用程序」。
2. **设置用户名**：首次启动在卡片中填自己的 X 用户名，可带或不带 `@`，限 1–15 位字母、数字或下划线。以后用「更多 → 修改 X 用户名」。
3. **登录 X**：点击「登录 X」，在工作台专用浏览器中手动登录该账号，验证码和双重验证由本人完成。检测到账号后窗口关闭；最多等待 15 分钟。
4. **仅更新数据**：点击后等待约 1–2 分钟，查看当天报告。需要访问 X 和账号 Analytics 的权限；登录其他账号不会被认作成功。

Windows 自动尝试 Edge → Chrome；Mac 的 Playwright 自动尝试 Chrome → Edge。macOS 更新数据时若发现已安装的 ego-browser，会优先使用 ego lite 的登录会话；此时需在 ego 中登录同一账号。「登录 X」按钮始终打开 Playwright 的独立配置窗口；详细区别见 Mac 使用说明。

## 隐私与安全

全程只读 X：不发帖、不删帖、不修改账号设置、不代填密码。数据只保存在本机的 `文档/X分析工作台`（实际路径为用户主目录下 `Documents/X分析工作台`），工作台不上传任何数据至开发者或遥测服务器。默认不连接 AI 服务；自行启用 mirasim 后，助手按用户配置的流程处理报告。

Playwright 登录态保存在工作台专用 `browser-profile/`，与日常浏览器配置分开。macOS 的可选 ego 后端沿用 ego lite 自己管理的会话。登录态、`config.local.json`、原始数据和报告均属于私人数据，请自行备份，不要提交到公开仓库。

安装版升级、卸载保留数据。高级用户可用 `XWB_ROOT` 指定数据根目录；Windows 便携版优先使用 exe 同级有 `config.json` 的目录；从源码运行默认使用仓库根目录。Mac 冻结版默认使用「文稿」目录。

## 免责声明

本项目是非 X 官方工具，与 X Corp. 无关。X 页面、导出格式或奖励规则变化可能导致采集失效或指标含义改变；请以官方页面为准，并遵守 X 服务条款。分类、风险提示和阶段目标是规则示例，可能误判，不构成收益承诺。

## 从源码运行

需要 Python 3.10+、Node（仅开发测试需要）及已安装的 Edge 或 Chrome。Linux 的 Playwright 自动依次尝试 Chrome → Edge → Playwright 自带 Chromium，后者需自行安装。

在仓库根目录执行，先创建只保存本机设置的 `config.local.json`：

```json
{
  "handle": "your_handle"
}
```

macOS / Linux：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/run_weekly.py --login
.venv/bin/python scripts/run_weekly.py
# macOS 可用薄包装；macOS auto 优先 ego
XWB_PYTHON=.venv/bin/python ./scripts/run_weekly.sh
```

Windows PowerShell：

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python scripts\run_weekly.py --login
.venv\Scripts\python scripts\run_weekly.py
```

运行源码桌面版：macOS 安装 `packaging/requirements-macos.txt`，Windows 安装 `packaging/requirements-windows.txt`，再运行 `python desktop/app.py`。Linux 命令行可用；桌面 WebView 运行库需自行配置，不提供 Linux 安装包。

```bash
python scripts/run_weekly.py --skip-collect --date 2026-10-17 --root .
python scripts/run_weekly.py --backend playwright --root .
python scripts/render.py --root .
```

`config.json` 是公共默认值，`config.local.json` 按字典递归覆盖，数组及标量整体替换。默认分类、风险规则、阶段目标按 AI/web3 中文创作者设置，可自行调整。首次初始化从通用模板生成 `docs/策略基线.md`，已有个人策略不覆盖；助手流程见 [周报流程](docs/周报流程.md)。

```json
{
  "handle": "your_handle",
  "collector": {
    "backend": "auto",
    "browser_channel": "auto",
    "profile_dir": "browser-profile",
    "headless": false,
    "base_url": "https://x.com"
  },
  "assistant": { "context_file": null }
}
```

`--backend auto|ego|playwright` 可覆盖配置。`browser_channel` 可显式选 `msedge`、`chrome` 或 `""`；空字符串使用 Playwright Chromium，需要 `python -m playwright install chromium`。不要把 `profile_dir` 指向日常个人浏览器配置。`--login` 不能和 `--skip-collect` 同用。

| 退出码 | 处理 |
|---|---|
| 0 | 成功 |
| 2 | 设置用户名或修正参数 / 配置 |
| 3 | 登录正确的 X 账号后重试 |
| 4 | 查看运行日志及 `data/raw/日期/meta.json`；CSV 被 Excel 占用时先关闭 Excel |
| 5 | 安装 markdown 依赖，或重新安装工作台 |
| 6 | 安装 Edge / Chrome；源码运行时检查 Playwright 依赖 |
| 7 | 等待已有任务结束；进程已退出或锁记录超过 2 小时后自动回收 |

## 进阶：Mac 原生应用与 mirasim 自动周报

`app/` 保留 Swift 原生应用源码，支持 macOS 14+ 的 Apple Silicon。它与 Python 桌面版共用分析脚本和报告格式，可继续与已有工作台目录放在一起，或用 `XWB_ROOT` 指向原数据目录。原生应用默认回退到桌面同名工作台目录；Python 安装版默认数据在「文稿」，两种入口需指向同一 root 才会共享报告。

原生应用的 `AppConfig.load` 依次读取 `config.json` 和 `config.local.json`，支持 handle 与 app 字段覆盖。自行编译用 `app/build.sh`；不要在使用现有应用时无意覆盖它。

安装并运行 mirasim 和 ego lite，在 mirasim 中创建每周任务，按 [周报流程](docs/周报流程.md) 采集、写建议、渲染。把本机任务的 `app.mirasim_schedule_id`、`app.mirasim_workspace`、`app.mirasim_port` 写入 `config.local.json`（端口默认 4970）。Python 桌面版检测到 CLI 和完整配置后启用「生成完整周报」，按任务运行状态轮询。项目背景文件可通过 `assistant.context_file` 指定，按流程只读取可公开讲的经历。

未配置 mirasim 时，可把 `report.md` 交给自己选择的助手，按周报流程填入 `SUGGESTIONS:START/END` 标记之间，再点「重新生成网页」。本工具不自动发布帖子。

## 开发与发布流程

```bash
python -m unittest discover -s tests
# macOS Apple Silicon
bash packaging/build_macos.sh python3
```

Windows 使用 `./packaging/build_windows.ps1`。两份构建脚本都安装依赖、跑测试、PyInstaller 冻结并以临时合成数据冒烟。Mac 再做 ad-hoc 签名，生成 DMG（含「应用程序」快捷方式）和 ZIP；Windows 生成 Inno Setup 安装包和便携 ZIP。不捆绑浏览器，不打包个人数据或个人策略。

普通测试不启动浏览器。显式设置 `XWB_BROWSER_TESTS=1` 才运行 headless 本地模拟站点集成测试，绝不访问真实 X；`XWB_BROWSER_CHANNEL` 可指定浏览器。CI 在 Ubuntu、Windows、macOS 测试；Windows 用 Edge、macOS 用 Chrome 开启浏览器测试。GUI、首次登录、平台安全拦截和真实 X 改版兼容仍需真机验收。

发布时更新唯一版本来源 `scripts/version.py` 和 `CHANGELOG.md`，测试后由维护者提交、打 `vX.Y.Z` 标签并推送。release 工作流分别构建 Windows / Mac，各上传 artifact；两者成功后 Ubuntu publish job 一次创建 Release 并附上四个文件。标签必须等于源码版本。手动触发只构建、不发布。本地构建或修改工作流不会自动将 GitHub 仓库设为公开。

## 目录结构

| 路径 | 用途 |
|---|---|
| `config.json` / `config.local.json` | 公共默认值 / 忽略入库的本机覆盖 |
| `desktop/` | Python 桌面入口、js_api、UI 与只读报告服务 |
| `app/` | 可选 Swift 原生应用 |
| `scripts/` | 采集、分析、渲染、配置、锁和共享版本 |
| `packaging/` | 图标、PyInstaller、Mac / Windows 构建与安装脚本 |
| `.github/workflows/` | 三平台 CI、双平台出包与标签发布 |
| `tests/` | 合成夹具、离线测试、显式开启的模拟采集测试 |
| `docs/` | 安装说明、策略模板、助手流程和开发记录 |
| `docs/策略基线.md` | 首次初始化生成的个人策略，不入库、不随包分发 |
| `data/raw/日期/` | 个人原始数据，不入库 |
| `data/history.json` | 历次指标，不入库 |
| `reports/日期/`、`index.html` | 个人报告，不入库 |
| `browser-profile/` | Playwright 专用登录态，不入库 |
