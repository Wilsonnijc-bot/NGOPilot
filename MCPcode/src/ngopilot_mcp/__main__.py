"""NGOPilotMCP command-line entry point."""

from __future__ import annotations

import argparse
import json
from typing import Sequence

from .bootstrap import bootstrap
from .config import load_settings
from .host.registry import load_tools
from .host.server import create_server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ngopilot-mcp")
    subparsers = parser.add_subparsers(dest="command")

    serve = subparsers.add_parser("serve", help="Run the MCP server.")
    serve.add_argument(
        "--transport",
        choices=("stdio",),
        default="stdio",
    )

    bootstrap_parser = subparsers.add_parser(
        "bootstrap",
        help="Create and verify the managed CareFlow and Roster environments.",
    )
    bootstrap_parser.add_argument("--upgrade", action="store_true")

    subparsers.add_parser("list-tools", help="Print registered tool metadata.")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "serve"
    if command == "bootstrap":
        result = bootstrap(load_settings(), upgrade=args.upgrade)
        print(
            json.dumps(
                {
                    "careflow_python": str(result.careflow_python),
                    "roster_python": str(result.roster_python),
                    "careflow_source": str(result.careflow_source),
                    "roster_source": str(result.roster_source),
                },
                indent=2,
            )
        )
        return
    if command == "list-tools":
        print(
            json.dumps(
                [
                    {
                        "name": item.manifest.name,
                        "description": item.manifest.description,
                        "operations": list(item.manifest.operations),
                        "worker": item.manifest.worker,
                    }
                    for item in load_tools()
                ],
                indent=2,
            )
        )
        return
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
