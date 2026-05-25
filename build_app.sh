#!/bin/bash
# WineGarden.app を作るスクリプト

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="WineGarden"
APP="$SCRIPT_DIR/$APP_NAME.app"

echo "🌿 WineGarden.app を作成中..."

# 既存の .app を削除
rm -rf "$APP"

# フォルダ構造を作成
mkdir -p "$APP/Contents/MacOS"
mkdir -p "$APP/Contents/Resources/assets"

# WineGarden.py をコピー
cp "$SCRIPT_DIR/WineGarden.py" "$APP/Contents/Resources/WineGarden.py"

# assets をコピー（画像など）
if [ -d "$SCRIPT_DIR/assets" ]; then
    cp -r "$SCRIPT_DIR/assets/." "$APP/Contents/Resources/assets/"
fi

# 起動スクリプトを作成
cat > "$APP/Contents/MacOS/$APP_NAME" << 'LAUNCHER'
#!/bin/bash
DIR="$(cd "$(dirname "$0")/../Resources" && pwd)"

# Python を探す
for py in \
    /usr/local/bin/python3.11 \
    /opt/homebrew/bin/python3.11 \
    /usr/local/bin/python3 \
    /usr/bin/python3
do
    if [ -x "$py" ]; then
        exec "$py" "$DIR/WineGarden.py"
    fi
done

osascript -e 'display alert "WineGarden エラー" message "Python 3 が見つかりませんでした。\n/usr/local/bin/python3.11 を確認してください。"'
exit 1
LAUNCHER

chmod +x "$APP/Contents/MacOS/$APP_NAME"

# Info.plist を作成
cat > "$APP/Contents/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>WineGarden</string>
    <key>CFBundleIdentifier</key>
    <string>com.winegarden.app</string>
    <key>CFBundleName</key>
    <string>WineGarden</string>
    <key>CFBundleDisplayName</key>
    <string>🌿 WineGarden</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>LSMinimumSystemVersion</key>
    <string>13.0</string>
</dict>
</plist>
PLIST

echo "✅ 完成: $APP"
echo ""
echo "デスクトップに WineGarden.app が作成されました。"
echo "ダブルクリックで起動できます。"
