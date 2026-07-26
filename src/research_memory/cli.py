from __future__ import annotations

import argparse
import os
import webbrowser
from pathlib import Path

import uvicorn


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="research-memory",
        description="Run or manage the local Research Memory application.",
    )
    parser.add_argument("--host", default=None, help="Bind address; defaults to 127.0.0.1")
    parser.add_argument("--port", type=int, default=None, help="Local port; defaults to 8765")
    parser.add_argument(
        "--data-dir", type=Path, default=None, help="Private application data directory"
    )
    parser.add_argument(
        "--desktop",
        action="store_true",
        help="Expose only the authenticated typed desktop API",
    )
    parser.add_argument(
        "--legacy-web",
        action="store_true",
        help="Enable the unsupported v0.1 browser prototype for development",
    )
    parser.add_argument(
        "--no-browser", action="store_true", help="Do not open the app in the default browser"
    )
    parser.add_argument("--reload", action="store_true", help="Development auto-reload")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.desktop and args.legacy_web:
        raise SystemExit("--desktop and --legacy-web cannot be used together")
    if not args.desktop and not args.legacy_web:
        raise SystemExit("Choose --desktop or the unsupported development-only --legacy-web")
    if args.desktop and args.reload:
        raise SystemExit("--reload is not permitted in desktop mode")
    if args.desktop and not os.getenv("RESEARCH_MEMORY_IPC_TOKEN"):
        raise SystemExit("Desktop mode requires an ephemeral IPC token")
    if args.data_dir:
        os.environ["RESEARCH_MEMORY_DATA_DIR"] = str(args.data_dir.expanduser().resolve())
    if args.desktop:
        os.environ["RESEARCH_MEMORY_ALLOW_LEGACY_WEB"] = "false"
    elif args.legacy_web:
        os.environ["RESEARCH_MEMORY_ALLOW_LEGACY_WEB"] = "true"
    host = args.host or os.getenv("RESEARCH_MEMORY_HOST", "127.0.0.1")
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("Research Memory may bind only to a loopback address")
    port = args.port or int(os.getenv("RESEARCH_MEMORY_PORT", "8765"))
    if args.legacy_web and not args.no_browser and host in {"127.0.0.1", "localhost"}:
        # Opening immediately is harmless; the browser retries while Uvicorn starts.
        webbrowser.open(f"http://127.0.0.1:{port}")
    uvicorn.run(
        "research_memory.main:app",
        host=host,
        port=port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
