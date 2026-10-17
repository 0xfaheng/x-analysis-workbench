#!/bin/zsh
# 编译「X分析工作台.app」并放到工作台根目录。用法：app/build.sh
set -euo pipefail

APP_DIR="${0:A:h}"
ROOT="${APP_DIR:h}"
BUILD="$APP_DIR/build"
APP="$ROOT/X分析工作台.app"
EXE="XWorkbench"

rm -rf "$BUILD"
mkdir -p "$BUILD"

swiftc -O -swift-version 5 -parse-as-library \
  -target arm64-apple-macos14.0 \
  -o "$BUILD/$EXE" "$APP_DIR"/Sources/*.swift \
  -framework SwiftUI -framework WebKit -framework AppKit

# 图标
swift "$APP_DIR/icon.swift" "$BUILD/icon_1024.png"
ICONSET="$BUILD/AppIcon.iconset"
mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
  sips -z $s $s "$BUILD/icon_1024.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  sips -z $((s * 2)) $((s * 2)) "$BUILD/icon_1024.png" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$BUILD/AppIcon.icns"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BUILD/$EXE" "$APP/Contents/MacOS/$EXE"
cp "$BUILD/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key><string>$EXE</string>
  <key>CFBundleIdentifier</key><string>com.rulan.x-workbench</string>
  <key>CFBundleName</key><string>X分析工作台</string>
  <key>CFBundleDisplayName</key><string>X分析工作台</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSApplicationCategoryType</key><string>public.app-category.productivity</string>
</dict>
</plist>
PLIST
codesign --force --deep -s - "$APP" >/dev/null
echo "built: $APP"
