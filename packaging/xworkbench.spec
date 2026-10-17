# -*- mode: python ; coding: utf-8 -*-
"""Windows onedir / macOS arm64 BUNDLE；只带驱动，浏览器由用户安装。"""
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

root = Path(SPECPATH).parent
sys.path.insert(0, str(root / "scripts"))
from version import __version__

version_info = None
if sys.platform == "win32":
    from PyInstaller.utils.win32.versioninfo import VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct, VarFileInfo, VarStruct
    numeric_version = tuple(int(v) for v in __version__.split(".")) + (0,)
    version_info = VSVersionInfo(
        ffi=FixedFileInfo(filevers=numeric_version, prodvers=numeric_version,
                          mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)),
        kids=[StringFileInfo([StringTable("080404B0", [
            StringStruct("FileDescription", "X 分析工作台"),
            StringStruct("FileVersion", __version__), StringStruct("ProductVersion", __version__),
            StringStruct("ProductName", "X 分析工作台"), StringStruct("OriginalFilename", "XWorkbench.exe"),
        ])]), VarFileInfo([VarStruct("Translation", [2052, 1200])])],
    )
pw_data, pw_binaries, pw_imports = collect_all("playwright")
datas = [(str(root / "desktop/ui"), "desktop/ui"), (str(root / "config.json"), ".")]
datas += [(str(p), "scripts") for p in (root / "scripts").iterdir() if p.suffix in (".py", ".mjs")]
datas.append((str(root / "scripts/collect.mjs"), "."))
# 开发记录不随安装包分发。
datas += [(str(p), "docs") for p in (root / "docs").glob("*.md") if p.name != "策略基线.md"]
datas += pw_data

a = Analysis(
    [str(root / "desktop/app.py")],
    pathex=[str(root / "desktop"), str(root / "scripts")],
    binaries=pw_binaries, datas=datas,
    hiddenimports=pw_imports + collect_submodules("markdown.extensions")
                  + ["run_weekly", "analyze", "render", "collect_playwright", "version"],
    hookspath=[], runtime_hooks=[], excludes=[], noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="XWorkbench", debug=False,
    bootloader_ignore_signals=False, strip=False, upx=False, console=False,
    icon=str(root / "packaging/icon.ico") if sys.platform == "win32" else None,
    version=version_info,
    target_arch="arm64" if sys.platform == "darwin" else None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="XWorkbench")
if sys.platform == "darwin":
    app = BUNDLE(
        coll, name="XWorkbench.app", icon=str(root / "packaging/icon.icns"),
        bundle_identifier="io.github.0xfaheng.xworkbench", version=__version__,
        info_plist={
            "CFBundleName": "X分析工作台", "CFBundleDisplayName": "X分析工作台",
            "CFBundleShortVersionString": __version__, "CFBundleVersion": __version__,
            "LSMinimumSystemVersion": "13.5", "NSHighResolutionCapable": True,
            "NSDocumentsFolderUsageDescription": "在文稿文件夹中保存本机 X 分析数据与周报。",
            "LSApplicationCategoryType": "public.app-category.productivity",
        },
    )
