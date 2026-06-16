#!/bin/bash
# PDForge — build & package script
#
# Double-click this file in Finder (or run `./package_app.command` in
# Terminal) to build the latest PDForge.app and zip it for sharing.
#
# Output: dist/PDForge-YYYY-MM-DD.zip

set -e

cd "$(dirname "$0")"

echo "==> Cleaning previous build..."
rm -rf build dist

echo "==> Activating virtual environment..."
source .venv/bin/activate

echo "==> Building PDForge.app with PyInstaller..."
pyinstaller --noconfirm pdforge.spec

echo "==> Zipping app for sharing..."
cd dist

ZIPNAME="PDForge-$(date +%Y-%m-%d).zip"
rm -f "$ZIPNAME"
ditto -c -k --keepParent PDForge.app "$ZIPNAME"

echo ""
echo "==> Done! Ready to share:"
echo "    $(pwd)/$ZIPNAME"

# Reveal the zip in Finder
open -R "$ZIPNAME"

echo ""
read -p "Press Enter to close this window..."
