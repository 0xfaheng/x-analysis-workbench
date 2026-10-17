param([string]$Python = "python")
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProjectRoot = Split-Path $PSScriptRoot -Parent
Push-Location $ProjectRoot
try {
    function Invoke-Python {
        & $Python @args
        if ($LASTEXITCODE -ne 0) { throw "Python 步骤失败，退出码 $LASTEXITCODE" }
    }
    Invoke-Python -m pip install -r packaging/requirements-windows.txt
    $AppVersion = (& $Python scripts/version.py).Trim()
    if ($LASTEXITCODE -ne 0 -or $AppVersion -notmatch '^\d+\.\d+\.\d+$') { throw "版本号无效" }
    Invoke-Python -m unittest discover -s tests
    Invoke-Python -m PyInstaller --noconfirm --clean packaging/xworkbench.spec
    foreach ($Resource in @("desktop/ui/index.html", "config.json", "docs/Windows安装与使用.md",
                             "scripts/run_weekly.py", "playwright/driver/node.exe", "playwright/driver/package/cli.js")) {
        if (-not (Test-Path (Join-Path "dist/XWorkbench/_internal" $Resource))) { throw "冻结包缺少资源：$Resource" }
    }

    # windowed 程序使用 Start-Process 并显式等待，不能直接读取陈旧的 LASTEXITCODE。
    $FixtureRoot = Join-Path ([IO.Path]::GetTempPath()) ("XWB 合成冒烟-" + [guid]::NewGuid().ToString("N"))
    try {
        Invoke-Python tests/make_fixture.py --out $FixtureRoot
        $FixtureDate = (& $Python tests/make_fixture.py --print-date).Trim()
        if ($LASTEXITCODE -ne 0) { throw "无法读取夹具日期" }
        $Executable = Join-Path $ProjectRoot "dist/XWorkbench/XWorkbench.exe"
        $JobLog = Join-Path $FixtureRoot "frozen-smoke.log"
        $Arguments = "--job-log `"$JobLog`" --run-weekly --skip-collect --root `"$FixtureRoot`" --date $FixtureDate"
        $Process = Start-Process -FilePath $Executable -ArgumentList $Arguments -PassThru
        $null = $Process.Handle
        if (-not $Process.WaitForExit(120000)) { $Process.Kill(); throw "冻结包冒烟测试超时" }
        $Process.Refresh()
        if (Test-Path $JobLog) { Get-Content -Encoding utf8 $JobLog }
        if ($Process.ExitCode -ne 0) { throw "冻结包退出码 $($Process.ExitCode)" }
        foreach ($File in @("reports/$FixtureDate/report.html", "index.html")) {
            if (-not (Test-Path (Join-Path $FixtureRoot $File))) { throw "冻结包缺少输出：$File" }
        }
    } finally {
        if (Test-Path $FixtureRoot) { Remove-Item -LiteralPath $FixtureRoot -Recurse -Force }
    }

    $Compiler = Get-Command ISCC.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source
    if (-not $Compiler) {
        $Candidate = Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6/ISCC.exe"
        if (Test-Path $Candidate) { $Compiler = $Candidate }
    }
    if (-not $Compiler) {
        & choco install innosetup --yes --no-progress
        if ($LASTEXITCODE -ne 0) { throw "Inno Setup 安装失败" }
        $Compiler = Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6/ISCC.exe"
    }
    & $Compiler "/DAppVersion=$AppVersion" packaging/installer.iss
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup 编译失败" }

    # 便携版把默认配置放在 exe 同级，触发便携 root 解析；用户升级前先备份。
    $PortableRoot = Join-Path $ProjectRoot "build/portable/XWorkbench"
    if (Test-Path $PortableRoot) { Remove-Item -LiteralPath $PortableRoot -Recurse -Force }
    New-Item -ItemType Directory -Force $PortableRoot | Out-Null
    Copy-Item -Path "dist/XWorkbench/*" -Destination $PortableRoot -Recurse -Force
    Copy-Item -LiteralPath config.json -Destination $PortableRoot
    $Zip = Join-Path $ProjectRoot "dist/XWorkbench-$AppVersion-portable.zip"
    if (Test-Path $Zip) { Remove-Item -LiteralPath $Zip -Force }
    Compress-Archive -LiteralPath $PortableRoot -DestinationPath $Zip -CompressionLevel Optimal
    foreach ($Output in @("dist/XWorkbench-Setup-$AppVersion.exe", "dist/XWorkbench-$AppVersion-portable.zip")) {
        if (-not (Test-Path $Output)) { throw "缺少发布产物：$Output" }
        Get-FileHash -Algorithm SHA256 $Output
    }
} finally {
    Pop-Location
}
