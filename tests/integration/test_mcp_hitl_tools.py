"""Integration tests for the HITL MCP tools.

Exercises ``start_okr_draft`` and ``resume_okr_draft`` end-to-end through a
real :class:`FastMCP` server with a real :class:`AsyncSqliteSaver`
checkpointer and a :class:`FakeChatModel`. The shape mirrors the orchestrator
resumption tests but goes through the MCP wire surface, so a reviewer
verifying the integration looks at one place.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from mcp.server.fastmcp import FastMCP
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from cascade.agents.llm import FakeChatModel
from cascade.mcp.tools import AgentContext, register_tools


@pytest_asyncio.fixture
async def sessionmaker(engine: AsyncEngine) -> AsyncIterator[async_sessionmaker]:  # type: ignore[type-arg]
    """An async sessionmaker bound to the test engine."""
    yield async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def _proposal_json() -> str:
    return json.dumps(
        {
            "title": "Reach product-market fit in the SMB segment",
            "description": None,
            "key_results": [
                {
                    "description": "Lift weekly active accounts from 200 to 800",
                    "metric_type": "number",
                    "baseline_value": 200,
                    "target_value": 800,
                    "current_value": 200,
                    "unit": "accounts",
                    "weight": 1.0,
                }
            ],
        }
    )


def _critique_json(verdict: str, score: float = 0.85) -> str:
    return json.dumps(
        {
            "specificity": {"score": score, "reasoning": "ok"},
            "measurability": {"score": score, "reasoning": "ok"},
            "ambition": {"score": score, "reasoning": "ok"},
            "structure": {"score": score, "reasoning": "ok"},
            "vague_phrases": [],
            "verdict": verdict,
            "suggestions": [] if verdict == "pass" else ["Sharpen the segment definition"],
        }
    )


def _alignment_json(verdict: str) -> str:
    conflicts = (
        []
        if verdict == "aligned"
        else [
            {
                "peer_okr_id": None,
                "peer_title": "Conflicting peer OKR",
                "conflict_type": "resource",
                "description": "Both OKRs need the same engineering capacity",
                "severity": "blocking",
            }
        ]
    )
    return json.dumps(
        {
            "vertical_score": 0.9,
            "vertical_reasoning": "Direct contribution to parent",
            "conflicts": conflicts,
            "verdict": verdict,
            "suggestions": [],
        }
    )


async def _build_server_with_checkpointer(
    sessionmaker: async_sessionmaker,  # type: ignore[type-arg]
    saver: AsyncSqliteSaver,
    *,
    responses: list[str],
) -> tuple[FastMCP, FakeChatModel]:
    """Build an MCP server with a real checkpointer attached."""
    model = FakeChatModel(responses=responses)
    ctx = AgentContext(sessionmaker=sessionmaker, model=model, checkpointer=saver)
    mcp = FastMCP(name="cascade-test-hitl")
    register_tools(mcp, ctx)
    return mcp, model


async def _call(mcp: FastMCP, name: str, **arguments: Any) -> dict[str, Any]:
    """Call an MCP tool and return the parsed JSON content from the result."""
    result = await mcp.call_tool(name, arguments)
    # FastMCP returns a (content_list, structured_dict) pair in 1.x. Newer
    # versions return just content_list. Handle both.
    if isinstance(result, tuple):
        content_list, _structured = result
    else:
        content_list = result
    # First content block is text-form JSON of the return value.
    text = content_list[0].text  # type: ignore[union-attr]
    return json.loads(text)


# -- start_okr_draft happy path -----------------------------------------------


@pytest.mark.integration
async def test_start_okr_draft_completes_when_aligned(sessionmaker) -> None:  # type: ignore[no-untyped-def]
    """A drafting run that aligns on the first pass returns status='completed'."""
    async with AsyncSqliteSaver.from_conn_string(":memory:") as saver:
        mcp, _ = await _build_server_with_checkpointer(
            sessionmaker,
            saver,
            responses=[
                _proposal_json(),
                _critique_json("pass"),
                _alignment_json("aligned"),
            ],
        )

        result = await _call(mcp, "start_okr_draft", intent="Reach PMF in SMB")

        assert result["thread_id"]
        assert result["state"]["status"] == "completed"
        assert result["state"]["alignment_verdict"] == "aligned"
        assert result["state"]["proposal"]["title"].startswith("Reach product-market fit")


@pytest.mark.integration
async def test_start_okr_draft_pauses_on_alignment_block(sessionmaker) -> None:  # type: ignore[no-untyped-def]
    """A run that hits a blocking alignment conflict returns status='paused' with the conflict surfaced."""
    async with AsyncSqliteSaver.from_conn_string(":memory:") as saver:
        mcp, _ = await _build_server_with_checkpointer(
            sessionmaker,
            saver,
            responses=[
                _proposal_json(),
                _critique_json("pass"),
                _alignment_json("blocked"),
            ],
        )

        result = await _call(mcp, "start_okr_draft", intent="Reach PMF in SMB")

        assert result["state"]["status"] == "paused"
        assert result["state"]["alignment_verdict"] == "blocked"
        assert result["state"]["conflicts"], "expected at least one conflict in pause info"
        assert result["state"]["conflicts"][0]["severity"] == "blocking"
        assert result["thread_id"]


@pytest.mark.integration
async def test_start_okr_draft_without_checkpointer_raises(sessionmaker) -> None:  # type: ignore[no-untyped-def]
    """When the AgentContext has no checkpointer, the tool surfaces an instructive error."""
    model = FakeChatModel(responses=[])
    ctx = AgentContext(sessionmaker=sessionmaker, model=model, checkpointer=None)
    mcp = FastMCP(name="cascade-test-no-cp")
    register_tools(mcp, ctx)

    with pytest.raises(Exception) as exc_info:
        await mcp.call_tool("start_okr_draft", {"intent": "x"})
    # FastMCP wraps tool errors; the underlying RuntimeError text should make it through.
    assert "checkpointer" in str(exc_info.value).lower()


# -- resume_okr_draft ---------------------------------------------------------


@pytest.mark.integration
async def test_resume_with_commit_completes_run(sessionmaker) -> None:  # type: ignore[no-untyped-def]
    """Pause then commit — the resumed run completes with alignment forced to aligned."""
    async with AsyncSqliteSaver.from_conn_string(":memory:") as saver:
        mcp, _ = await _build_server_with_checkpointer(
            sessionmaker,
            saver,
            responses=[
                _proposal_json(),
                _critique_json("pass"),
                _alignment_json("blocked"),
            ],
        )

        start_result = await _call(mcp, "start_okr_draft", intent="x")
        assert start_result["state"]["status"] == "paused"
        thread_id = start_result["thread_id"]

        resume_result = await _call(
            mcp,
            "resume_okr_draft",
            thread_id=thread_id,
            decision="commit",
            notes="Approved despite resource conflict",
        )

        assert resume_result["thread_id"] == thread_id
        assert resume_result["state"]["status"] == "completed"
        assert resume_result["state"]["alignment_verdict"] == "aligned"
        # Conflicts should be demoted from blocking to info
        assert all(c["severity"] == "info" for c in resume_result["state"]["conflicts"])


@pytest.mark.integration
async def test_resume_with_revise_pauses_or_completes_after_redraft(sessionmaker) -> None:  # type: ignore[no-untyped-def]
    """Revise reruns the Drafter; if the redraft aligns, the run completes."""
    async with AsyncSqliteSaver.from_conn_string(":memory:") as saver:
        mcp, _ = await _build_server_with_checkpointer(
            sessionmaker,
            saver,
            responses=[
                # First pass: proposal, critique pass, alignment blocked -> pause
                _proposal_json(),
                _critique_json("pass"),
                _alignment_json("blocked"),
                # After revise: proposal, critique pass, alignment aligned -> complete
                _proposal_json(),
                _critique_json("pass"),
                _alignment_json("aligned"),
            ],
        )

        start_result = await _call(mcp, "start_okr_draft", intent="x")
        thread_id = start_result["thread_id"]

        resume_result = await _call(mcp, "resume_okr_draft", thread_id=thread_id, decision="revise")

        assert resume_result["state"]["status"] == "completed"
        assert resume_result["state"]["alignment_verdict"] == "aligned"
        # The revise rerun pushed iteration_count past the first pass
        assert resume_result["state"]["iteration_count"] >= 2


@pytest.mark.integration
async def test_resume_with_abandon_completes_with_blocked_audit(sessionmaker) -> None:  # type: ignore[no-untyped-def]
    """Abandon terminates with a 'blocked' verdict and an audit-trail conflict carrying the notes."""
    async with AsyncSqliteSaver.from_conn_string(":memory:") as saver:
        mcp, _ = await _build_server_with_checkpointer(
            sessionmaker,
            saver,
            responses=[
                _proposal_json(),
                _critique_json("pass"),
                _alignment_json("blocked"),
            ],
        )

        start_result = await _call(mcp, "start_okr_draft", intent="x")
        thread_id = start_result["thread_id"]

        resume_result = await _call(
            mcp,
            "resume_okr_draft",
            thread_id=thread_id,
            decision="abandon",
            notes="No longer relevant for Q2",
        )

        assert resume_result["state"]["status"] == "completed"
        assert resume_result["state"]["alignment_verdict"] == "blocked"
        # The audit conflict carries the notes
        descriptions = " ".join(c["description"] for c in resume_result["state"]["conflicts"])
        assert "No longer relevant for Q2" in descriptions


@pytest.mark.integration
async def test_resume_with_invalid_decision_raises(sessionmaker) -> None:  # type: ignore[no-untyped-def]
    """An unknown decision string is caught at the tool boundary, not deep in resume()."""
    async with AsyncSqliteSaver.from_conn_string(":memory:") as saver:
        mcp, _ = await _build_server_with_checkpointer(
            sessionmaker,
            saver,
            responses=[
                _proposal_json(),
                _critique_json("pass"),
                _alignment_json("blocked"),
            ],
        )

        start_result = await _call(mcp, "start_okr_draft", intent="x")
        thread_id = start_result["thread_id"]

        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool(
                "resume_okr_draft",
                {"thread_id": thread_id, "decision": "yolo"},
            )
        assert "commit" in str(exc_info.value).lower()


@pytest.mark.integration
async def test_resume_unknown_thread_id_raises(sessionmaker) -> None:  # type: ignore[no-untyped-def]
    """Resuming a thread that doesn't exist surfaces a clear error rather than a deep stack trace."""
    async with AsyncSqliteSaver.from_conn_string(":memory:") as saver:
        mcp, _ = await _build_server_with_checkpointer(
            sessionmaker,
            saver,
            responses=[],
        )

        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool(
                "resume_okr_draft",
                {"thread_id": "00000000-0000-0000-0000-000000000000", "decision": "commit"},
            )
        assert "no paused draft" in str(exc_info.value).lower()


@pytest.mark.integration
async def test_thread_ids_are_unique_across_starts(sessionmaker) -> None:  # type: ignore[no-untyped-def]
    """Two start_okr_draft calls must not share a thread_id — would corrupt the checkpointer."""
    async with AsyncSqliteSaver.from_conn_string(":memory:") as saver:
        mcp, _ = await _build_server_with_checkpointer(
            sessionmaker,
            saver,
            responses=[
                _proposal_json(),
                _critique_json("pass"),
                _alignment_json("aligned"),
                _proposal_json(),
                _critique_json("pass"),
                _alignment_json("aligned"),
            ],
        )

        first = await _call(mcp, "start_okr_draft", intent="x")
        second = await _call(mcp, "start_okr_draft", intent="y")
        assert first["thread_id"] != second["thread_id"]
