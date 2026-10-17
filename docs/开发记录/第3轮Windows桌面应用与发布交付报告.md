# 第 3 轮：Windows 桌面应用、打包、CI 发布与版本管理

日期：2026-10-17。已完成代码与发布流程准备；未执行 GitHub 推送、打标签、创建 Release 或 git commit。本机没有启动浏览器、pywebview 窗口或现有 Mac 应用，没有联网安装依赖。Windows 安装包仍需在 Windows / GitHub Actions 上编译，不能将本机 Mac 冻结包视作 Windows 安装包。

## 实现与边界

- 新桌面入口使用 Python + pywebview，Windows 强制 Edge WebView2。Mac 继续使用 Swift 应用；Swift 仅补齐退出码文案，构建脚本改读共享版本。
- 左侧按 history.json 和存在 analysis.json 的日期目录生成报告列表，与 Swift 的 refresh 逻辑一致；每 20 秒刷新，保留当前选择。手动更新成功后选中最新一期。
- 报告用同源 iframe 显示。只读随机端口服务仅提供 UI、reports 和用户 docs，随机路径令牌、防编码穿越、防符号链接逃逸、禁止目录列举与写请求，不暴露配置和 data。
- 隐藏报告页导航和历史列表只发生在 HTTP 响应及页面注入中，不修改 report.html 文件。报告里的外链及 window.open 交给系统默认浏览器；Windows 原生 WebView2 导航事件也拦截 iframe 的外部跳转。
- 登录、采集、已有数据重生成及 mirasim 任务都调用程序自身的子进程入口；后台线程读取独立输出，不占用界面线程。Windows 使用 CREATE_NO_WINDOW。windowed 模式自行恢复标准流，桌面冻结任务另外显式重定向日志文件并实时读取，避免依赖启动器的管道行为。
- root 优先级：XWB_ROOT → exe 同级 config.json 的便携目录 → 源码仓库 → 用户主目录 Documents/X分析工作台。首次只补缺失的默认配置和用户文档，创建 data/reports，已有文件不覆盖；collector 默认 profile_dir 随 root。
- mirasim 需同时满足 CLI 可发现、任务 ID / 本机有效工作目录 / 端口齐全才可用。未满足时禁用按钮并提示由 Mac 定时任务完成；可用时沿用 Swift 的 schedule run、20 秒轮询、45 分钟总等待和 90 秒未观察到 running 时的完成判断。
- 登录轮询容忍导航期 evaluate 异常，持续等待最新标签页；暂时没有页时等待新页事件，只有上下文关闭或 15 分钟总超时才结束未登录等待。新增导航重试、新标签、空页间隙、超时的 mock 测试。
- 所有数据分析和渲染算法、模板保持原样。当前程序只读 X；安装、升级和卸载均不删除 Documents 下的用户数据。

## 新增文件清单

| 文件 | 内容 |
|---|---|
| `desktop/__init__.py` | 桌面模块 |
| `desktop/app.py` | GUI / CLI 分流、自身子进程、日志、js_api、系统打开文件和链接、WebView2 导航拦截 |
| `desktop/core.py` | root / 初始化 / 周报列表 / 退出码 / 任务命令 / mirasim / 只读静态服务 |
| `desktop/ui/index.html` | 简体中文桌面界面 |
| `desktop/ui/style.css` | 跟随系统深浅色、侧栏、报告、展开日志 |
| `desktop/ui/app.js` | 自动刷新、选择保留、任务轮询、日志滚动及工具栏 |
| `desktop/ui/report.js` | 外链及 window.open 拦截、隐藏页内导航 |
| `scripts/version.py` | 唯一版本号 2.0.0 |
| `CHANGELOG.md` | 1.0.0、1.1.0、2.0.0 中文更新记录，参考现有提交说明 |
| `packaging/requirements-windows.txt` | Windows 构建依赖范围 |
| `packaging/xworkbench.spec` | onedir / windowed、图标、共享版本文件属性、UI / scripts / docs / config、Markdown 扩展与 Playwright Node 驱动 |
| `packaging/installer.iss` | 固定 AppId、当前用户安装、快捷方式、安装后启动、中文语言探测和英文回退、不删除用户数据 |
| `packaging/build_windows.ps1` | 安装依赖、测试、冻结构建、资源检查、冒烟、Inno Setup、便携 ZIP 及 SHA-256 |
| `packaging/release_notes.py` | 严格提取对应版本的更新说明 |
| `.github/workflows/ci.yml` | main push / PR，Ubuntu 和 Windows，Python 3.12；Windows 开启模拟浏览器测试 |
| `.github/workflows/release.yml` | v* / 手动出包、标签版本校验、artifact、标签触发 Release 与附件 |
| `tests/make_fixture.py` | 复用单测合成夹具的命令行生成器 |
| `tests/test_collect_mock.py` | 本地模拟站点、真实 Playwright 采集与未登录场景；浏览器测试需 XWB_BROWSER_TESTS=1，另有不启动浏览器的夹具检查 |
| `tests/test_desktop.py` | 路径、初始化、列表、退出码、命令、线程任务、mirasim、标准流、防穿越、服务响应及原生导航事件替身 |
| `tests/test_desktop_js.py` | 用 Node 执行真实前端脚本，验证外链/window.open、隐藏导航、刷新保留选择及变更加载 |
| `tests/test_packaging.py` | 发布说明精确版本提取 |
| `docs/Windows安装与使用.md` | 非技术用户安装、使用、数据备份、升级、卸载与退出码排障 |
| `docs/开发记录/第3轮Windows桌面应用与发布交付报告.md` | 本报告，不随安装包分发 |

## 修改文件清单

| 文件 | 修改 |
|---|---|
| `.gitignore` | 保留原 build/dist/browser-profile 忽略；将 index.html 限定为根目录，确保新 UI index.html 能进入 git；忽略临时发布说明与日志 |
| `README.md` | 跨平台总览、Windows 桌面用法、源码入口、测试/构建/发布方法、目录清单 |
| `app/Sources/main.swift` | 补齐 2/5/6/7，统一 3/4 文案；未改采集、轮询、报告显示流程 |
| `app/build.sh` | CFBundleShortVersionString / CFBundleVersion 从 scripts/version.py 读取；未执行此脚本 |
| `scripts/collect_playwright.py` | 登录导航重试、最新页追踪、15 分钟超时；采集流程与选择器未改 |
| `tests/support.py` | 抽出共用 write_fixture，原默认合成输入保持不变 |
| `tests/test_collect_playwright.py` | 增加登录回归测试 |

原 `packaging/icon.ico` 未改，真实 `data/`、`reports/`、`index.html` 未改。

## Windows 用户使用流程

登录有权限的 GitHub 账号，进入私有仓库 Releases，下载最新 `XWorkbench-Setup-版本号.exe` 并双击安装；未签名导致 SmartScreen 提示时，确认来源后点“更多信息 → 仍要运行”。安装后从开始菜单或桌面双击应用，第一次点“登录 X”在专用 Edge 中完成目标账号登录，再点“仅更新数据”。以后直接打开应用查看历史报告，按需更新；补写 report.md 建议后点“重新生成网页”。数据默认保存在用户主目录 Documents/X分析工作台，备份整个文件夹；新版覆盖安装和卸载均保留该目录。

## 本机验证结果

| 检查 | 实际结果 |
|---|---|
| `<构建虚拟环境>/bin/python -m unittest discover -s tests` | 109 项，成功，跳过 2 项；约 2.2 秒 |
| `python3 -m unittest discover -s tests` | 109 项，成功，跳过 3 项；约 2.1 秒 |
| Swift 类型检查 | `swiftc -typecheck -swift-version 5 -parse-as-library -target arm64-apple-macos14.0 -module-cache-path <临时目录>/xwb-swift-cache app/Sources/main.swift -framework SwiftUI -framework WebKit -framework AppKit` 退出码 0；没有执行 app/build.sh，没有覆盖 .app |
| Mac PyInstaller | `<构建虚拟环境>/bin/python -m PyInstaller --noconfirm --clean packaging/xworkbench.spec` 成功；使用 `PYINSTALLER_CONFIG_DIR=<临时目录>/xwb-pyinstaller-config`，arm64 onedir/windowed 产物在 dist/XWorkbench，约 157 MiB |
| 冻结包普通输出冒烟 | 合成中文/带空格临时 root；`dist/XWorkbench/XWorkbench --run-weekly --skip-collect --root <dir> --date 2026-10-17` 返回 0，生成 report.html / index.html |
| 冻结包显式日志冒烟 | 同一入口加 `--job-log <日志路径>`，返回 0，日志含 report_html，未创建窗口 |
| 分析/渲染回归 | 冻结包两种模式下，history.json、analysis.json、report.md、report.html、index.html 共 5 项，SHA-256 与修改前合成基线相同 |
| 资源收集 | 检查 10 项关键资源：4 个 UI 文件、config、Windows 文档、run_weekly.py、collect.mjs、Playwright Node 和 cli.js；全在包内，无 docs/开发记录 |
| 真实数据与图标 | 修改前后 25 项（24 个真实数据/报告文件 + icon.ico）的文件清单、SHA-256 与权限一致 |
| 前端/脚本 | Node 的真实脚本执行测试及语法检查、Python compileall、zsh build.sh 语法检查通过 |
| 工作流与发布说明 | Ruby 标准 YAML 解析两份工作流成功；release_notes.py 精确提取 2.0.0 的 8 行条目；错误版本提取有测试 |
| Git | git diff --check 通过；未 commit；根 index.html 仍被忽略，desktop/ui/index.html 可进入 git |

跳过原因必须区分：两个解释器都未设置 XWB_BROWSER_TESTS，因此浏览器集成测试跳过；当前执行沙箱禁止监听任何本地端口（bind 返回 PermissionError / Operation not permitted），真实 HTTP 连接测试也跳过，但处理器的 200/404、防穿越、报告注入及不改磁盘的逻辑通过无端口测试。第二个解释器还缺少 pywebview，按预期跳过该依赖的导入检查。CI Windows 开启 XWB_BROWSER_TESTS 时，端口不允许或浏览器/依赖缺失会失败，不会借本机跳过逻辑掩盖错误。

本机 PyInstaller 日志暂存在 `<临时目录>/xwb-round3-pyinstaller.log`；基线指纹仅为临时验证证据，不包含真实数据正文。正常构建结果留在忽略的 build/ 与 dist/。

## 仍须 CI / 真实 Windows 验证

- Windows Python 3.12 的全套测试，特别是系统 msedge 的无头完整采集、下载、认证切换和未登录退出码 3；模拟站点不代表真实 X 改版兼容。
- Windows PyInstaller / pythonnet / WebView2 的资源与原生运行、windowed exe 独立退出码和显式日志；Mac 冻结冒烟不能替代此项。
- PowerShell 构建脚本、ISPP / Inno Setup 编译和语言文件回退。本机没有 PowerShell / Inno Setup，未将静态检查写成编译通过。
- 实际安装、开始菜单/桌面快捷方式、无管理员运行、WebView2 缺失提示、SmartScreen、中文路径、便携版、升级与卸载后数据保留。
- 真实 WebView2 窗口的深浅色、排版、iframe 报告、外链/中键/window.open/程序化导航、刷新选择、实时日志和任务期间禁用操作；本机按要求未启动界面，只运行 DOM / 原生事件替身。
- 真实 X 的手动登录（导航、验证码、新标签、关闭、超时）、登录态复用、Edge 占用与网络失败。
- Windows 本机 mirasim.exe 的发现与任务执行；默认配置中的 Mac 工作目录不会使 Windows 按钮误启用，需要配置本机任务。
- GitHub 私有仓库的 Actions 权限、tag 校验、artifact 下载和 gh release create。手动触发仅上传 artifact，不发布 Release；这些外部操作本轮都未执行。

## 首次 CI 最可能失败的位置

优先关注 Windows 的 `test_collect_mock`：系统 Edge 是否可由该 Playwright 版本启动、runner 的 Edge 策略或进程占用、下载事件时序，这是本机完全没有实际浏览器覆盖的部分。其次是 Windows 冻结及 Inno Setup 阶段的 pythonnet / WebView2 资源收集、ISCC 发现或 Chocolatey 安装；脚本已对 Node 驱动资源、冻结退出码、语言文件缺失和产物缺失设置明确失败点。若这些通过，发布阶段最值得检查的是私有仓库是否允许 GITHUB_TOKEN 写 contents。

现有流程守卫检查为 WARN：缺少 docs/goals 任务目录，当前分支为 main，未设标准 check 目标；按本轮明确任务书在指定工作区完成实现和验证，开发报告集中于本目录，没有因此扩大到提交或发布。全程由当前主代理完成，未调用子代理或 Astra。
