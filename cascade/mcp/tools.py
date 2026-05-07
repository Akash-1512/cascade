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
from uuid import UUID, uuid4

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
    to_hitl_conflicts,
    to_objective_summary,
    to_objective_view,
    to_risk_view,
)
from cascade.mcp.schemas import (
    AlignmentResultView,
    CheckInResult,
    DecisionView,
    DraftResult,
    HitlCompleteInfo,
    HitlPauseInfo,
    ObjectiveSummary,
    ObjectiveView,
    ResumeOkrDraftResult,
    RiskAssessmentView,
    ScoreResult,
    StartOkrDraftResult,
)
from cascade.orchestrator.graph import build_graph
from cascade.orchestrator.resumption import resume as resume_graph
from cascade.orchestrator.state import OKRState
from cascade.storage.repositories import NotFoundError
from cascade.storage.repositories.decision import DecisionRepository
from cascade.storage.repositories.objective import ObjectiveRepository

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from mcp.server.fastmcp import FastMCP
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AgentContext:
    """Dependencies the MCP tools need to do their work.

    Constructed once at server startup and shared across requests. Sessions are
    created per-request via the :func:`session` context manager so transactions
    are scoped to a single tool call.

    The optional ``checkpointer`` is a long-lived LangGraph saver used by the
    HITL-capable drafting tools (``start_okr_draft`` / ``resume_okr_draft``).
    Tools that don't need it can ignore it; tools that do need it raise an
    instructive error if it isn't wired in.
    """

    sessionmaker: async_sessionmaker[AsyncSession]
    model: BaseChatModel
    checkpointer: BaseCheckpointSaver | None = None

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

    def require_checkpointer(self) -> BaseCheckpointSaver:
        """Return the checkpointer or raise if it isn't wired in.

        Tools that need HITL resumption call this rather than reading the
        attribute directly so the error message names what to fix.
        """
        if self.checkpointer is None:
            raise RuntimeError(
                "This tool requires a LangGraph checkpointer to support "
                "human-in-the-loop resumption. Configure "
                "CASCADE_MCP_CHECKPOINTER_PATH and ensure the MCP server was "
                "built with build_server() (which opens the checkpointer for "
                "you). If you constructed AgentContext directly in tests, "
                "pass a checkpointer parameter."
            )
        return self.checkpointer


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

    # --- start_okr_draft (HITL-capable) -------------------------------------

    @mcp.tool(
        name="start_okr_draft",
        description=(
            "Start a HITL-capable OKR drafting run. Runs the Drafter, Critic, "
            "and Aligner; if the Aligner blocks (resource conflict, vertical "
            "drift, etc.) or the Critic loops past the iteration cap, the "
            "graph pauses at the human node. The response carries a "
            "thread_id and either the completed proposal (status='completed') "
            "or the pause information (status='paused'). For paused runs, "
            "call ``resume_okr_draft`` with the same thread_id and a "
            "decision: 'commit' to accept the proposal as-is, 'revise' to "
            "rerun the Drafter, or 'abandon' to terminate with an audit "
            "marker. Drafts are NOT persisted as committed OKRs by this "
            "tool — call your team's commit flow once the draft is aligned."
        ),
    )
    async def start_okr_draft(intent: str) -> StartOkrDraftResult:
        checkpointer = ctx.require_checkpointer()
        graph = build_graph(model=ctx.model, checkpointer=checkpointer)
        thread_id = str(uuid4())
        config = {"configurable": {"thread_id": thread_id}}

        result = await graph.ainvoke(OKRState(intent=intent), config=config)
        return StartOkrDraftResult(
            thread_id=thread_id,
            state=_state_from_graph_result(graph, config, result),
        )

    # --- resume_okr_draft ---------------------------------------------------

    @mcp.tool(
        name="resume_okr_draft",
        description=(
            "Resume a paused HITL OKR drafting run. ``decision`` must be "
            "'commit' (accept the latest proposal as-is — alignment is forced "
            "to 'aligned' and any blocking conflicts are demoted to 'info'), "
            "'revise' (clear the proposal and rerun the Drafter), or "
            "'abandon' (terminate with a 'blocked' audit marker capturing "
            "the abandonment). The run can pause again on revise — the "
            "response carries the same shape as ``start_okr_draft`` and the "
            "same thread_id can be passed back to ``resume_okr_draft`` to "
            "continue."
        ),
    )
    async def resume_okr_draft(
        thread_id: str,
        decision: str,
        notes: str | None = None,
    ) -> ResumeOkrDraftResult:
        if decision not in ("commit", "revise", "abandon"):
            raise ValueError(f"decision must be one of: commit, revise, abandon. Got {decision!r}")
        checkpointer = ctx.require_checkpointer()
        graph = build_graph(model=ctx.model, checkpointer=checkpointer)
        config = {"configurable": {"thread_id": thread_id}}

        # Verify the thread exists before resuming — gives a clean error if
        # the client passes a stale thread_id rather than letting LangGraph
        # surface a less actionable error from inside resume().
        snapshot = await graph.aget_state(config)
        if snapshot is None or not snapshot.values:
            raise ValueError(
                f"No paused draft found for thread_id={thread_id!r}. The "
                "thread may have been completed already, or the checkpointer "
                "may have been reset (in-memory checkpointers do not survive "
                "server restart)."
            )

        result = await resume_graph(
            graph=graph,
            thread_id=thread_id,
            decision=decision,  # type: ignore[arg-type]
            notes=notes,
        )
        return ResumeOkrDraftResult(
            thread_id=thread_id,
            state=_state_from_graph_result(graph, config, result),
        )


def _state_from_graph_result(
    graph,  # type: ignore[no-untyped-def]
    config: dict,  # type: ignore[type-arg]
    result: dict,  # type: ignore[type-arg]
) -> HitlPauseInfo | HitlCompleteInfo:
    """Inspect a graph invocation result and return the matching HITL state.

    LangGraph signals a paused run via the ``__interrupt__`` field in the
    result dict. When present we return :class:`HitlPauseInfo`; when absent
    the run is complete and we return :class:`HitlCompleteInfo`.

    The proposal and alignment are read from the result dict's keys (which
    have the merged state including any updates from the most recent node).
    For paused runs, alignment may be None (the Critic rejected before the
    Aligner ran); for completed runs it is always present (the supervisor
    only reaches END after alignment is set).
    """
    iterations = result.get("iterations") or []
    iteration_count = len(iterations)

    proposal_view = None
    if result.get("proposal") is not None:
        proposal_view = to_drafted_objective(result["proposal"])

    alignment = result.get("alignment")
    alignment_verdict = alignment.verdict if alignment is not None else None
    alignment_summary = alignment.vertical_reasoning if alignment is not None else None
    conflicts = to_hitl_conflicts(alignment)
    suggestions = list(alignment.suggestions) if alignment is not None else []

    interrupt_marker = result.get("__interrupt__")
    if interrupt_marker:
        # LangGraph 1.0+ surfaces interrupts as a tuple of Interrupt objects.
        # The interrupt's ``value`` carries whatever payload the human node
        # passed to interrupt() — for cascade that includes the reason.
        reason = "awaiting_human"
        try:
            first = (
                interrupt_marker[0]
                if isinstance(interrupt_marker, list | tuple)
                else interrupt_marker
            )
            if hasattr(first, "value") and isinstance(first.value, dict):
                reason = first.value.get("reason", reason)
        except (IndexError, AttributeError, TypeError):
            pass

        return HitlPauseInfo(
            reason=reason,
            iteration_count=iteration_count,
            proposal=proposal_view,
            alignment_verdict=alignment_verdict,
            alignment_summary=alignment_summary,
            conflicts=conflicts,
            suggestions=suggestions,
        )

    # Completed run — proposal and alignment must both be present for the
    # supervisor to have routed to END. If they aren't, it means we hit a
    # terminal "abandoned" path; surface that with whatever proposal we have.
    if proposal_view is None:
        # Defensive — shouldn't happen in practice but better to fail loudly
        # than to return an inconsistent HitlCompleteInfo.
        raise RuntimeError(
            "Graph completed but no proposal in state. This indicates a "
            "supervisor bug — the supervisor should not route to END without "
            "a proposal."
        )
    if alignment_verdict is None:
        # Synthesise a 'blocked' verdict for runs that completed without
        # alignment (e.g. abandoned during pre-Aligner phases).
        alignment_verdict = "blocked"
        alignment_summary = "Run completed without alignment"

    return HitlCompleteInfo(
        proposal=proposal_view,
        alignment_verdict=alignment_verdict,
        alignment_summary=alignment_summary,
        conflicts=conflicts,
        iteration_count=iteration_count,
    )


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
