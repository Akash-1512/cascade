"""MCP tool implementations for cascade.

Eight tools, one entry point. The :func:`register_tools` function attaches every
tool to a FastMCP server given an :class:`AgentContext` that holds the
dependencies — repositories, agent functions, the chat model. This is the only
place agent and storage code touches MCP code.

A pattern note on testability: each tool body is a thin async wrapper around
existing functions in ``cascade.agents`` and ``cascade.storage.repositories``.
The interesting behaviour lives in those functions and is tested independently.
What we test in this module is that the *adapter* path is intact — that the
right repository is called with the right arguments, and the right wire type
comes back.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from cascade.agents.aligner import check_alignment
from cascade.agents.checkin_coach import run_checkin
from cascade.agents.critic import critique_proposal
from cascade.agents.drafter import draft_objective
from cascade.agents.risk_sentinel import assess_risk
from cascade.domain.enums import CheckInConfidence, KeyResultStatus
from cascade.domain.okr import Quarter
from cascade.mcp.adapters import (
    to_alignment_view,
    to_decision_view,
    to_drafted_objective,
    to_objective_summary,
    to_objective_view,
    to_risk_view,
)
from cascade.mcp.schemas import (
    AlignmentResultView,
    CheckInResult,
    DecisionView,
    DraftResult,
    ObjectiveSummary,
    ObjectiveView,
    RiskAssessmentView,
    ScoreResult,
)
from cascade.storage.repositories import NotFoundError
from cascade.storage.repositories.decision import DecisionRepository
from cascade.storage.repositories.objective import ObjectiveRepository

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from mcp.server.fastmcp import FastMCP
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AgentContext:
    """Dependencies the MCP tools need to do their work.

    Constructed once at server startup and shared across requests. Sessions are
    created per-request via the :func:`session` context manager so transactions
    are scoped to a single tool call.
    """

    sessionmaker: async_sessionmaker[AsyncSession]
    model: BaseChatModel

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Yield a session bound to a single tool call's transaction."""
        async with self.sessionmaker() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise


def register_tools(mcp: FastMCP, ctx: AgentContext) -> None:
    """Attach the cascade MCP tools to ``mcp``.

    Args:
        mcp: A :class:`FastMCP` server instance.
        ctx: The :class:`AgentContext` carrying dependencies.
    """

    # --- list_okrs ----------------------------------------------------------

    @mcp.tool(
        name="list_okrs",
        description=(
            "List Objectives for a team, optionally filtered by quarter. Returns "
            "compact summaries — call ``get_okr`` for full details."
        ),
    )
    async def list_okrs(team_id: str, quarter: str | None = None) -> list[ObjectiveSummary]:
        team_uuid = UUID(team_id)
        quarter_obj = Quarter.from_string(quarter) if quarter else None
        async with ctx.session() as session:
            repo = ObjectiveRepository(session)
            objectives = await repo.list_for_team(team_uuid, quarter=quarter_obj)
        return [to_objective_summary(o) for o in objectives]

    # --- get_okr ------------------------------------------------------------

    @mcp.tool(
        name="get_okr",
        description=(
            "Fetch a single Objective with all of its Key Results. Returns the "
            "full ObjectiveView including derived per-KR scores."
        ),
    )
    async def get_okr(objective_id: str) -> ObjectiveView:
        async with ctx.session() as session:
            repo = ObjectiveRepository(session)
            objective = await repo.get(UUID(objective_id))
        return to_objective_view(objective)

    # --- draft_okr ----------------------------------------------------------

    @mcp.tool(
        name="draft_okr",
        description=(
            "Draft a new Objective from natural-language intent. Runs the "
            "Drafter and Critic agents and returns the proposal plus the "
            "Critic's verdict. The proposal is NOT yet persisted — use "
            "``commit_okr`` if the verdict is acceptable."
        ),
    )
    async def draft_okr(intent: str) -> DraftResult:
        proposal = await draft_objective(intent=intent, model=ctx.model)
        critique = await critique_proposal(proposal=proposal, model=ctx.model)
        return DraftResult(
            proposal=to_drafted_objective(proposal),
            critique_verdict=critique.verdict,
            critique_overall_score=critique.overall_score,
            critique_suggestions=list(critique.suggestions),
            iterations=1,
        )

    # --- score_okr ----------------------------------------------------------

    @mcp.tool(
        name="score_okr",
        description=(
            "Compute the current score for an existing Objective and break it "
            "down by Key Result. Scores are derived from baseline, current, "
            "and target values — they are never stored independently."
        ),
    )
    async def score_okr(objective_id: str) -> ScoreResult:
        async with ctx.session() as session:
            repo = ObjectiveRepository(session)
            objective = await repo.get(UUID(objective_id))

        kr_breakdown = [
            {
                "id": str(kr.id),
                "description": kr.description,
                "score": kr.score,
            }
            for kr in objective.key_results
        ]
        return ScoreResult(
            objective_id=str(objective.id),
            overall_score=objective.score,
            key_result_scores=kr_breakdown,
        )

    # --- log_checkin --------------------------------------------------------

    @mcp.tool(
        name="log_checkin",
        description=(
            "Log a check-in against a Key Result. Runs the Coach agent to turn "
            "the free-text narrative into structured progress, captures any "
            "decisions raised in the conversation, and returns a coaching "
            "response. Target changes always require human confirmation."
        ),
    )
    async def log_checkin(
        objective_id: str,
        key_result_id: str,
        progress_value: float,
        confidence: str,
        narrative: str,
        author_id: str,
        blockers: str | None = None,
    ) -> CheckInResult:
        # Validate enum input early — surface a clear error to the MCP client
        # instead of letting Pydantic validation deep in the call stack do it.
        try:
            confidence_enum = CheckInConfidence(confidence)
        except ValueError as exc:
            raise ValueError(
                f"confidence must be one of: high, medium, low. Got {confidence!r}"
            ) from exc

        async with ctx.session() as session:
            repo = ObjectiveRepository(session)
            objective = await repo.get(UUID(objective_id))

            target_kr = next(
                (kr for kr in objective.key_results if str(kr.id) == key_result_id),
                None,
            )
            if target_kr is None:
                raise NotFoundError("key_result", key_result_id)

            coach_response = await run_checkin(
                objective=objective,
                user_message=narrative,
                model=ctx.model,
            )

            # Resolve the new status — defer to the Coach if it suggested one,
            # otherwise compute from confidence and progress.
            new_status = (
                target_kr.status
                if not coach_response.updates
                else _resolve_status(coach_response.updates[0].new_status, confidence_enum)
            )

            # Persist the check-in via the domain payload type.
            from cascade.storage.models import CheckInORM

            check_in = CheckInORM(
                key_result_id=UUID(key_result_id),
                progress_value=progress_value,
                confidence=confidence_enum,
                status=new_status,
                blockers=blockers,
                narrative=narrative,
                author_id=UUID(author_id),
            )
            session.add(check_in)
            await session.flush()
            await session.refresh(check_in)
            check_in_id = str(check_in.id)

        return CheckInResult(
            check_in_id=check_in_id,
            key_result_id=key_result_id,
            new_progress_value=progress_value,
            new_status=new_status.value,  # type: ignore[arg-type]
            coaching_message=coach_response.coaching_message,
        )

    # --- query_decisions ----------------------------------------------------

    @mcp.tool(
        name="query_decisions",
        description=(
            "Retrieve the decision history for an Objective. Returns the causal "
            "trail — every state-changing event with the alternatives "
            "considered, the chosen option, and the tradeoff accepted. This is "
            "the 'why we did what we did' record."
        ),
    )
    async def query_decisions(objective_id: str, limit: int = 50) -> list[DecisionView]:
        async with ctx.session() as session:
            repo = DecisionRepository(session)
            decisions = await repo.list_for_objective(UUID(objective_id), limit=limit)
        return [to_decision_view(d) for d in decisions]

    # --- assess_risk --------------------------------------------------------

    @mcp.tool(
        name="assess_risk",
        description=(
            "Run the Risk Sentinel agent against an Objective. Returns a risk "
            "score (probability of missing the target by quarter end), a "
            "velocity assessment, contributing factors, and recommended "
            "interventions. Stalled velocity always triggers intervention "
            "regardless of score."
        ),
    )
    async def assess_risk_tool(objective_id: str, weeks_elapsed: int = 6) -> RiskAssessmentView:
        async with ctx.session() as session:
            repo = ObjectiveRepository(session)
            objective = await repo.get(UUID(objective_id))

        # In a fuller implementation we'd fetch the check-in history here. For
        # the MCP surface we let the agent reason from the OKR's current state
        # alone — Coach already captures check-in trajectory in its narrative.
        risk = await assess_risk(
            okr=objective,
            check_ins=[],
            weeks_elapsed=weeks_elapsed,
            model=ctx.model,
        )
        return to_risk_view(risk)

    # --- get_alignment ------------------------------------------------------

    @mcp.tool(
        name="get_alignment",
        description=(
            "Run the Aligner against an Objective: vertical alignment to the "
            "parent OKR and horizontal conflicts with peer OKRs at the same "
            "team and quarter. Verdict is 'aligned', 'needs_review', or "
            "'blocked'."
        ),
    )
    async def get_alignment(objective_id: str) -> AlignmentResultView:
        oid = UUID(objective_id)
        async with ctx.session() as session:
            repo = ObjectiveRepository(session)
            objective = await repo.get(oid)

            parent = None
            if objective.parent_objective_id is not None:
                parent = await repo.get(objective.parent_objective_id)

            peers = [
                p
                for p in await repo.list_for_team(objective.team_id, quarter=objective.quarter)
                if p.id != objective.id
            ]

        # Re-render proposal from the existing Objective so the Aligner sees
        # the same shape it was designed for.
        from cascade.agents.contracts import ProposedKeyResult, ProposedObjective

        proposal = ProposedObjective(
            title=objective.title,
            description=objective.description,
            key_results=[
                ProposedKeyResult(
                    description=kr.description,
                    metric_type=kr.metric_type,
                    baseline_value=kr.baseline_value,
                    target_value=kr.target_value,
                    current_value=kr.current_value,
                    unit=kr.unit,
                    weight=kr.weight,
                )
                for kr in objective.key_results
            ],
        )

        alignment = await check_alignment(
            proposal=proposal,
            parent_objective=parent,
            peer_objectives=peers,
            model=ctx.model,
        )
        return to_alignment_view(alignment, objective_id=str(objective.id))


def _resolve_status(
    suggested: str | None,
    confidence: CheckInConfidence,
) -> KeyResultStatus:
    """Pick a KR status from the Coach's suggestion or fall back to confidence."""
    if suggested is not None:
        return KeyResultStatus(suggested)
    if confidence == CheckInConfidence.HIGH:
        return KeyResultStatus.ON_TRACK
    if confidence == CheckInConfidence.MEDIUM:
        return KeyResultStatus.AT_RISK
    return KeyResultStatus.OFF_TRACK


__all__ = ["AgentContext", "register_tools"]
