#!/bin/sh
set -eu

PROJECT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
BUNDLE_DIR="$PROJECT_DIR/desktop/src-tauri/target/release/bundle"
APP_PATH="$(find "$BUNDLE_DIR/macos" -maxdepth 1 -type d -name '*.app' -print -quit)"
DMG_PATH="$(find "$BUNDLE_DIR/dmg" -maxdepth 1 -type f -name '*.dmg' -print -quit)"
MOUNT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/research-memory-dmg.XXXXXX")"
MOUNTED=0

cleanup() {
  if [ "$MOUNTED" -eq 1 ]; then
    hdiutil detach "$MOUNT_DIR" -quiet || true
  fi
  rmdir "$MOUNT_DIR" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

test -n "$APP_PATH"
test -n "$DMG_PATH"
python3 "$PROJECT_DIR/scripts/verify_macos_bundle.py" \
  "$APP_PATH" --maximum-deployment-target 13.0
codesign --verify --deep --strict --verbose=2 "$APP_PATH"
TESSERACT_PATH="$APP_PATH/Contents/MacOS/tesseract"
TESSDATA_PATH="$APP_PATH/Contents/Resources/resources/tessdata"
TESSDATA_PREFIX="$TESSDATA_PATH" "$TESSERACT_PATH" --version |
  grep -F "tesseract 5.5.2"
TESSDATA_PREFIX="$TESSDATA_PATH" "$TESSERACT_PATH" --list-langs |
  grep -Fx "eng"
TESSDATA_PREFIX="$TESSDATA_PATH" "$TESSERACT_PATH" --list-langs |
  grep -Fx "osd"
MODEL_ROOT="$APP_PATH/Contents/Resources/resources/models"
MODEL_MANIFEST="$MODEL_ROOT/model-manifest.json"
MODEL_REVISION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["revision"])' "$MODEL_MANIFEST")"
MODEL_FILENAME="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["onnx_file"])' "$MODEL_MANIFEST")"
EXPECTED_MODEL_HASH="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["onnx_sha256"])' "$MODEL_MANIFEST")"
MODEL_PATH="$(find "$MODEL_ROOT" -type f \
  -path "*/snapshots/$MODEL_REVISION/$MODEL_FILENAME" -print -quit)"
test -n "$MODEL_PATH"
ACTUAL_MODEL_HASH="$(shasum -a 256 "$MODEL_PATH" | awk '{print $1}')"
test "$ACTUAL_MODEL_HASH" = "$EXPECTED_MODEL_HASH"
"$PROJECT_DIR/scripts/smoke_macos_app.sh" "$APP_PATH"
spctl --assess --type execute --verbose=4 "$APP_PATH"
xcrun stapler validate "$APP_PATH"
hdiutil verify "$DMG_PATH"
xcrun stapler validate "$DMG_PATH"
test -n "$(find "$BUNDLE_DIR/macos" -maxdepth 1 -type f -name '*.sig' -print -quit)"

hdiutil attach "$DMG_PATH" -nobrowse -readonly -mountpoint "$MOUNT_DIR"
MOUNTED=1
MOUNTED_APP="$(find "$MOUNT_DIR" -maxdepth 1 -type d -name '*.app' -print -quit)"
test -n "$MOUNTED_APP"
codesign --verify --deep --strict --verbose=2 "$MOUNTED_APP"
spctl --assess --type execute --verbose=4 "$MOUNTED_APP"
if [ -n "${EXPECTED_BUNDLE_IDENTIFIER:-}" ]; then
  codesign -dv --verbose=4 "$MOUNTED_APP" 2>&1 |
    grep -F "Identifier=$EXPECTED_BUNDLE_IDENTIFIER"
fi
