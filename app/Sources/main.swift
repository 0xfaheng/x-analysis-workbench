// X 分析工作台：独立运行的 macOS 应用。
// 左侧列出历次周报，右侧显示报告（应用内嵌渲染，不打开浏览器）；
// 工具栏可「仅更新数据」（本机运行 scripts/run_weekly.sh）或「生成完整周报」（让 mirasim 立即运行每周定时任务，由助手写建议）。

import AppKit
import SwiftUI
import WebKit

// MARK: - 路径与配置

enum Paths {
    static let home = FileManager.default.homeDirectoryForCurrentUser

    /// 工作台根目录：优先取应用所在目录（应用和工作台放在一起），否则用桌面默认位置。
    static let root: URL = {
        if let env = ProcessInfo.processInfo.environment["XWB_ROOT"] {
            return URL(fileURLWithPath: env)
        }
        let beside = Bundle.main.bundleURL.deletingLastPathComponent()
        if FileManager.default.fileExists(atPath: beside.appendingPathComponent("config.json").path) {
            return beside
        }
        return home.appendingPathComponent("Desktop/X分析工作台")
    }()

    static var mirasim: String { home.appendingPathComponent(".mirasim/bin/mirasim").path }

    static var childPATH: String {
        [
            home.appendingPathComponent(".local/bin").path,
            "/Library/Frameworks/Python.framework/Versions/3.13/bin",
            "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin",
        ].joined(separator: ":")
    }
}

struct AppConfig {
    var handle = "0xfaheng"
    var scheduleID: String?
    var scheduleWorkspace: String?
    var port = 4970

    static func load() -> AppConfig {
        var c = AppConfig()
        let url = Paths.root.appendingPathComponent("config.json")
        guard let data = try? Data(contentsOf: url),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return c }
        if let h = obj["handle"] as? String { c.handle = h }
        if let app = obj["app"] as? [String: Any] {
            c.scheduleID = app["mirasim_schedule_id"] as? String
            c.scheduleWorkspace = app["mirasim_workspace"] as? String
            if let p = app["mirasim_port"] as? Int { c.port = p }
        }
        return c
    }
}

// MARK: - 周报列表

struct ReportItem: Identifiable, Hashable {
    let id: String               // 报告日期 YYYY-MM-DD
    let dir: URL
    var eligibility: Int?        // 近 90 天认证用户首页曝光
    var targetsMet: Int?
    var targetsTotal: Int?
    var mainPosts: Int?
    var median: Int?
    var pendingSuggestions = false
    var htmlModified: Date?

    var htmlURL: URL { dir.appendingPathComponent("report.html") }
    var progress: Double? { eligibility.map { min(Double($0) / 500_000, 1) } }
}

func formatCount(_ n: Int?) -> String {
    guard let n else { return "—" }
    if abs(n) >= 10_000 {
        let v = Double(n) / 10_000
        return (v.truncatingRemainder(dividingBy: 1) == 0 ? String(format: "%.0f", v) : String(format: "%.1f", v)) + " 万"
    }
    let f = NumberFormatter()
    f.numberStyle = .decimal
    return f.string(from: NSNumber(value: n)) ?? "\(n)"
}

// MARK: - 子进程

enum Runner {
    /// 运行一个命令，实时回调输出，返回退出码。
    static func run(_ executable: String, _ args: [String], cwd: URL,
                    onOutput: @escaping @Sendable (String) -> Void) async -> Int32 {
        await withCheckedContinuation { cont in
            let p = Process()
            p.executableURL = URL(fileURLWithPath: executable)
            p.arguments = args
            p.currentDirectoryURL = cwd
            var env = ProcessInfo.processInfo.environment
            env["PATH"] = Paths.childPATH
            env["PYTHONUNBUFFERED"] = "1"
            p.environment = env
            let pipe = Pipe()
            p.standardOutput = pipe
            p.standardError = pipe
            let outputLock = NSLock()
            pipe.fileHandleForReading.readabilityHandler = { h in
                outputLock.lock()
                defer { outputLock.unlock() }
                let d = h.availableData
                if !d.isEmpty { onOutput(String(decoding: d, as: UTF8.self)) }
            }
            p.terminationHandler = { proc in
                pipe.fileHandleForReading.readabilityHandler = nil
                // 等待正在进行的读取与回调结束，再排空尾部并返回退出码。
                outputLock.lock()
                defer { outputLock.unlock() }
                let rest = pipe.fileHandleForReading.readDataToEndOfFile()
                if !rest.isEmpty { onOutput(String(decoding: rest, as: UTF8.self)) }
                cont.resume(returning: proc.terminationStatus)
            }
            do {
                try p.run()
            } catch {
                pipe.fileHandleForReading.readabilityHandler = nil
                p.terminationHandler = nil
                try? pipe.fileHandleForReading.close()
                try? pipe.fileHandleForWriting.close()
                onOutput("无法启动 \(executable)：\(error.localizedDescription)\n")
                cont.resume(returning: -1)
            }
        }
    }

    /// 运行并收集全部输出。
    static func capture(_ executable: String, _ args: [String], cwd: URL) async -> (Int32, String) {
        let box = OutputBox()
        let code = await run(executable, args, cwd: cwd) { box.append($0) }
        return (code, box.text)
    }
}

final class OutputBox: @unchecked Sendable {
    private let lock = NSLock()
    private var buf = ""
    func append(_ s: String) { lock.lock(); buf += s; lock.unlock() }
    var text: String { lock.lock(); defer { lock.unlock() }; return buf }
}

// MARK: - 状态模型

@MainActor
final class Workbench: ObservableObject {
    enum Job { case collect, assistant }

    @Published var reports: [ReportItem] = []
    @Published var selection: String?
    @Published var job: Job?
    @Published var status = ""
    @Published var statusIsError = false
    @Published var log = ""
    @Published var showLog = false
    @Published var confirmAssistant = false

    let config = AppConfig.load()
    private var refreshTimer: Timer?

    init() {
        refresh(selectLatest: true)
        refreshTimer = Timer.scheduledTimer(withTimeInterval: 20, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.refresh(selectLatest: false) }
        }
        if reports.isEmpty { status = "还没有周报，点击工具栏「仅更新数据」开始第一次采集" }
    }

    var selected: ReportItem? { reports.first { $0.id == selection } }

    func refresh(selectLatest: Bool) {
        let fm = FileManager.default
        let reportsDir = Paths.root.appendingPathComponent("reports")
        var history: [String: [String: Any]] = [:]
        if let data = try? Data(contentsOf: Paths.root.appendingPathComponent("data/history.json")),
           let arr = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]] {
            for h in arr { if let d = h["report_date"] as? String { history[d] = h } }
        }
        let dirs = ((try? fm.contentsOfDirectory(at: reportsDir, includingPropertiesForKeys: nil)) ?? [])
            .filter { fm.fileExists(atPath: $0.appendingPathComponent("analysis.json").path) }
            .sorted { $0.lastPathComponent > $1.lastPathComponent }
        let items: [ReportItem] = dirs.map { dir in
            let d = dir.lastPathComponent
            let h = history[d] ?? [:]
            var item = ReportItem(id: d, dir: dir)
            item.eligibility = h["eligibility_verified_home_90d"] as? Int
            item.targetsMet = h["targets_met"] as? Int
            item.targetsTotal = h["targets_total"] as? Int
            item.mainPosts = h["main_posts"] as? Int
            item.median = h["median"] as? Int
            if let md = try? String(contentsOf: dir.appendingPathComponent("report.md"), encoding: .utf8) {
                item.pendingSuggestions = md.contains("（待助手填写")
            }
            item.htmlModified = (try? fm.attributesOfItem(atPath: item.htmlURL.path))?[.modificationDate] as? Date
            return item
        }
        if items != reports { reports = items }
        if selectLatest || selection == nil || !items.contains(where: { $0.id == selection }) {
            selection = items.first?.id
        }
    }

    private func appendLog(_ s: String) { log += s }

    private func setStatus(_ s: String, error: Bool = false) {
        status = s
        statusIsError = error
    }

    // 仅更新数据：采集 + 分析 + 生成网页，不写建议。
    func collect() {
        guard job == nil else { return }
        job = .collect
        log = "$ ./scripts/run_weekly.sh\n"
        setStatus("正在通过 ego 浏览器读取 X 数据，大约 1–2 分钟…")
        Task {
            let code = await Runner.run("/bin/zsh", [Paths.root.appendingPathComponent("scripts/run_weekly.sh").path],
                                        cwd: Paths.root) { s in Task { @MainActor in self.appendLog(s) } }
            switch code {
            case 0:
                setStatus("数据已更新。「下周调整建议」需要助手撰写，可点「生成完整周报」。")
            case 3:
                setStatus("X 未登录：请在 ego 浏览器里登录 @\(config.handle) 后重试。", error: true)
                showLog = true
            case 4:
                setStatus("采集失败：请确认 ego lite 正在运行，详情见运行日志。", error: true)
                showLog = true
            default:
                setStatus("运行失败（退出码 \(code)），详情见运行日志。", error: true)
                showLog = true
            }
            job = nil
            refresh(selectLatest: code == 0)
        }
    }

    // 生成完整周报：让 mirasim 立即运行每周定时任务（采集、助手写建议、生成网页、发到对话）。
    func runAssistant() {
        guard job == nil else { return }
        guard let id = config.scheduleID, let ws = config.scheduleWorkspace else {
            setStatus("config.json 里没有配置 mirasim 定时任务，无法调用助手。", error: true)
            return
        }
        job = .assistant
        log = "$ mirasim ui-cli schedule run --id \(id)\n"
        setStatus("正在把任务交给助手…")
        let port = String(config.port)
        Task {
            let (code, out) = await Runner.capture(Paths.mirasim,
                ["ui-cli", "--port", port, "schedule", "run", "--cwd", ws, "--id", id], cwd: Paths.root)
            appendLog(out + "\n")
            guard code == 0 else {
                if out.contains("no local access token") || out.contains("ECONNREFUSED") {
                    setStatus("mirasim 没有在运行：请先打开 mirasim 再试。", error: true)
                } else {
                    setStatus("调用助手失败，详情见运行日志。", error: true)
                }
                showLog = true
                job = nil
                return
            }
            setStatus("助手正在生成本周周报（采集、写建议、生成网页），通常需要 5–15 分钟，完成后自动显示。")
            await waitForSchedule(id: id, port: port)
            job = nil
            refresh(selectLatest: true)
        }
    }

    private func waitForSchedule(id: String, port: String) async {
        let start = Date()
        var sawRunning = false
        while Date().timeIntervalSince(start) < 45 * 60 {
            try? await Task.sleep(nanoseconds: 20_000_000_000)
            refresh(selectLatest: false)
            let (code, out) = await Runner.capture(Paths.mirasim, ["ui-cli", "--port", port, "schedule"], cwd: Paths.root)
            guard code == 0, let entry = Self.findSchedule(id: id, in: out) else { continue }
            let running = entry["running"] as? Bool ?? false
            if running { sawRunning = true; continue }
            if sawRunning || Date().timeIntervalSince(start) > 90 {
                if let last = entry["lastRun"], let data = try? JSONSerialization.data(withJSONObject: last, options: [.prettyPrinted]) {
                    appendLog("最近一次运行：\n" + String(decoding: data, as: UTF8.self) + "\n")
                }
                setStatus("助手已完成本周周报。")
                return
            }
        }
        setStatus("等待超过 45 分钟，请到 mirasim 里查看这次周报会话。", error: true)
    }

    private static func findSchedule(id: String, in json: String) -> [String: Any]? {
        guard let obj = try? JSONSerialization.jsonObject(with: Data(json.utf8)) else { return nil }
        var found: [String: Any]?
        func walk(_ o: Any) {
            if found != nil { return }
            if let d = o as? [String: Any] {
                if d["id"] as? String == id, d["cron"] != nil { found = d; return }
                d.values.forEach(walk)
            } else if let a = o as? [Any] {
                a.forEach(walk)
            }
        }
        walk(obj)
        return found
    }

    func open(_ relative: String) {
        NSWorkspace.shared.open(Paths.root.appendingPathComponent(relative))
    }
}

// MARK: - 报告视图（WKWebView 内嵌渲染）

struct ReportWebView: NSViewRepresentable {
    let url: URL
    let version: Date?

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeNSView(context: Context) -> WKWebView {
        let cfg = WKWebViewConfiguration()
        // 应用左侧已有周报列表，隐藏网页里的导航和历史链接
        let css = ".nav, .history { display: none !important; } .wrap { padding-top: 18px !important; }"
        let js = "var s=document.createElement('style');s.textContent=\(String(reflecting: css));document.head.appendChild(s);"
        cfg.userContentController.addUserScript(WKUserScript(source: js, injectionTime: .atDocumentEnd, forMainFrameOnly: true))
        let wv = WKWebView(frame: .zero, configuration: cfg)
        wv.navigationDelegate = context.coordinator
        wv.uiDelegate = context.coordinator
        wv.allowsMagnification = true
        SnapshotAgent.shared.webView = wv
        return wv
    }

    func updateNSView(_ wv: WKWebView, context: Context) {
        let key = url.path + "#\(version?.timeIntervalSince1970 ?? 0)"
        if context.coordinator.loadedKey != key {
            context.coordinator.loadedKey = key
            wv.loadFileURL(url, allowingReadAccessTo: Paths.root)
        }
    }

    @MainActor
    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate {
        var loadedKey = ""

        // 帖子链接等外部网址交给系统默认方式打开，报告本身始终留在应用里
        func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction) async -> WKNavigationActionPolicy {
            if let u = navigationAction.request.url, let scheme = u.scheme, scheme == "http" || scheme == "https" {
                NSWorkspace.shared.open(u)
                return .cancel
            }
            return .allow
        }

        func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                     for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
            if let u = navigationAction.request.url { NSWorkspace.shared.open(u) }
            return nil
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            SnapshotAgent.shared.pageLoaded()
        }
    }
}

// MARK: - 界面

struct ReportRow: View {
    let item: ReportItem

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(item.id).font(.headline).monospacedDigit()
                Spacer()
                if item.pendingSuggestions {
                    Text("待写建议")
                        .font(.caption2)
                        .padding(.horizontal, 6).padding(.vertical, 2)
                        .background(Color.orange.opacity(0.18), in: Capsule())
                }
            }
            if let p = item.progress {
                ProgressView(value: p).controlSize(.small)
            }
            Text("门槛 \(formatCount(item.eligibility)) / 50 万 · 目标 \(item.targetsMet.map(String.init) ?? "—")/\(item.targetsTotal.map(String.init) ?? "—")")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(.vertical, 4)
    }
}

struct LogView: View {
    @EnvironmentObject var wb: Workbench

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                Text(wb.log.isEmpty ? "还没有运行记录" : wb.log)
                    .font(.system(.caption, design: .monospaced))
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(10)
                Color.clear.frame(height: 1).id("bottom")
            }
            .onChange(of: wb.log) { _, _ in proxy.scrollTo("bottom", anchor: .bottom) }
        }
    }
}

struct ContentView: View {
    @EnvironmentObject var wb: Workbench

    var body: some View {
        NavigationSplitView {
            List(selection: $wb.selection) {
                Section("每周报告") {
                    ForEach(wb.reports) { r in
                        ReportRow(item: r).tag(r.id)
                    }
                }
            }
            .navigationSplitViewColumnWidth(min: 230, ideal: 260, max: 340)
            .safeAreaInset(edge: .bottom) { footer }
        } detail: {
            detail
        }
        .navigationTitle("X 分析工作台")
        .navigationSubtitle("@\(wb.config.handle)")
        .toolbar {
            ToolbarItemGroup(placement: .primaryAction) {
                Button { wb.confirmAssistant = true } label: {
                    Label("生成完整周报", systemImage: "sparkles")
                }
                .help("让助手采集数据、撰写下周调整建议并生成报告")
                .disabled(wb.job != nil)

                Button { wb.collect() } label: {
                    Label("仅更新数据", systemImage: "arrow.down.circle")
                }
                .help("只采集和统计 X 数据，不写建议（约 1–2 分钟）")
                .disabled(wb.job != nil)

                Button { wb.showLog.toggle() } label: {
                    Label("运行日志", systemImage: "terminal")
                }
                .help("显示或隐藏运行日志")

                Menu {
                    Button("在访达中打开工作台文件夹") { wb.open("") }
                    if let r = wb.selected {
                        Button("打开本期报告原文（report.md）") { NSWorkspace.shared.open(r.dir.appendingPathComponent("report.md")) }
                    }
                    Divider()
                    Button("查看策略基线") { wb.open("docs/策略基线.md") }
                    Button("查看周报流程") { wb.open("docs/周报流程.md") }
                    Button("编辑阶段目标（config.json）") { wb.open("config.json") }
                } label: {
                    Label("更多", systemImage: "ellipsis.circle")
                }
            }
        }
        .inspector(isPresented: $wb.showLog) {
            LogView().inspectorColumnWidth(min: 280, ideal: 380, max: 600)
        }
        .confirmationDialog("生成本周完整周报？", isPresented: $wb.confirmAssistant) {
            Button("开始生成") { wb.runAssistant() }
            Button("取消", role: .cancel) {}
        } message: {
            Text("将由 mirasim 立即运行每周周报任务：采集 X 数据、助手撰写下周调整建议、生成报告并发到 mirasim 对话。需要 mirasim 和 ego lite 都在运行，通常 5–15 分钟。全程只读，不会发帖或修改账号。")
        }
    }

    @ViewBuilder private var detail: some View {
        if let r = wb.selected, r.htmlModified != nil {
            ReportWebView(url: r.htmlURL, version: r.htmlModified)
        } else if wb.reports.isEmpty {
            ContentUnavailableView("还没有周报", systemImage: "chart.bar.xaxis",
                                   description: Text("点击工具栏「仅更新数据」开始第一次采集"))
        } else {
            ContentUnavailableView("这一期还没有生成报告页面", systemImage: "doc.text",
                                   description: Text("点击「仅更新数据」或「生成完整周报」重新生成"))
        }
    }

    private var footer: some View {
        HStack(alignment: .top, spacing: 8) {
            if wb.job != nil {
                ProgressView().controlSize(.small)
            } else if wb.statusIsError {
                Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.orange)
            }
            Text(wb.status.isEmpty ? "数据来自 X Creator Studio 与 Analytics" : wb.status)
                .font(.caption)
                .foregroundStyle(wb.statusIsError ? .primary : .secondary)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
        .padding(10)
        .background(.bar)
    }
}

// MARK: - 自检截图（--snapshot <png>，用于验收，截完即退出）

@MainActor
final class SnapshotAgent {
    static let shared = SnapshotAgent()
    var target: String?
    weak var webView: WKWebView?
    private var done = false

    func pageLoaded() {
        guard let target, !done else { return }
        done = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { self.capture(to: target) }
    }

    private func capture(to path: String) {
        guard let window = NSApp.windows.first(where: { $0.isVisible }), let content = window.contentView,
              let rep = content.bitmapImageRepForCachingDisplay(in: content.bounds) else { NSApp.terminate(nil); return }
        content.cacheDisplay(in: content.bounds, to: rep)
        let size = content.bounds.size
        guard let wv = webView else { NSApp.terminate(nil); return }
        wv.takeSnapshot(with: nil) { image, _ in
            let composite = NSImage(size: size)
            composite.lockFocus()
            rep.draw(in: NSRect(origin: .zero, size: size))
            if let image {
                var r = wv.convert(wv.bounds, to: content)
                if content.isFlipped { r.origin.y = size.height - r.maxY }
                image.draw(in: r)
            }
            composite.unlockFocus()
            if let tiff = composite.tiffRepresentation, let bmp = NSBitmapImageRep(data: tiff),
               let png = bmp.representation(using: .png, properties: [:]) {
                try? png.write(to: URL(fileURLWithPath: path))
            }
            NSApp.terminate(nil)
        }
    }
}

// MARK: - 应用入口

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

@main
struct XWorkbenchApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject private var wb = Workbench()

    init() {
        let args = ProcessInfo.processInfo.arguments
        if let i = args.firstIndex(of: "--snapshot"), i + 1 < args.count {
            MainActor.assumeIsolated { SnapshotAgent.shared.target = args[i + 1] }
        }
    }

    var body: some Scene {
        Window("X 分析工作台", id: "main") {
            ContentView()
                .environmentObject(wb)
                .frame(minWidth: 1000, minHeight: 680)
        }
        .defaultSize(width: 1380, height: 900)
    }
}
