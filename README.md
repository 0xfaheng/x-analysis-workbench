# 0xfaheng · X 分析工作台

在自己的电脑上读取 X 数据，自动生成账号周报、下周调整建议和官方规则提示。无需接入 AI 或填写 API Key。

由 [0xfaheng](https://github.com/0xfaheng)（上海封阳科技创始人）维护。微信：`faheng2009` · [X](https://x.com/0xfaheng) · [YouTube](https://www.youtube.com/@0xfaheng)。

## 下载与使用

从 [最新版本](https://github.com/0xfaheng/x-analysis-workbench/releases/latest) 下载对应附件：

| 系统 | 下载文件 |
|---|---|
| Windows 10 / 11，64 位 | `XWorkbench-Setup-版本号.exe`，或 `XWorkbench-版本号-portable.zip` |
| macOS 13.5+，Apple Silicon | `XWorkbench-版本号-macOS-arm64.dmg`，或同名 `.zip` |

1. 打开应用，填写自己的 X 用户名。
2. 点击「登录 X」，在专用浏览器中手动完成登录。
3. 点击「更新数据与建议」，查看统计、下周动作和复查指标。

需能访问 X，并具有对应账号 Analytics 的访问权限。安装包未做平台认证签名，首次打开及常见问题见 [Windows 说明](docs/Windows安装与使用.md) / [Mac 说明](docs/Mac安装与使用.md)。

## 报告包含什么

- 曝光、涨粉、主帖表现、内容分类及阶段目标。
- 结合实际数据生成的下周建议，每条列明依据、动作和复查方法。
- X 官方规则摘要、来源及核验日期；超过30天提醒复核。
- 历史报告与原始 CSV；自动刷新程序建议，保留人工修改。

运营目标可自行配置，关键词提示可能误判，程序不预测算法、收益或达标时间。详见 [程序建议与官方规则](docs/程序建议与官方规则.md)。

## 隐私

全程只读 X，不发帖、不删帖、不改账号设置。数据、配置和报告保存在本机，不上传给开发者。安装版默认目录为用户主目录下的 `Documents/X分析工作台`，源码版默认使用项目目录，也可通过 `XWB_ROOT` 指定。

`config.local.json`、`data/`、`reports/`、`browser-profile/` 与个人策略不入库。分享软件请使用发布包，勿打包个人数据目录。

## 源码运行

需要 Python 3.10+ 与已安装的 Edge 或 Chrome。在项目根目录创建 `config.local.json`，内容为 `{"handle": "your_handle"}`，然后执行：

```bash
python -m venv .venv
# Windows 使用 .venv/Scripts/python；macOS 使用 .venv/bin/python
python -m pip install -r requirements.txt
python scripts/run_weekly.py --login
python scripts/run_weekly.py
```

运行命令前激活虚拟环境，或将 `python` 替换为对应的虚拟环境解释器。运行桌面版需再安装平台对应的 `packaging/requirements-*.txt`，执行 `python desktop/app.py`。

已安装 OpenCLI 和 Chrome 扩展的源码用户可设置 `collector.backend: "opencli"`，复用日常 Chrome 登录态；先用 `opencli doctor` 检查连接。默认采集模式使用专用浏览器目录。

[周报流程](docs/周报流程.md) · [个人策略模板](docs/策略基线.template.md) · [开发与发布](docs/开发与发布.md)
