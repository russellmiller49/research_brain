#!/bin/sh
set -eu

PROJECT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
TARGET_TRIPLE="${TARGET_TRIPLE:-aarch64-apple-darwin}"
TESSERACT_PREFIX="${TESSERACT_ENV_PREFIX:-${CONDA_PREFIX:-}}"
VERIFY_PYTHON="${VERIFY_PYTHON:-python3}"
TAURI_DIR="$PROJECT_DIR/desktop/src-tauri"
PATCHED_BIN="$TAURI_DIR/binaries/tesseract-$TARGET_TRIPLE"
LIB_DIR="$TAURI_DIR/resources/tesseract-libs"
DATA_DIR="$TAURI_DIR/resources/tessdata"

test "$(uname -m)" = "arm64" || {
  echo "Tesseract must be packaged on an Apple-silicon runner." >&2
  exit 1
}
test "$TARGET_TRIPLE" = "aarch64-apple-darwin" || {
  echo "Unsupported Tesseract target: $TARGET_TRIPLE" >&2
  exit 1
}
test -n "$TESSERACT_PREFIX" || {
  echo "Activate the locked Tesseract environment or set TESSERACT_ENV_PREFIX." >&2
  exit 1
}

TESSERACT_BIN="${TESSERACT_BIN:-$TESSERACT_PREFIX/bin/tesseract}"
TESSDATA_DIR="${TESSDATA_DIR:-$TESSERACT_PREFIX/share/tessdata}"

command -v dylibbundler >/dev/null 2>&1 || {
  echo "Install dylibbundler before packaging Tesseract." >&2
  exit 1
}
test -x "$TESSERACT_BIN" || {
  echo "Missing Tesseract executable: $TESSERACT_BIN" >&2
  exit 1
}
test -f "$TESSDATA_DIR/eng.traineddata" || {
  echo "Missing English Tesseract data." >&2
  exit 1
}
test -f "$TESSDATA_DIR/osd.traineddata" || {
  echo "Missing orientation Tesseract data." >&2
  exit 1
}

"$VERIFY_PYTHON" "$PROJECT_DIR/scripts/verify_macos_bundle.py" \
  "$TESSERACT_BIN" --maximum-deployment-target 13.0

mkdir -p "$LIB_DIR" "$DATA_DIR"
find "$LIB_DIR" -mindepth 1 -delete
find "$DATA_DIR" -mindepth 1 -delete
rm -f "$PATCHED_BIN"
cp "$TESSERACT_BIN" "$PATCHED_BIN"
chmod 755 "$PATCHED_BIN"
dylibbundler \
  -od \
  -b \
  -ns \
  -x "$PATCHED_BIN" \
  -s "$TESSERACT_PREFIX/lib" \
  -d "$LIB_DIR" \
  -p "@executable_path/../Resources/resources/tesseract-libs/"
cp "$TESSDATA_DIR/eng.traineddata" "$DATA_DIR/eng.traineddata"
cp "$TESSDATA_DIR/osd.traineddata" "$DATA_DIR/osd.traineddata"
touch "$LIB_DIR/.gitkeep" "$DATA_DIR/.gitkeep"

SIGNING_IDENTITY="${APPLE_SIGNING_IDENTITY:?Set APPLE_SIGNING_IDENTITY}"
sign_file() {
  if [ "$SIGNING_IDENTITY" = "-" ]; then
    codesign --force --sign - "$1"
  else
    codesign --force --options runtime --timestamp \
      --sign "$SIGNING_IDENTITY" "$1"
  fi
}

find "$LIB_DIR" -type f -name '*.dylib' -print0 |
  while IFS= read -r -d '' library; do
    sign_file "$library"
  done
sign_file "$PATCHED_BIN"

"$VERIFY_PYTHON" "$PROJECT_DIR/scripts/verify_macos_bundle.py" \
  "$PATCHED_BIN" --maximum-deployment-target 13.0
"$VERIFY_PYTHON" "$PROJECT_DIR/scripts/verify_macos_bundle.py" \
  "$LIB_DIR" --maximum-deployment-target 13.0
