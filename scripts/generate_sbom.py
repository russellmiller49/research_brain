from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

SHA256 = re.compile(r"^[0-9a-f]{64}$")


def bundled_python_license(distribution: importlib.metadata.Distribution) -> str:
    for relative in distribution.files or []:
        normalized = str(relative).lower()
        if ".dist-info/licenses/" not in normalized:
            continue
        try:
            notice = distribution.locate_file(relative).read_text(
                encoding="utf-8",
                errors="ignore",
            )
        except OSError:
            continue
        if notice.lstrip().startswith("MIT License"):
            return "MIT"
        if "Apache License" in notice[:500] and "Version 2.0" in notice[:500]:
            return "Apache-2.0"
    return "UNKNOWN"


def component(
    ecosystem: str,
    name: str,
    version: str,
    license_value: str,
    *,
    purl: str | None = None,
) -> dict[str, Any]:
    package_type = {
        "python": "pypi",
        "node": "npm",
        "rust": "cargo",
        "conda": "conda",
    }[ecosystem]
    value: dict[str, Any] = {
        "type": "library",
        "name": name,
        "version": version,
        "purl": purl or f"pkg:{package_type}/{name}@{version}",
    }
    if license_value and license_value != "UNKNOWN":
        value["licenses"] = [{"license": {"name": license_value}}]
    return value


def python_components() -> list[dict[str, Any]]:
    values = []
    for distribution in importlib.metadata.distributions():
        metadata = distribution.metadata
        name = metadata.get("Name") or distribution.name
        license_value = (
            metadata.get("License-Expression")
            or metadata.get("License")
            or bundled_python_license(distribution)
        )
        values.append(component("python", name, distribution.version, license_value.strip()))
    return values


def node_components(project_dir: Path) -> list[dict[str, Any]]:
    completed = subprocess.run(
        ["npm", "ls", "--all", "--json"],
        cwd=project_dir / "desktop",
        check=True,
        capture_output=True,
        text=True,
    )
    root = json.loads(completed.stdout)
    seen: set[tuple[str, str]] = set()
    values: list[dict[str, Any]] = []

    def visit(dependencies: dict[str, Any]) -> None:
        for name, value in dependencies.items():
            version = str(value.get("version") or "UNKNOWN")
            key = (name, version)
            if key not in seen:
                seen.add(key)
                values.append(component("node", name, version, "UNKNOWN"))
            visit(value.get("dependencies") or {})

    visit(root.get("dependencies") or {})
    return values


def rust_components(project_dir: Path) -> list[dict[str, Any]]:
    metadata_path = os.environ.get("RESEARCH_MEMORY_CARGO_METADATA")
    if metadata_path:
        metadata = json.loads(Path(metadata_path).read_text(encoding="utf-8"))
    else:
        cargo = os.environ.get("RESEARCH_MEMORY_CARGO", "cargo")
        completed = subprocess.run(
            [
                cargo,
                "metadata",
                "--locked",
                "--format-version",
                "1",
                "--filter-platform",
                "aarch64-apple-darwin",
            ],
            cwd=project_dir / "desktop" / "src-tauri",
            check=True,
            capture_output=True,
            text=True,
        )
        metadata = json.loads(completed.stdout)
    return [
        component(
            "rust",
            str(package["name"]),
            str(package["version"]),
            str(package.get("license") or "UNKNOWN"),
        )
        for package in metadata["packages"]
    ]


def tesseract_components(project_dir: Path) -> list[dict[str, Any]]:
    manifest_path = project_dir / "packaging" / "tesseract-components.json"
    lock_path = project_dir / "packaging" / "tesseract-osx-arm64.lock"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    locked = {
        line.strip()
        for line in lock_path.read_text(encoding="utf-8").splitlines()
        if line.startswith("https://")
    }
    declared: set[str] = set()
    values: list[dict[str, Any]] = []
    for package in manifest["packages"]:
        name = str(package["name"])
        version = str(package["version"])
        build = str(package["build"])
        url = str(package["url"])
        digest = str(package["sha256"])
        subdir = "noarch" if "/noarch/" in url else "osx-arm64"
        if not SHA256.fullmatch(digest):
            raise ValueError(f"Invalid Tesseract package hash for {name}")
        declared.add(f"{url}#{digest}")
        value = component(
            "conda",
            name,
            version,
            str(package["license"]),
            purl=(
                f"pkg:conda/{quote(name, safe='')}@{quote(version, safe='')}"
                f"?build={quote(build, safe='')}&channel=conda-forge&subdir={subdir}"
            ),
        )
        value["hashes"] = [{"alg": "SHA-256", "content": digest}]
        value["externalReferences"] = [{"type": "distribution", "url": url}]
        values.append(value)
    if declared != locked:
        raise ValueError("Tesseract SBOM manifest does not match the explicit package lock")
    return values


def model_components(project_dir: Path) -> list[dict[str, Any]]:
    manifest_path = (
        project_dir / "desktop" / "src-tauri" / "resources" / "models" / "model-manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    digest = str(manifest["onnx_sha256"])
    if not SHA256.fullmatch(digest):
        raise ValueError("Invalid offline-model hash")
    name = str(manifest["model"])
    revision = str(manifest["revision"])
    value = {
        "type": "machine-learning-model",
        "name": name,
        "version": revision,
        "purl": f"pkg:generic/{name}@{revision}",
        "licenses": [{"license": {"name": str(manifest["license"])}}],
        "hashes": [{"alg": "SHA-256", "content": digest}],
        "properties": [
            {
                "name": "research-memory:distribution-repository",
                "value": str(manifest["distribution_repository"]),
            },
            {
                "name": "research-memory:index-version",
                "value": str(manifest["index_version"]),
            },
        ],
    }
    return [value]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    project_dir = Path(__file__).resolve().parents[1]
    components = (
        python_components()
        + node_components(project_dir)
        + rust_components(project_dir)
        + tesseract_components(project_dir)
        + model_components(project_dir)
    )
    unique = {(value["purl"], value.get("version", "")): value for value in components}
    ordered = sorted(unique.values(), key=lambda value: value["purl"])
    serial = uuid.uuid5(uuid.NAMESPACE_URL, "\n".join(value["purl"] for value in ordered))
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{serial}",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "research-memory",
                "version": "0.2.0",
            },
            "properties": [
                {
                    "name": "research-memory:release-target",
                    "value": "aarch64-apple-darwin",
                }
            ],
        },
        "components": ordered,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(sbom, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(ordered)} components to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
