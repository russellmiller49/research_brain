from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

DENIED = (
    "AGPL",
    "GPL-3.0-ONLY",
    "GPL-3.0-OR-LATER",
    "GNU AFFERO GENERAL PUBLIC LICENSE",
)
PACKAGE_EXCEPTIONS = {
    # PyInstaller's bootloader exception explicitly permits distributing the
    # executable produced from a non-GPL application.
    "pyinstaller",
    "pyinstaller-hooks-contrib",
}
NODE_LICENSE_OVERRIDES = {
    # Version 3.0.3 omits the license field from its published package
    # manifest, but the maintainer's matching source tag declares MIT.
    ("combine-errors", "3.0.3"): (
        "MIT",
        "https://github.com/MatthewMueller/combine-errors/tree/3.0.3#license",
    ),
}
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def bundled_python_license(distribution: importlib.metadata.Distribution) -> str:
    """Recover a standard license identifier from a wheel's bundled notice."""
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


def license_is_denied(name: str, expression: str) -> bool:
    normalized_name = name.strip().lower()
    normalized = expression.upper().replace(" ", "")
    if normalized_name in PACKAGE_EXCEPTIONS:
        return False
    return any(token.replace(" ", "") in normalized for token in DENIED)


def python_packages() -> list[dict[str, str]]:
    packages = []
    for distribution in importlib.metadata.distributions():
        metadata = distribution.metadata
        expression = metadata.get("License-Expression")
        classifiers = [
            value.removeprefix("License :: ").strip()
            for value in metadata.get_all("Classifier", [])
            if value.startswith("License :: ")
        ]
        declared = metadata.get("License") or ""
        first_line = next((line.strip() for line in declared.splitlines() if line.strip()), "")
        license_value = (
            expression
            or "; ".join(classifiers)
            or first_line[:200]
            or bundled_python_license(distribution)
        )
        packages.append(
            {
                "ecosystem": "python",
                "name": metadata.get("Name") or distribution.name,
                "version": distribution.version,
                "license": license_value.strip() or "UNKNOWN",
            }
        )
    return packages


def node_packages(project_dir: Path) -> list[dict[str, str]]:
    packages: list[dict[str, str]] = []
    node_modules = project_dir / "desktop" / "node_modules"
    manifests = list(node_modules.glob("*/package.json"))
    manifests.extend(node_modules.glob("@*/*/package.json"))
    for manifest in manifests:
        try:
            value = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        name = str(value.get("name") or manifest.parent.name)
        version = str(value.get("version") or "")
        override = NODE_LICENSE_OVERRIDES.get((name, version))
        license_value = value.get("license") or (override[0] if override else "UNKNOWN")
        if isinstance(license_value, dict):
            license_value = license_value.get("type") or "UNKNOWN"
        package = {
            "ecosystem": "node",
            "name": name,
            "version": version,
            "license": str(license_value),
        }
        if override and not value.get("license"):
            package["license_source"] = override[1]
        packages.append(package)
    return packages


def rust_packages(project_dir: Path) -> list[dict[str, str]]:
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
    metadata: dict[str, Any] = json.loads(completed.stdout)
    return [
        {
            "ecosystem": "rust",
            "name": str(package["name"]),
            "version": str(package["version"]),
            "license": str(package.get("license") or "UNKNOWN"),
        }
        for package in metadata["packages"]
    ]


def tesseract_packages(project_dir: Path) -> list[dict[str, str]]:
    manifest_path = project_dir / "packaging" / "tesseract-components.json"
    lock_path = project_dir / "packaging" / "tesseract-osx-arm64.lock"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    values: list[dict[str, str]] = []
    locked = {
        line.strip()
        for line in lock_path.read_text(encoding="utf-8").splitlines()
        if line.startswith("https://")
    }
    declared: set[str] = set()
    for package in manifest["packages"]:
        url = str(package["url"])
        digest = str(package["sha256"])
        if not SHA256.fullmatch(digest):
            raise ValueError(f"Invalid Tesseract package hash for {package['name']}")
        declared.add(f"{url}#{digest}")
        values.append(
            {
                "ecosystem": "conda",
                "name": str(package["name"]),
                "version": str(package["version"]),
                "license": str(package["license"]),
                "build": str(package["build"]),
                "sha256": digest,
                "source": url,
            }
        )
    if declared != locked:
        raise ValueError("Tesseract license manifest does not match the explicit package lock")
    return values


def model_packages(project_dir: Path) -> list[dict[str, str]]:
    manifest_path = (
        project_dir / "desktop" / "src-tauri" / "resources" / "models" / "model-manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    digest = str(manifest["onnx_sha256"])
    if not SHA256.fullmatch(digest):
        raise ValueError("Invalid offline-model hash")
    return [
        {
            "ecosystem": "model",
            "name": str(manifest["model"]),
            "version": str(manifest["revision"]),
            "license": str(manifest["license"]),
            "sha256": digest,
            "source": str(manifest["distribution_repository"]),
        }
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    project_dir = Path(__file__).resolve().parents[1]
    packages = (
        python_packages()
        + node_packages(project_dir)
        + rust_packages(project_dir)
        + tesseract_packages(project_dir)
        + model_packages(project_dir)
    )
    packages.sort(key=lambda value: (value["ecosystem"], value["name"].lower()))
    denied = [
        package for package in packages if license_is_denied(package["name"], package["license"])
    ]
    unknown = [package for package in packages if package["license"] == "UNKNOWN"]
    report = {
        "policy": {
            "denied": list(DENIED),
            "exceptions": sorted(PACKAGE_EXCEPTIONS),
            "rust_target": "aarch64-apple-darwin",
        },
        "package_count": len(packages),
        "denied_packages": denied,
        "unknown_packages": unknown,
        "packages": packages,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if denied:
        for package in denied:
            print(
                f"Denied license: {package['ecosystem']}:{package['name']} "
                f"{package['version']} ({package['license']})"
            )
    if unknown:
        for package in unknown:
            print(f"Unknown license: {package['ecosystem']}:{package['name']} {package['version']}")
    if denied or unknown:
        return 1
    print(f"License policy passed for {len(packages)} packages.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
