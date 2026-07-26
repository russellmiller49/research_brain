#!/bin/sh
set -eu

PROJECT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3.12}"
RELEASE_REQUIREMENTS="$PROJECT_DIR/requirements-release.lock"
OUTPUT_VENV="${1:?Usage: install-release-python.sh OUTPUT_VENV}"
WHEELHOUSE="${RELEASE_WHEELHOUSE:-$OUTPUT_VENV-wheelhouse}"

test "$(uname -m)" = "arm64" || {
  echo "The release Python environment must be prepared on Apple silicon." >&2
  exit 1
}
PYTHON_ABI="$("$PYTHON_BIN" -c 'import sys; print(f"cp{sys.version_info.major}{sys.version_info.minor}")')"
test "$PYTHON_ABI" = "cp312" || {
  echo "The release Python environment requires CPython 3.12; found $PYTHON_ABI." >&2
  exit 1
}
test -f "$RELEASE_REQUIREMENTS" || {
  echo "Missing release dependency lock: $RELEASE_REQUIREMENTS" >&2
  exit 1
}
test ! -e "$OUTPUT_VENV" || {
  echo "Refusing to overwrite an existing release environment: $OUTPUT_VENV" >&2
  exit 1
}
test ! -e "$WHEELHOUSE" || {
  echo "Refusing to overwrite an existing release wheelhouse: $WHEELHOUSE" >&2
  exit 1
}

export MACOSX_DEPLOYMENT_TARGET=13.0
"$PYTHON_BIN" -m venv "$OUTPUT_VENV"
mkdir -p "$WHEELHOUSE"
"$OUTPUT_VENV/bin/pip" download \
  --disable-pip-version-check \
  --quiet \
  --require-hashes \
  --only-binary=:all: \
  --platform macosx_13_0_arm64 \
  --python-version 3.12 \
  --implementation cp \
  --abi "$PYTHON_ABI" \
  --dest "$WHEELHOUSE" \
  -r "$RELEASE_REQUIREMENTS"
"$OUTPUT_VENV/bin/pip" install \
  --disable-pip-version-check \
  --quiet \
  --no-index \
  --find-links "$WHEELHOUSE" \
  --require-hashes \
  -r "$RELEASE_REQUIREMENTS"
"$OUTPUT_VENV/bin/pip" install \
  --disable-pip-version-check \
  --quiet \
  --no-deps \
  --no-build-isolation \
  "$PROJECT_DIR"

"$PYTHON_BIN" "$PROJECT_DIR/scripts/verify_macos_bundle.py" \
  "$OUTPUT_VENV" --maximum-deployment-target 13.0
PYTHON_SHARED_LIBRARY="$(
  "$OUTPUT_VENV/bin/python" -c \
    'from PyInstaller.depend.bindepend import get_python_library_path; print(get_python_library_path())'
)"
"$PYTHON_BIN" "$PROJECT_DIR/scripts/verify_macos_bundle.py" \
  "$PYTHON_SHARED_LIBRARY" --maximum-deployment-target 13.0
printf 'Prepared release Python environment at %s\n' "$OUTPUT_VENV"
