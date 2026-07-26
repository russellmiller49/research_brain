#!/bin/sh
set -eu

VERSION="1.0.5"
ARCHIVE_SHA256="13384ebe7ca841ec392ac49dc5e50b1470190466623fa0e5cd30f1c634858530"
SOURCE_URL="https://github.com/auriamg/macdylibbundler/archive/refs/tags/$VERSION.tar.gz"
OUTPUT_DIR="${1:?Usage: install-dylibbundler.sh OUTPUT_DIR}"
BUILD_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/research-memory-dylibbundler.XXXXXX")"
ARCHIVE="$BUILD_ROOT/source.tar.gz"

test "$(uname -m)" = "arm64" || {
  echo "The release dylibbundler must be built on Apple silicon." >&2
  exit 1
}
test ! -e "$OUTPUT_DIR" || {
  echo "Refusing to overwrite an existing dylibbundler directory: $OUTPUT_DIR" >&2
  exit 1
}

cleanup() {
  rm -rf "$BUILD_ROOT"
}
trap cleanup EXIT INT TERM

curl --fail --location --silent --show-error "$SOURCE_URL" --output "$ARCHIVE"
ACTUAL_SHA256="$(shasum -a 256 "$ARCHIVE" | awk '{print $1}')"
test "$ACTUAL_SHA256" = "$ARCHIVE_SHA256" || {
  echo "dylibbundler source hash mismatch." >&2
  exit 1
}
tar -xzf "$ARCHIVE" -C "$BUILD_ROOT"
make -C "$BUILD_ROOT/macdylibbundler-$VERSION"
mkdir -p "$OUTPUT_DIR"
cp "$BUILD_ROOT/macdylibbundler-$VERSION/dylibbundler" "$OUTPUT_DIR/dylibbundler"
chmod 755 "$OUTPUT_DIR/dylibbundler"
file "$OUTPUT_DIR/dylibbundler" | grep -F "arm64"
printf 'Prepared dylibbundler %s at %s\n' "$VERSION" "$OUTPUT_DIR/dylibbundler"
