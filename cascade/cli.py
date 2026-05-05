"""Command-line entry point.

Resolves to the ``cascade`` console script declared in ``pyproject.toml``. Subcommands
are added in later phases (``cascade migrate``, ``cascade eval``, etc.).
"""

from __future__ import annotations

import sys

from cascade._version import __version__


def main(argv: list[str] | None = None) -> int:
    """Run the CLI.

    Returns the process exit code. ``0`` for success, non-zero for failure.
    """
    args = sys.argv[1:] if argv is None else argv

    if not args or args[0] in {"-h", "--help"}:
        print(_help_text())
        return 0

    if args[0] in {"-V", "--version"}:
        print(f"cascade {__version__}")
        return 0

    print(f"unknown command: {args[0]}", file=sys.stderr)
    print(_help_text(), file=sys.stderr)
    return 2


def _help_text() -> str:
    return (
        f"cascade {__version__}\n"
        "\n"
        "Usage: cascade [COMMAND]\n"
        "\n"
        "Options:\n"
        "  -V, --version    Print version and exit\n"
        "  -h, --help       Show this message and exit\n"
        "\n"
        "Commands are added in subsequent releases. Run the API directly with:\n"
        "  uvicorn cascade.api.main:app\n"
    )


if __name__ == "__main__":
    raise SystemExit(main())
