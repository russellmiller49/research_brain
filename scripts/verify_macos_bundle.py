from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

MINIMUM_VERSION = re.compile(r"^\s*minos\s+(\d+(?:\.\d+)*)\s*$", re.MULTILINE)
LEGACY_MINIMUM_VERSION = re.compile(
    r"cmd LC_VERSION_MIN_MACOSX(?:(?!Load command).)*?"
    r"^\s*version\s+(\d+(?:\.\d+)*)\s*$",
    re.MULTILINE | re.DOTALL,
)
MACH_O_MAGICS = {
    b"\xfe\xed\xfa\xce",
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
    b"\xca\xfe\xba\xbf",
    b"\xbf\xba\xfe\xca",
}


def version_tuple(value: str) -> tuple[int, ...]:
    try:
        parts = tuple(int(part) for part in value.split("."))
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"Invalid macOS version: {value}") from error
    return parts + (0,) * max(0, 3 - len(parts))


def is_mach_o(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(4) in MACH_O_MAGICS
    except OSError:
        return False


def candidates(root: Path) -> list[Path]:
    if root.is_file():
        return [root] if is_mach_o(root) else []
    return [
        path
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink() and is_mach_o(path)
    ]


def command_output(command: list[str]) -> str:
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify that a macOS bundle contains arm64-compatible Mach-O files."
    )
    parser.add_argument("path", type=Path)
    parser.add_argument(
        "--maximum-deployment-target",
        default="13.0",
        help="Reject a Mach-O whose minimum macOS version is newer than this value.",
    )
    args = parser.parse_args()

    if not args.path.exists():
        parser.error(f"Path does not exist: {args.path}")

    maximum = version_tuple(args.maximum_deployment_target)
    failures: list[str] = []
    inspected = 0
    for path in candidates(args.path):
        description = command_output(["file", "-b", str(path)])
        if "Mach-O" not in description:
            continue
        inspected += 1
        if "arm64" not in description:
            failures.append(f"{path}: missing arm64 slice ({description.strip()})")
            continue

        build = command_output(["xcrun", "vtool", "-show-build", str(path)])
        minimums = MINIMUM_VERSION.findall(build)
        if not minimums:
            minimums = LEGACY_MINIMUM_VERSION.findall(build)
        if not minimums:
            failures.append(f"{path}: has no readable LC_BUILD_VERSION minimum")
            continue
        for minimum in minimums:
            if version_tuple(minimum) > maximum:
                failures.append(
                    f"{path}: minimum macOS {minimum} exceeds {args.maximum_deployment_target}"
                )

    if inspected == 0:
        failures.append(f"{args.path}: no Mach-O files found")
    if failures:
        for failure in failures:
            print(f"ERROR: {failure}")
        return 1
    print(
        f"Verified {inspected} arm64 Mach-O files with deployment targets no newer than "
        f"macOS {args.maximum_deployment_target}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
