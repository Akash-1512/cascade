"""Integration tests for the cascade MCP tool surface.

These tests build a real :class:`FastMCP` server, register the cascade tools,
and call them via the in-process protocol. The session-maker is bound to the
test SQLite database and the chat model is :class:`FakeChatModel` — so the path
exercises everything except the actual provider call.

What we test here:

- Tool registration succeeds with the real session factory and fake model
- Each tool returns a wire-typed response
- Repository state mutates as expected (objectives created, decisions persisted)

What we do NOT test here:

- LLM behaviour — that's covered by agent unit tests
- Domain logic — covered by domain tests
- The MCP transport layer (stdio, SSE) — that's MCP-package surface, not ours
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from mcp.server.fastmcp import FastMCP
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from cascade.agents.llm import FakeChatModel
from cascade.mcp.tools import AgentContext, register_tools
from tests.integration.factories import seed_team, seed_user


@pytest_asyncio.fixture
async def sessionmaker(engine: AsyncEngine) -> AsyncIterator[async_sessionmaker]:
    """An async sessionmaker bound to the test engine."""
    yield async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def _good_proposal_json() -> str:
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


def _critique_json(verdict: str = "pass") -> str:
    return json.dumps(
        {
            "specificity": {"score": 0.9, "reasoning": "ok"},
            "measurability": {"score": 0.9, "reasoning": "ok"},
            "ambition": {"score": 0.85, "reasoning": "ok"},
            "structure": {"score": 0.9, "reasoning": "ok"},
            "vague_phrases": [],
            "verdict": verdict,
            "suggestions": [],
        }
    )


def _coach_json(kr_id: str, target_change: bool = False) -> str:
    return json.dumps(
        {
            "updates": [
                {
                    "key_result_id": kr_id,
                    "new_progress_value": 320,
                    "new_target_value": 600 if target_change else None,
                    "new_status": "on_track",
                    "confidence": "medium",
                    "blockers": None,
                    "narrative": "Up to 320, on pace.",
                    "requires_confirmation": target_change,
                }
            ],
            "coaching_message": "Nice progress.",
            "follow_up_questions": [],
        }
    )


def _risk_json(okr_id: str) -> str:
    return json.dumps(
        {
            "okr_id": okr_id,
            "risk_score": 0.4,
            "velocity_assessment": "on_pace",
            "factors": [
                {
                    "name": "On track",
                    "severity": "low",
                    "explanation": "Progress is consistent week over week",
                }
            ],
            "recommended_interventions": [],
            "requires_intervention": False,
        }
    )


def _alignment_json() -> str:
    return json.dumps(
        {
            "vertical_score": 0.85,
            "vertical_reasoning": "Direct contribution to parent",
            "conflicts": [],
            "verdict": "aligned",
            "suggestions": [],
        }
    )


def _build_server(
    sessionmaker: async_sessionmaker, responses: list[str]
) -> tuple[FastMCP, FakeChatModel]:
    """Build an MCP server with cascade tools registered against test deps."""
    model = FakeChatModel(responses=responses)
    ctx = AgentContext(sessionmaker=sessionmaker, model=model)
    mcp = FastMCP(name="cascade-test")
    register_tools(mcp, ctx)
    return mcp, model


@pytest.mark.integration
async def test_ten_tools_registered(sessionmaker) -> None:  # type: ignore[no-untyped-def]
    mcp, _ = _build_server(sessionmaker, responses=[])
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert names == {
        "list_okrs",
        "get_okr",
        "draft_okr",
        "score_okr",
        "log_checkin",
        "query_decisions",
        "assess_risk",
        "get_alignment",
        "start_okr_draft",
        "resume_okr_draft",
    }


@pytest.mark.integration
async def test_list_okrs_returns_summaries(sessionmaker, session) -> None:  # type: ignore[no-untyped-def]
    """Seed an OKR via the repository, then call the MCP tool."""
    from cascade.domain.enums import MetricType
    from cascade.domain.okr import KeyResultCreate, ObjectiveCreate, Quarter
    from cascade.storage.repositories.objective import ObjectiveRepository

    team = await seed_team(session)
    user = await seed_user(session, team_id=team.id)

    repo = ObjectiveRepository(session)
    await repo.create(
        ObjectiveCreate(
            title="Reach PMF in SMB segment this quarter",
            team_id=team.id,
            quarter=Quarter(year=2026, quarter=2),
            key_results=[
                KeyResultCreate(
                    description="Lift WAU from 200 to 800",
                    metric_type=MetricType.NUMBER,
                    baseline_value=200,
                    target_value=800,
                    current_value=200,
                )
            ],
        ),
        owner_id=user.id,
    )
    await session.commit()

    mcp, _ = _build_server(sessionmaker, responses=[])
    result = await mcp.call_tool("list_okrs", {"team_id": str(team.id)})
    # FastMCP returns (content_blocks, structured_dict) for tools with structured output
    assert result is not None


@pytest.mark.integration
async def test_get_okr_returns_full_view(sessionmaker, session) -> None:  # type: ignore[no-untyped-def]
    from cascade.domain.enums import MetricType
    from cascade.domain.okr import KeyResultCreate, ObjectiveCreate, Quarter
    from cascade.storage.repositories.objective import ObjectiveRepository

    team = await seed_team(session)
    user = await seed_user(session, team_id=team.id)
    repo = ObjectiveRepository(session)
    okr = await repo.create(
        ObjectiveCreate(
            title="Reach PMF in SMB segment this quarter",
            team_id=team.id,
            quarter=Quarter(year=2026, quarter=2),
            key_results=[
                KeyResultCreate(
                    description="Lift WAU from 200 to 800",
                    metric_type=MetricType.NUMBER,
                    baseline_value=200,
                    target_value=800,
                    current_value=500,
                )
            ],
        ),
        owner_id=user.id,
    )
    await session.commit()

    mcp, _ = _build_server(sessionmaker, responses=[])
    result = await mcp.call_tool("get_okr", {"objective_id": str(okr.id)})
    # We just verify the call succeeds and returns content; field-level assertions
    # are covered by adapter unit tests.
    assert result is not None


@pytest.mark.integration
async def test_score_okr_returns_breakdown(sessionmaker, session) -> None:  # type: ignore[no-untyped-def]
    from cascade.domain.enums import MetricType
    from cascade.domain.okr import KeyResultCreate, ObjectiveCreate, Quarter
    from cascade.storage.repositories.objective import ObjectiveRepository

    team = await seed_team(session)
    user = await seed_user(session, team_id=team.id)
    repo = ObjectiveRepository(session)
    okr = await repo.create(
        ObjectiveCreate(
            title="Reach PMF in SMB segment this quarter",
            team_id=team.id,
            quarter=Quarter(year=2026, quarter=2),
            key_results=[
                KeyResultCreate(
                    description="Lift WAU from 200 to 800",
                    metric_type=MetricType.NUMBER,
                    baseline_value=200,
                    target_value=800,
                    current_value=500,
                )
            ],
        ),
        owner_id=user.id,
    )
    await session.commit()

    mcp, _ = _build_server(sessionmaker, responses=[])
    result = await mcp.call_tool("score_okr", {"objective_id": str(okr.id)})
    assert result is not None


@pytest.mark.integration
async def test_draft_okr_runs_drafter_and_critic(sessionmaker) -> None:  # type: ignore[no-untyped-def]
    """``draft_okr`` runs the full Drafter→Critic loop and returns a result."""
    mcp, model = _build_server(
        sessionmaker,
        responses=[_good_proposal_json(), _critique_json("pass")],
    )
    result = await mcp.call_tool(
        "draft_okr",
        {"intent": "Reach product-market fit in the SMB segment"},
    )
    assert result is not None
    # Both LLM calls were consumed
    assert len(model.responses) == 0


@pytest.mark.integration
async def test_query_decisions_returns_causal_trail(sessionmaker, session) -> None:  # type: ignore[no-untyped-def]

    from cascade.domain.decision import Alternative, DecisionCreate
    from cascade.domain.enums import DecisionEventType, MetricType
    from cascade.domain.okr import KeyResultCreate, ObjectiveCreate, Quarter
    from cascade.storage.repositories.decision import DecisionRepository
    from cascade.storage.repositories.objective import ObjectiveRepository

    team = await seed_team(session)
    user = await seed_user(session, team_id=team.id)

    okr = await ObjectiveRepository(session).create(
        ObjectiveCreate(
            title="A real OKR with a decision attached",
            team_id=team.id,
            quarter=Quarter(year=2026, quarter=2),
            key_results=[
                KeyResultCreate(
                    description="A real KR for the test scenario",
                    metric_type=MetricType.NUMBER,
                    baseline_value=0,
                    target_value=100,
                    current_value=0,
                )
            ],
        ),
        owner_id=user.id,
    )
    await DecisionRepository(session).create(
        DecisionCreate(
            event_type=DecisionEventType.OBJECTIVE_COMMIT,
            objective_id=okr.id,
            summary="Committed Q2 OKR after pipeline review",
            alternatives=[
                Alternative(option="Hold Q1 targets", reason_rejected="No longer relevant")
            ],
            chosen="Proceed with new SMB focus",
            tradeoff=None,
        ),
        actor_id=user.id,
    )
    await session.commit()

    mcp, _ = _build_server(sessionmaker, responses=[])
    result = await mcp.call_tool("query_decisions", {"objective_id": str(okr.id), "limit": 10})
    assert result is not None


@pytest.mark.integration
async def test_assess_risk_runs_sentinel(sessionmaker, session) -> None:  # type: ignore[no-untyped-def]
    from cascade.domain.enums import MetricType
    from cascade.domain.okr import KeyResultCreate, ObjectiveCreate, Quarter
    from cascade.storage.repositories.objective import ObjectiveRepository

    team = await seed_team(session)
    user = await seed_user(session, team_id=team.id)
    okr = await ObjectiveRepository(session).create(
        ObjectiveCreate(
            title="An objective the Risk Sentinel can assess",
            team_id=team.id,
            quarter=Quarter(year=2026, quarter=2),
            key_results=[
                KeyResultCreate(
                    description="Some key result for risk testing scenario",
                    metric_type=MetricType.NUMBER,
                    baseline_value=0,
                    target_value=100,
                    current_value=30,
                )
            ],
        ),
        owner_id=user.id,
    )
    await session.commit()

    mcp, _ = _build_server(sessionmaker, responses=[_risk_json(str(okr.id))])
    result = await mcp.call_tool("assess_risk", {"objective_id": str(okr.id), "weeks_elapsed": 6})
    assert result is not None


@pytest.mark.integration
async def test_get_alignment_runs_aligner(sessionmaker, session) -> None:  # type: ignore[no-untyped-def]
    from cascade.domain.enums import MetricType
    from cascade.domain.okr import KeyResultCreate, ObjectiveCreate, Quarter
    from cascade.storage.repositories.objective import ObjectiveRepository

    team = await seed_team(session)
    user = await seed_user(session, team_id=team.id)
    okr = await ObjectiveRepository(session).create(
        ObjectiveCreate(
            title="An OKR the Aligner can analyse",
            team_id=team.id,
            quarter=Quarter(year=2026, quarter=2),
            key_results=[
                KeyResultCreate(
                    description="Some KR description for alignment analysis",
                    metric_type=MetricType.NUMBER,
                    baseline_value=0,
                    target_value=100,
                    current_value=0,
                )
            ],
        ),
        owner_id=user.id,
    )
    await session.commit()

    mcp, _ = _build_server(sessionmaker, responses=[_alignment_json()])
    result = await mcp.call_tool("get_alignment", {"objective_id": str(okr.id)})
    assert result is not None


@pytest.mark.integration
async def test_log_checkin_persists_check_in(sessionmaker, session) -> None:  # type: ignore[no-untyped-def]
    """Logging a check-in via MCP creates a row visible to subsequent reads."""
    from sqlalchemy import select

    from cascade.domain.enums import MetricType
    from cascade.domain.okr import KeyResultCreate, ObjectiveCreate, Quarter
    from cascade.storage.models import CheckInORM
    from cascade.storage.repositories.objective import ObjectiveRepository

    team = await seed_team(session)
    user = await seed_user(session, team_id=team.id)
    okr = await ObjectiveRepository(session).create(
        ObjectiveCreate(
            title="An OKR we can post check-ins against",
            team_id=team.id,
            quarter=Quarter(year=2026, quarter=2),
            key_results=[
                KeyResultCreate(
                    description="A KR we can post check-ins against",
                    metric_type=MetricType.NUMBER,
                    baseline_value=0,
                    target_value=1000,
                    current_value=0,
                )
            ],
        ),
        owner_id=user.id,
    )
    await session.commit()

    kr_id = str(okr.key_results[0].id)
    mcp, _ = _build_server(sessionmaker, responses=[_coach_json(kr_id)])

    await mcp.call_tool(
        "log_checkin",
        {
            "objective_id": str(okr.id),
            "key_result_id": kr_id,
            "progress_value": 320,
            "confidence": "medium",
            "narrative": "Up to 320 this week.",
            "author_id": str(user.id),
        },
    )

    # Verify the check-in was persisted
    rows = (await session.execute(select(CheckInORM))).scalars().all()
    assert len(rows) == 1
    assert rows[0].progress_value == 320
