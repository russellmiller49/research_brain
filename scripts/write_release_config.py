from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required for a signed release")
    return value


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: write_release_config.py OUTPUT.json")
    identifier = required("RESEARCH_MEMORY_BUNDLE_IDENTIFIER")
    if identifier == "app.researchmemory.beta" or not re.fullmatch(
        r"[A-Za-z][A-Za-z0-9-]*(?:\.[A-Za-z0-9-]+){2,}",
        identifier,
    ):
        raise RuntimeError("Freeze a production reverse-DNS bundle identifier before signing")
    endpoint = required("RESEARCH_MEMORY_UPDATE_ENDPOINT")
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.netloc:
        raise RuntimeError("The signed update endpoint must use HTTPS")
    public_key = required("TAURI_UPDATER_PUBLIC_KEY")
    if len(public_key) < 40:
        raise RuntimeError("The Tauri updater public key is invalid")
    config = {
        "identifier": identifier,
        "bundle": {"createUpdaterArtifacts": True},
        "plugins": {
            "updater": {
                "endpoints": [endpoint],
                "pubkey": public_key,
                "dangerousInsecureTransportProtocol": False,
            }
        },
    }
    Path(sys.argv[1]).write_text(json.dumps(config), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
