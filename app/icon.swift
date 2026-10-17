// 生成应用图标：深色圆角底 + 三根上升柱 + X 字样。用法：swift icon.swift <输出 1024px png>
import AppKit

let out = CommandLine.arguments[1]
let S: CGFloat = 1024
let img = NSImage(size: NSSize(width: S, height: S))
img.lockFocus()
let bg = NSBezierPath(roundedRect: NSRect(x: 100, y: 100, width: 824, height: 824), xRadius: 185, yRadius: 185)
NSGradient(colors: [NSColor(red: 0.07, green: 0.08, blue: 0.10, alpha: 1),
                    NSColor(red: 0.13, green: 0.16, blue: 0.22, alpha: 1)])!.draw(in: bg, angle: 90)
let blue = NSColor(red: 0.16, green: 0.47, blue: 0.84, alpha: 1)
for (i, h) in [CGFloat(170), 290, 430].enumerated() {
    let x = 250 + CGFloat(i) * 140
    let bar = NSBezierPath(roundedRect: NSRect(x: x, y: 230, width: 96, height: h), xRadius: 18, yRadius: 18)
    (i == 2 ? NSColor(red: 0.92, green: 0.41, blue: 0.20, alpha: 1) : blue).setFill()
    bar.fill()
}
let para = NSMutableParagraphStyle(); para.alignment = .right
let attrs: [NSAttributedString.Key: Any] = [
    .font: NSFont.systemFont(ofSize: 300, weight: .heavy),
    .foregroundColor: NSColor.white, .paragraphStyle: para,
]
NSString(string: "X").draw(in: NSRect(x: 420, y: 520, width: 380, height: 360), withAttributes: attrs)
img.unlockFocus()
let png = NSBitmapImageRep(data: img.tiffRepresentation!)!.representation(using: .png, properties: [:])!
try! png.write(to: URL(fileURLWithPath: out))
