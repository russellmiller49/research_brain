from __future__ import annotations

import contextlib
import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import struct
import tempfile
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from research_memory.config import Settings
from research_memory.db import Database
from research_memory.migrations import CURRENT_SCHEMA_VERSION
from research_memory.utils import resolve_external_destination, sha256_file

MAGIC = b"RMBACKUP1"
MAX_MANIFEST_BYTES = 16 * 1024 * 1024


class BackupError(RuntimeError):
    pass


class BackupService:
    """Creates streaming AES-GCM encrypted, portable library backups."""

    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings

    def create(self, destination: Path, passphrase: str) -> Path:
        if len(passphrase) < 12:
            raise BackupError("Backup passphrases must contain at least 12 characters")
        try:
            destination = resolve_external_destination(destination, self.settings.data_dir)
        except ValueError as exc:
            raise BackupError(str(exc)) from exc
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.settings.temp_dir) as temporary:
            staging = Path(temporary)
            database_copy = self.db.online_backup(staging / "research_memory.sqlite3")
            archive = staging / "library.zip"
            manifest = self._manifest(database_copy)
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as bundle:
                bundle.writestr("manifest.json", json.dumps(manifest, indent=2))
                bundle.write(database_copy, "research_memory.sqlite3")
                for item in manifest["objects"]:
                    source = self._object_path(str(item["sha256"]))
                    bundle.write(source, f"objects/{source.name}")
            self._encrypt(archive, destination, passphrase)
        return destination

    def verify(self, source: Path, passphrase: str) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(dir=self.settings.temp_dir) as temporary:
            archive = Path(temporary) / "library.zip"
            self._decrypt(source, archive, passphrase)
            with zipfile.ZipFile(archive) as bundle:
                manifest = self._load_manifest(bundle, archive.stat().st_size)
                database_digest = self._hash_member(bundle, "research_memory.sqlite3")
                if database_digest != manifest["database_sha256"]:
                    raise BackupError("Backup database is corrupt")
                for item in manifest["objects"]:
                    digest = str(item["sha256"])
                    member = f"objects/{digest}.pdf"
                    if self._hash_member(bundle, member) != digest:
                        raise BackupError(f"Backup object is corrupt: {member}")
                return manifest

    def restore(self, source: Path, passphrase: str) -> dict[str, int]:
        """Verify and restore a portable backup while retaining a rollback snapshot."""

        source = source.expanduser().resolve(strict=True)
        with tempfile.TemporaryDirectory(dir=self.settings.temp_dir) as temporary:
            staging = Path(temporary)
            archive = staging / "library.zip"
            self._decrypt(source, archive, passphrase)
            with zipfile.ZipFile(archive) as bundle:
                manifest = self._load_manifest(bundle, archive.stat().st_size)
                restored_database = staging / "research_memory.sqlite3"
                database_digest, _ = self._copy_member(
                    bundle,
                    "research_memory.sqlite3",
                    restored_database,
                )
                if database_digest != manifest["database_sha256"]:
                    raise BackupError("Backup database failed integrity verification")

                staged_objects: dict[str, Path] = {}
                for item in manifest["objects"]:
                    digest = self._validated_digest(item["sha256"])
                    member = f"objects/{digest}.pdf"
                    staged_object = staging / f"{digest}.pdf"
                    actual, size = self._copy_member(bundle, member, staged_object)
                    if actual != digest or size != int(item["size_bytes"]):
                        raise BackupError(f"Backup object is corrupt: {member}")
                    staged_objects[digest] = staged_object

            with contextlib.closing(sqlite3.connect(restored_database)) as restored:
                restored.row_factory = sqlite3.Row
                integrity = restored.execute("PRAGMA integrity_check").fetchone()
                if not integrity or integrity[0] != "ok":
                    raise BackupError("Backup database failed SQLite integrity checks")
                if restored.execute("PRAGMA foreign_key_check").fetchone():
                    raise BackupError("Backup database failed relational integrity checks")
                for row in restored.execute(
                    """
                    SELECT id, sha256, availability FROM document_files
                    WHERE object_path != ''
                    """
                ).fetchall():
                    digest = self._validated_digest(row["sha256"])
                    destination = self._object_path(digest)
                    if row["availability"] == "available" and digest not in staged_objects:
                        raise BackupError(f"Backup manifest is missing managed object {digest}")
                    restored.execute(
                        """
                        UPDATE document_files
                        SET object_path = ?, file_path = ?, availability = ?
                        WHERE id = ?
                        """,
                        (
                            str(destination),
                            str(destination),
                            "available"
                            if digest in staged_objects or destination.is_file()
                            else "missing",
                            row["id"],
                        ),
                    )
                restored.commit()
                restored_objects = self._publish_objects(staged_objects)
                counts = {
                    "documents": int(
                        restored.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
                    ),
                    "annotations": int(
                        restored.execute("SELECT COUNT(*) FROM annotations").fetchone()[0]
                    ),
                    "collections": int(
                        restored.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
                    ),
                    "objects_copied": restored_objects,
                }
                stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
                self.db.online_backup(self.settings.backups_dir / f"pre-restore-{stamp}.sqlite3")
                with contextlib.closing(self.db.connect()) as live:
                    restored.backup(live)
                    live.commit()
        self.db.initialize()
        self.db.execute("DELETE FROM index_state")
        self._remove_vector_indexes()
        return counts

    def _manifest(self, database_copy: Path) -> dict[str, Any]:
        with contextlib.closing(sqlite3.connect(database_copy)) as snapshot:
            snapshot.row_factory = sqlite3.Row
            rows = snapshot.execute(
                """
                SELECT DISTINCT sha256, object_path, size_bytes
                FROM document_files
                WHERE availability = 'available' AND object_path != ''
                """
            ).fetchall()
        objects: list[dict[str, object]] = []
        for row in rows:
            digest = self._validated_digest(row["sha256"])
            path = Path(row["object_path"])
            expected_path = self._object_path(digest)
            if path.expanduser().resolve() != expected_path.resolve():
                raise BackupError("A managed PDF points outside the object store")
            if not path.is_file():
                raise BackupError(f"Managed PDF is missing: {digest}")
            actual_size = path.stat().st_size
            if actual_size != int(row["size_bytes"]):
                raise BackupError(f"Managed PDF size does not match its record: {digest}")
            actual_digest = sha256_file(path)
            if actual_digest != digest:
                raise BackupError(f"Managed PDF failed integrity verification: {path.name}")
            objects.append(
                {
                    "sha256": actual_digest,
                    "size_bytes": actual_size,
                }
            )
        return {
            "format": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "schema_version": self.db.schema_version,
            "database_sha256": sha256_file(database_copy),
            "objects": objects,
        }

    def _load_manifest(
        self,
        bundle: zipfile.ZipFile,
        archive_size: int,
    ) -> dict[str, Any]:
        names = bundle.namelist()
        if len(names) != len(set(names)):
            raise BackupError("Backup contains duplicate archive members")
        try:
            manifest_info = bundle.getinfo("manifest.json")
            database_info = bundle.getinfo("research_memory.sqlite3")
        except KeyError as exc:
            raise BackupError("Backup manifest or database is missing") from exc
        if manifest_info.file_size > MAX_MANIFEST_BYTES:
            raise BackupError("Backup manifest is unreasonably large")
        if any(info.compress_type != zipfile.ZIP_STORED for info in bundle.infolist()):
            raise BackupError("Backup uses an unsupported compressed archive format")
        if sum(info.file_size for info in bundle.infolist()) > archive_size:
            raise BackupError("Backup archive expands beyond its encrypted payload")
        try:
            manifest = json.loads(bundle.read(manifest_info))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise BackupError("Backup manifest is invalid") from exc
        if not isinstance(manifest, dict) or manifest.get("format") != 1:
            raise BackupError("Unsupported backup manifest")
        database_sha256 = self._validated_digest(manifest.get("database_sha256"))
        raw_objects = manifest.get("objects")
        if not isinstance(raw_objects, list):
            raise BackupError("Backup object manifest is invalid")
        objects: list[dict[str, object]] = []
        expected_names = {"manifest.json", "research_memory.sqlite3"}
        seen: set[str] = set()
        max_object_bytes = self.settings.max_upload_mb * 1024 * 1024
        for value in raw_objects:
            if not isinstance(value, dict):
                raise BackupError("Backup object manifest is invalid")
            digest = self._validated_digest(value.get("sha256"))
            if digest in seen:
                raise BackupError("Backup object manifest contains duplicate hashes")
            seen.add(digest)
            try:
                size = int(value["size_bytes"])
            except (KeyError, TypeError, ValueError) as exc:
                raise BackupError("Backup object size is invalid") from exc
            if size < 0 or size > max_object_bytes:
                raise BackupError("Backup object exceeds the configured PDF size limit")
            member = f"objects/{digest}.pdf"
            try:
                info = bundle.getinfo(member)
            except KeyError as exc:
                raise BackupError(f"Backup object is missing: {member}") from exc
            if info.file_size != size:
                raise BackupError(f"Backup object size does not match its manifest: {member}")
            expected_names.add(member)
            objects.append({"sha256": digest, "size_bytes": size})
        if set(names) != expected_names:
            raise BackupError("Backup contains unexpected archive members")
        try:
            schema_version = int(manifest.get("schema_version") or 0)
        except (TypeError, ValueError) as exc:
            raise BackupError("Backup schema version is invalid") from exc
        if schema_version < 1 or schema_version > CURRENT_SCHEMA_VERSION:
            raise BackupError("Backup was created by an unsupported schema version")
        return {
            "format": 1,
            "created_at": str(manifest.get("created_at") or ""),
            "schema_version": schema_version,
            "database_sha256": database_sha256,
            "database_size_bytes": database_info.file_size,
            "objects": objects,
        }

    @staticmethod
    def _validated_digest(value: object) -> str:
        digest = str(value or "").lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise BackupError("Backup contains an invalid SHA-256 digest")
        return digest

    def _object_path(self, digest: str) -> Path:
        normalized = self._validated_digest(digest)
        return self.settings.objects_dir / normalized[:2] / normalized[2:4] / f"{normalized}.pdf"

    @staticmethod
    def _hash_member(bundle: zipfile.ZipFile, member: str) -> str:
        digest = hashlib.sha256()
        with bundle.open(member) as handle:
            while block := handle.read(1024 * 1024):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _copy_member(
        bundle: zipfile.ZipFile,
        member: str,
        destination: Path,
    ) -> tuple[str, int]:
        digest = hashlib.sha256()
        size = 0
        with bundle.open(member) as source, destination.open("xb") as target:
            while block := source.read(1024 * 1024):
                size += len(block)
                digest.update(block)
                target.write(block)
            target.flush()
            os.fsync(target.fileno())
        os.chmod(destination, 0o600)
        return digest.hexdigest(), size

    def _publish_objects(self, staged: dict[str, Path]) -> int:
        copied = 0
        for digest, source in staged.items():
            destination = self._object_path(digest)
            if destination.is_file() and sha256_file(destination) == digest:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.restore")
            try:
                with source.open("rb") as source_handle, temporary.open("xb") as target:
                    shutil.copyfileobj(source_handle, target, length=1024 * 1024)
                    target.flush()
                    os.fsync(target.fileno())
                if sha256_file(temporary) != digest:
                    raise BackupError(f"Staged backup object failed verification: {digest}")
                os.chmod(temporary, 0o600)
                os.replace(temporary, destination)
                copied += 1
            finally:
                temporary.unlink(missing_ok=True)
        return copied

    def _remove_vector_indexes(self) -> None:
        index_dir = self.settings.data_dir / "indexes"
        if not index_dir.is_dir():
            return
        for candidate in index_dir.iterdir():
            if candidate.is_file() and (
                candidate.suffix == ".usearch" or candidate.name.endswith(".usearch.tmp")
            ):
                candidate.unlink()

    @staticmethod
    def _derive_key(passphrase: str, salt: bytes) -> bytes:
        return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(passphrase.encode("utf-8"))

    def _encrypt(self, source: Path, destination: Path, passphrase: str) -> None:
        salt = secrets.token_bytes(16)
        nonce = secrets.token_bytes(12)
        key = self._derive_key(passphrase, salt)
        encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        try:
            with source.open("rb") as plain, temporary.open("wb") as encrypted:
                encrypted.write(MAGIC)
                encrypted.write(salt)
                encrypted.write(nonce)
                encrypted.write(struct.pack(">Q", source.stat().st_size))
                while block := plain.read(1024 * 1024):
                    encrypted.write(encryptor.update(block))
                encrypted.write(encryptor.finalize())
                encrypted.write(encryptor.tag)
                encrypted.flush()
                os.fsync(encrypted.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    def _decrypt(self, source: Path, destination: Path, passphrase: str) -> None:
        minimum_size = len(MAGIC) + 16 + 12 + 8 + 16
        if source.stat().st_size < minimum_size:
            raise BackupError("Backup file is truncated")
        with source.open("rb") as encrypted:
            if encrypted.read(len(MAGIC)) != MAGIC:
                raise BackupError("Not a Research Memory backup")
            salt = encrypted.read(16)
            nonce = encrypted.read(12)
            try:
                expected_size = struct.unpack(">Q", encrypted.read(8))[0]
            except struct.error as exc:
                raise BackupError("Backup header is truncated") from exc
            payload_size = source.stat().st_size - len(MAGIC) - 16 - 12 - 8 - 16
            encrypted.seek(-16, os.SEEK_END)
            tag = encrypted.read(16)
            encrypted.seek(len(MAGIC) + 16 + 12 + 8)
            decryptor = Cipher(
                algorithms.AES(self._derive_key(passphrase, salt)),
                modes.GCM(nonce, tag),
            ).decryptor()
            remaining = payload_size
            try:
                with destination.open("wb") as plain:
                    while remaining:
                        block = encrypted.read(min(1024 * 1024, remaining))
                        if not block:
                            raise BackupError("Backup payload is truncated")
                        remaining -= len(block)
                        plain.write(decryptor.update(block))
                    plain.write(decryptor.finalize())
            except ValueError as exc:
                destination.unlink(missing_ok=True)
                raise BackupError("Incorrect passphrase or corrupt backup") from exc
        if destination.stat().st_size != expected_size:
            destination.unlink(missing_ok=True)
            raise BackupError("Backup payload size does not match its header")
