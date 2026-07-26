#!/bin/sh
set -eu

PROJECT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3.12}"
TARGET_TRIPLE="${TARGET_TRIPLE:-aarch64-apple-darwin}"
OUTPUT_DIR="$PROJECT_DIR/desktop/src-tauri/binaries"
BUILD_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/research-memory-sidecar.XXXXXX")"
BUILD_VENV="$BUILD_ROOT/venv"
WHEELHOUSE="$BUILD_ROOT/wheelhouse"
SIDECAR_BUNDLE_IDENTIFIER="${RESEARCH_MEMORY_BUNDLE_IDENTIFIER:?Set RESEARCH_MEMORY_BUNDLE_IDENTIFIER}.core"
SIGNING_IDENTITY="${APPLE_SIGNING_IDENTITY:?Set APPLE_SIGNING_IDENTITY}"

test "$(uname -m)" = "arm64" || {
  echo "The release sidecar must be built on an Apple-silicon runner." >&2
  exit 1
}
test "$TARGET_TRIPLE" = "aarch64-apple-darwin" || {
  echo "Unsupported sidecar target: $TARGET_TRIPLE" >&2
  exit 1
}
PYTHON_ABI="$("$PYTHON_BIN" -c 'import sys; print(f"cp{sys.version_info.major}{sys.version_info.minor}")')"
test "$PYTHON_ABI" = "cp312" || {
  echo "The release sidecar requires CPython 3.12; found $PYTHON_ABI." >&2
  exit 1
}

cleanup() {
  rm -rf "$BUILD_ROOT"
}
trap cleanup EXIT INT TERM

PYTHON_BIN="$PYTHON_BIN" \
  RELEASE_WHEELHOUSE="$WHEELHOUSE" \
  "$PROJECT_DIR/scripts/install-release-python.sh" "$BUILD_VENV"
"$BUILD_VENV/bin/pyinstaller" \
  --noconfirm \
  --clean \
  --onefile \
  --name research-memory-core \
  --codesign-identity "$SIGNING_IDENTITY" \
  --osx-bundle-identifier "$SIDECAR_BUNDLE_IDENTIFIER" \
  --distpath "$BUILD_ROOT/dist" \
  --workpath "$BUILD_ROOT/work" \
  --specpath "$BUILD_ROOT" \
  --collect-all pypdfium2_raw \
  --collect-all fastembed \
  --collect-data research_memory \
  --hidden-import research_memory.main \
  "$PROJECT_DIR/src/research_memory/__main__.py"

mkdir -p "$OUTPUT_DIR"
cp "$BUILD_ROOT/dist/research-memory-core" \
  "$OUTPUT_DIR/research-memory-core-$TARGET_TRIPLE"
if [ "$SIGNING_IDENTITY" = "-" ]; then
  codesign --force --sign - "$OUTPUT_DIR/research-memory-core-$TARGET_TRIPLE"
else
  codesign --force --options runtime --timestamp \
    --sign "$SIGNING_IDENTITY" \
    "$OUTPUT_DIR/research-memory-core-$TARGET_TRIPLE"
fi
"$PYTHON_BIN" "$PROJECT_DIR/scripts/verify_macos_bundle.py" \
  "$OUTPUT_DIR/research-memory-core-$TARGET_TRIPLE" \
  --maximum-deployment-target 13.0
