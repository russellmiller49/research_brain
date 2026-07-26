#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -x .venv-beta/bin/python ]]; then
  make bootstrap
fi
cd desktop
npm run tauri dev
