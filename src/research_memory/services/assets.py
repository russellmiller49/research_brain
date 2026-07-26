from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from research_memory.config import Settings
from research_memory.utils import sha256_file


class AssetIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StoredAsset:
    sha256: str
    path: Path
    size_bytes: int
    created: bool


class AssetStore:
    """Immutable, content-addressed storage for managed PDF bytes."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def object_path(self, digest: str) -> Path:
        normalized = digest.lower()
        if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
            raise ValueError("A SHA-256 hex digest is required")
        return self.settings.objects_dir / normalized[:2] / normalized[2:4] / f"{normalized}.pdf"

    def store(self, source: str | Path, digest: str | None = None) -> StoredAsset:
        source_path = Path(source).expanduser().resolve(strict=True)
        computed = digest or sha256_file(source_path)
        destination = self.object_path(computed)
        destination.parent.mkdir(parents=True, exist_ok=True)

        if destination.exists():
            try:
                self.verify(destination, computed)
            except AssetIntegrityError:
                # The caller supplied bytes that already match this content
                # address, so an atomic replacement repairs local corruption
                # without trusting or modifying the source file.
                pass
            else:
                return StoredAsset(computed, destination, destination.stat().st_size, False)

        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        try:
            with source_path.open("rb") as source_handle, temporary.open("xb") as target:
                shutil.copyfileobj(source_handle, target, length=1024 * 1024)
                target.flush()
                os.fsync(target.fileno())
            self.verify(temporary, computed)
            os.chmod(temporary, 0o600)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return StoredAsset(computed, destination, destination.stat().st_size, True)

    @staticmethod
    def verify(path: Path, expected_sha256: str) -> None:
        actual = sha256_file(path)
        if actual != expected_sha256:
            raise AssetIntegrityError(
                f"Managed asset hash mismatch: expected {expected_sha256}, got {actual}"
            )

    def resolve(self, object_path: str | Path, expected_sha256: str) -> Path:
        candidate = Path(object_path).expanduser().resolve()
        root = self.settings.objects_dir.resolve()
        if candidate != root and root not in candidate.parents:
            raise AssetIntegrityError("Managed asset path is outside the object store")
        if not candidate.is_file():
            raise FileNotFoundError(candidate)
        self.verify(candidate, expected_sha256)
        return candidate
