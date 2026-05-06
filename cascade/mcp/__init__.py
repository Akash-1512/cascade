"""cascade MCP server — Model Context Protocol surface for the platform.

Exposes eight tools that MCP clients (Claude Desktop, Cursor, any MCP-compatible
agent) can call to draft, score, align, and check in on OKRs:

- ``list_okrs`` — compact list view filtered by team and quarter
- ``get_okr`` — full Objective view with KRs and derived scores
- ``draft_okr`` — Drafter + Critic loop returning a proposal and verdict
- ``score_okr`` — current score breakdown for an existing Objective
- ``log_checkin`` — Coach-mediated check-in with structured persistence
- ``query_decisions`` — causal trail for an Objective
- ``assess_risk`` — Risk Sentinel agent with intervention recommendations
- ``get_alignment`` — Aligner agent with vertical and horizontal checks

Run as a script::

    python -m cascade.mcp.server
"""

from cascade.mcp.tools import AgentContext, register_tools

__all__ = ["AgentContext", "register_tools"]
