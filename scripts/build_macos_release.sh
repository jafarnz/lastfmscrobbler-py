#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$PROJECT_ROOT/dist/macos"
BUILD_DIR="$PROJECT_ROOT/build/macos"
APP_NAME="CuntyScrobbler"
IDENTIFIER="com.jafarnz.cuntyscrobbler"

if ! command -v pyinstaller >/dev/null 2>&1; then
  echo "pyinstaller is not installed. Install it with 'pip install pyinstaller' inside your virtualenv." >&2
  exit 1
fi

rm -rf "$DIST_DIR" "$BUILD_DIR"
mkdir -p "$DIST_DIR"

pyinstaller \
  "$PROJECT_ROOT/gui.py" \
  --name "$APP_NAME" \
  --windowed \
  --noconfirm \
  --clean \
  --distpath "$DIST_DIR" \
  --workpath "$BUILD_DIR" \
  --osx-bundle-identifier "$IDENTIFIER"

pushd "$DIST_DIR" >/dev/null
ZIP_NAME="${APP_NAME}-macos.zip"
rm -f "$ZIP_NAME"
zip -r "$ZIP_NAME" "${APP_NAME}.app"
popd >/dev/null

echo "macOS app available at $DIST_DIR/${APP_NAME}.app"
echo "Zip ready for release: $DIST_DIR/$ZIP_NAME"
