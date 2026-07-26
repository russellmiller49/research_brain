from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from huggingface_hub import snapshot_download


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    project_dir = Path(__file__).resolve().parents[1]
    model_dir = project_dir / "desktop" / "src-tauri" / "resources" / "models"
    manifest = json.loads((model_dir / "model-manifest.json").read_text())
    snapshot = Path(
        snapshot_download(
            repo_id=manifest["distribution_repository"],
            revision=manifest["revision"],
            cache_dir=model_dir,
            local_files_only=False,
        )
    )
    onnx = snapshot / manifest["onnx_file"]
    actual = sha256(onnx)
    if actual != manifest["onnx_sha256"]:
        raise RuntimeError(
            f"Pinned ONNX model hash mismatch: {actual} != {manifest['onnx_sha256']}"
        )
    print(f"Verified {manifest['model']} at {manifest['revision']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
