#!/usr/bin/env python3
"""Loras - standalone Civitai metadata manager.

Usage:
    python main.py [--host 127.0.0.1] [--port 8199] [--data-dir PATH]

Then open http://127.0.0.1:8199 in a browser, paste Civitai links, optionally
add a Civitai API token, and the tool builds a metadata-only catalog (images,
trigger words, versions, files) without downloading any model files and
without any ComfyUI installation.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from aiohttp import web

from app import __version__
from app.server import create_app

BANNER = r"""
 _                        _____
| |                      / ____|
| |     __ _ _ __   __ _| (___   __ _ ___ _   _ _ __
| |    / _` | '_ \ / _` |\___ \ / _` / __| | | | '_ \
| |___| (_| | | | | (_| |____) | (_| \__ \ |_| | |_) |
|______\__,_|_| |_|\__,_|_____/ \__,_|___/\__,_| .__/
                                               | |
                                        v{version} |_|
"""


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Loras - standalone Civitai metadata manager")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8199, help="Port (default: 8199)")
    parser.add_argument(
        "--data-dir",
        default=os.environ.get("LORAS_DATA_DIR")
        or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"),
        help="Directory where metadata and settings are stored",
    )
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args(argv)


async def run(args) -> None:
    app = create_app(args.data_dir)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, args.host, args.port)
    await site.start()

    print(BANNER.format(version=__version__))
    print(f"  Metadata dir : {args.data_dir}")
    print(f"  Serving UI   : http://{args.host}:{args.port}")
    print("  No ComfyUI needed. No model files are downloaded - metadata only.")
    print("  Press Ctrl+C to stop.\n")

    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await runner.cleanup()
        print("Stopped.")


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
