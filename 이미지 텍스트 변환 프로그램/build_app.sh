#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

echo "=========================================="
echo "  macOS SwiftUI OCR App 빌드를 시작합니다. "
echo "=========================================="

APP_NAME="이미지 텍스트 추출기"
SWIFT_FILE="mac_ocr_app.swift"
APP_DIR="${APP_NAME}.app"
DESKTOP_DIR="${HOME}/Desktop"

# 1. Clean previous build artifacts
echo "🧹 기존 빌드 잔재를 정리하는 중..."
rm -rf "$APP_DIR"
rm -f "AppBinary"

# 2. Compile SwiftUI app source code
echo "⚙️ Swift 소스 코드를 컴파일하는 중 (swiftc)..."
SDK_PATH=$(xcrun --show-sdk-path)
swiftc -O -sdk "$SDK_PATH" -parse-as-library "$SWIFT_FILE" -o "AppBinary"

# 3. Create macOS .app bundle directory structure
echo "📁 앱 번들 디렉토리 구조 생성 중..."
mkdir -p "${APP_DIR}/Contents/MacOS"

# 4. Move compiled binary into the bundle
mv "AppBinary" "${APP_DIR}/Contents/MacOS/${APP_NAME}"
chmod +x "${APP_DIR}/Contents/MacOS/${APP_NAME}"

# 5. Generate Info.plist file
echo "📄 Info.plist 설정 파일 작성 중..."
cat <<EOF > "${APP_DIR}/Contents/Info.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>${APP_NAME}</string>
    <key>CFBundleIdentifier</key>
    <string>com.ksd.image-ocr-app</string>
    <key>CFBundleName</key>
    <string>${APP_NAME}</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>LSMinimumSystemVersion</key>
    <string>13.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
EOF

# 6. Copy the finalized app to Desktop
echo "🚀 완성된 앱을 바탕화면으로 복사하는 중..."
rm -rf "${DESKTOP_DIR}/${APP_NAME}.app"
cp -R "$APP_DIR" "${DESKTOP_DIR}/"

echo "=========================================="
echo "🎉 빌드 완료! 바탕화면에 '${APP_NAME}' 앱이 생성되었습니다."
echo "👉 바탕화면에서 '${APP_NAME}' 앱을 더블클릭해서 사용해 보세요!"
echo "=========================================="
