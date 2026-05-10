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
                    "CASCADE_MCP_CHECKPOINTER_PATH": "/var/lib/cascade/checkpoint.db",
                },
            }
        }
    }

Run with stdio when launched by Claude Desktop or Cursor (the MCP client speaks
JSON-RPC over stdio). Run with SSE or streamable-http when serving multiple
clients across the network.

A LangGraph checkpointer backs the HITL drafting tools (``start_okr_draft`` /
``resume_okr_draft``). It opens before tool registration and closes on
shutdown. ``CASCADE_MCP_CHECKPOINTER_PATH`` defaults to ``:memory:`` — paused
drafts don't survive a restart in that mode. For production, set a file path.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import TYPE_CHECKING, Literal

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from mcp.server.fastmcp import FastMCP

from cascade._version import __version__
from cascade.agents.llm import get_chat_model
from cascade.config import get_settings
from cascade.mcp.tools import AgentContext, register_tools
from cascade.storage.session import get_sessionmaker

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver

logger = logging.getLogger(__name__)

Transport = Literal["stdio", "sse", "streamable-http"]


async def _open_checkpointer(path: str) -> tuple[BaseCheckpointSaver, aiosqlite.Connection]:
    """Open an :class:`AsyncSqliteSaver` and its underlying connection.

    Returns the (saver, conn) pair. The connection must be closed on shutdown
    or the SQLite WAL files leak. Setup is run once on first open so the
    checkpoint tables exist.
    """
    conn = await aiosqlite.connect(path)
    saver = AsyncSqliteSaver(conn)
    await saver.setup()
    return saver, conn


def build_server() -> tuple[FastMCP, BaseCheckpointSaver | None, aiosqlite.Connection | None]:
    """Construct the cascade MCP server with all tools registered.

    Returns ``(mcp, checkpointer_saver, checkpointer_conn)``. The caller is
    responsible for closing the connection on shutdown — this function
    can't open one as an async context because :meth:`FastMCP.run` is the
    long-lived blocking call after this returns.

    Returns ``(mcp, None, None)`` for the saver pair when checkpointer
    construction fails (e.g. no aiosqlite at runtime). The HITL tools will
    raise an instructive error on first invocation; the rest of the server
    keeps working.
    """
    settings = get_settings()

    mcp = FastMCP(
        name="cascade",
        instructions=(
            "cascade is an OKR governance platform. Use these tools to draft, "
            "score, align, and check in on Objectives and Key Results. The "
            "platform captures every state-changing event as a structured "
            "Decision so the reasoning behind targets and target changes is "
            "queryable months later via ``query_decisions``. The "
            "``start_okr_draft`` and ``resume_okr_draft`` tools support "
            "human-in-the-loop pause-and-resume — drafts that hit alignment "
            "conflicts pause for a human decision (commit / revise / abandon) "
            "rather than producing a low-quality result silently."
        ),
        host=settings.mcp_host,
        port=settings.mcp_port,
    )

    # Open the checkpointer synchronously through asyncio.run — the function
    # itself is async because aiosqlite is async. We deliberately don't keep
    # the event loop running here; the FastMCP run() call below will create
    # its own loop and the connection survives because aiosqlite connections
    # can be used from any loop on the same thread.
    saver: BaseCheckpointSaver | None
    conn: aiosqlite.Connection | None
    try:
        saver, conn = asyncio.run(_open_checkpointer(settings.mcp_checkpointer_path))
    except Exception:
        logger.exception(
            "Failed to open MCP checkpointer at %s — HITL tools will be unavailable",
            settings.mcp_checkpointer_path,
        )
        saver, conn = None, None

    ctx = AgentContext(
        sessionmaker=get_sessionmaker(),
        model=get_chat_model(settings),
        checkpointer=saver,
    )
    register_tools(mcp, ctx)
    return mcp, saver, conn


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
        server, _saver, conn = build_server()
    except Exception:
        logger.exception("failed to build MCP server")
        return 1

    from cascade.observability import observability_state

    logger.info(observability_state().summary_line())
    logger.info("cascade MCP server starting on transport=%s", args.transport)
    exit_code = 0
    try:
        server.run(transport=args.transport)
    except KeyboardInterrupt:
        logger.info("cascade MCP server shutting down")
        exit_code = 130
    except Exception:
        logger.exception("cascade MCP server crashed")
        exit_code = 1
    finally:
        if conn is not None:
            try:
                asyncio.run(conn.close())
            except Exception:
                logger.exception("failed to close checkpointer connection")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
