"""cascade MCP server entry point.

Run with::

    python -m cascade.mcp.server                          # stdio transport
    python -m cascade.mcp.server --transport sse          # SSE on MCP_HOST:MCP_PORT
    python -m cascade.mcp.server --transport streamable-http  # streaming HTTP

Configure in Claude Desktop's ``claude_desktop_config.json`` like::

    {
        "mcpServers": {
            "cascade": {
                "command": "python",
                "args": ["-m", "cascade.mcp.server"],
                "env": {
                    "DATABASE_URL": "postgresql+psycopg://cascade:cascade@localhost:5432/cascade",
                    "GROQ_API_KEY": "...",
                },
            }
        }
    }

Run with stdio when launched by Claude Desktop or Cursor (the MCP client speaks
JSON-RPC over stdio). Run with SSE or streamable-http when serving multiple
clients across the network.
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Literal

from mcp.server.fastmcp import FastMCP

from cascade._version import __version__
from cascade.agents.llm import get_chat_model
from cascade.config import get_settings
from cascade.mcp.tools import AgentContext, register_tools
from cascade.storage.session import get_sessionmaker

logger = logging.getLogger(__name__)

Transport = Literal["stdio", "sse", "streamable-http"]


def build_server() -> FastMCP:
    """Construct the cascade MCP server with all eight tools registered."""
    settings = get_settings()

    mcp = FastMCP(
        name="cascade",
        instructions=(
            "cascade is an OKR governance platform. Use these tools to draft, "
            "score, align, and check in on Objectives and Key Results. The "
            "platform captures every state-changing event as a structured "
            "Decision so the reasoning behind targets and target changes is "
            "queryable months later via ``query_decisions``."
        ),
        host=settings.mcp_host,
        port=settings.mcp_port,
    )

    ctx = AgentContext(
        sessionmaker=get_sessionmaker(),
        model=get_chat_model(settings),
    )
    register_tools(mcp, ctx)
    return mcp


def main(argv: list[str] | None = None) -> int:
    """Launch the MCP server.

    Returns the process exit code. ``0`` on clean shutdown, ``1`` on startup
    failure, ``130`` on Ctrl+C.
    """
    parser = argparse.ArgumentParser(
        prog="cascade-mcp",
        description="cascade MCP server",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="MCP transport to use (default: stdio).",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"cascade-mcp {__version__}",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=get_settings().log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        # MCP stdio expects clean stdout — log to stderr so JSON-RPC isn't polluted.
        stream=sys.stderr,
    )

    try:
        server = build_server()
    except Exception:
        logger.exception("failed to build MCP server")
        return 1

    logger.info("cascade MCP server starting on transport=%s", args.transport)
    try:
        server.run(transport=args.transport)
    except KeyboardInterrupt:
        logger.info("cascade MCP server shutting down")
        return 130
    except Exception:
        logger.exception("cascade MCP server crashed")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
