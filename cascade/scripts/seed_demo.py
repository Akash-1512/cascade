"""Idempotent demo seed for cascade.

Run::

    python -m cascade.scripts.seed_demo
    python -m cascade.scripts.seed_demo --reset --verbose

The seed:

1. Looks up the demo team by its fixed slug (``demo-team``)
2. If it exists, wipes its OKRs, decisions, and learnings and refreshes them
3. If it doesn't, creates it
4. Seeds two users, three OKRs across two quarters, eight decisions, three
   organizational learnings — all the content in :mod:`cascade.scripts.demo_data`

Why slug-based idempotency? Because the team UUID is generated on first
create. We need a stable identifier to find the team across runs, and a
human-readable slug doubles as the thing a reviewer pastes into the operator
console sidebar.

The seed never touches non-demo data — the wipe path filters strictly by the
demo team's id, so running it on a production database is safe (it only
touches the demo team's rows; if no demo team exists, it creates one).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import delete, select

from cascade.domain.decision import (
    Alternative,
    DecisionCreate,
    Evidence,
)
from cascade.domain.identity import TeamCreate
from cascade.domain.okr import (
    KeyResultCreate,
    Objective,
    ObjectiveCreate,
    Quarter,
)
from cascade.domain.organizational_learning import OrganizationalLearningCreate
from cascade.scripts.demo_data import (
    DECISIONS,
    DEMO_TEAM_NAME,
    DEMO_TEAM_SLUG,
    LEARNINGS,
    OBJECTIVES,
    USERS,
    DemoDecision,
    DemoObjective,
)
from cascade.storage.models import (
    DecisionORM,
    KeyResultORM,
    ObjectiveORM,
    OrganizationalLearningORM,
    UserORM,
)
from cascade.storage.repositories import NotFoundError
from cascade.storage.repositories.decision import DecisionRepository
from cascade.storage.repositories.objective import ObjectiveRepository
from cascade.storage.repositories.organizational_learning import (
    OrganizationalLearningRepository,
)
from cascade.storage.repositories.team import TeamRepository
from cascade.storage.session import get_sessionmaker

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("cascade.scripts.seed_demo")


async def seed_demo(
    session: AsyncSession,
    *,
    reset: bool = False,
) -> dict[str, object]:
    """Seed (or refresh) the demo dataset.

    Args:
        session: An active async session — caller is responsible for commit.
        reset: When True, also wipe pre-existing demo data before re-seeding.
            When False, the seed will skip the run entirely if the demo team
            already exists. Default False is the safe choice for a fresh DB;
            ``--reset`` is the idiom for "I want clean demo data again".

    Returns:
        A dict with the counts created — used by the CLI for verbose output
        and by tests for assertions.
    """
    team_repo = TeamRepository(session)
    okr_repo = ObjectiveRepository(session)
    decision_repo = DecisionRepository(session)
    learning_repo = OrganizationalLearningRepository(session)

    team_id, team_was_created = await _ensure_team(team_repo)
    logger.info(
        "Demo team %s — %s (%s)",
        team_id,
        "created" if team_was_created else "found",
        DEMO_TEAM_SLUG,
    )

    if not team_was_created and not reset:
        logger.info("Demo team already exists; pass --reset to refresh")
        return {
            "team_id": team_id,
            "team_was_created": False,
            "users": 0,
            "objectives": 0,
            "decisions": 0,
            "learnings": 0,
            "skipped": True,
        }

    if not team_was_created and reset:
        logger.info("Wiping existing demo data before re-seed")
        await _wipe_team_data(session, team_id)

    user_ids = await _seed_users(session, team_id=team_id)
    logger.info("Seeded %d users", len(user_ids))

    objective_id_by_title = await _seed_objectives(okr_repo, team_id=team_id, user_ids=user_ids)
    logger.info("Seeded %d objectives", len(objective_id_by_title))

    decision_count = await _seed_decisions(
        decision_repo,
        objective_id_by_title=objective_id_by_title,
        user_ids=user_ids,
    )
    logger.info("Seeded %d decisions", decision_count)

    learning_count = await _seed_learnings(
        learning_repo, team_id=team_id, objective_id_by_title=objective_id_by_title
    )
    logger.info("Seeded %d organizational learnings", learning_count)

    return {
        "team_id": team_id,
        "team_was_created": team_was_created,
        "users": len(user_ids),
        "objectives": len(objective_id_by_title),
        "decisions": decision_count,
        "learnings": learning_count,
        "skipped": False,
    }


# -- helpers ------------------------------------------------------------------


async def _ensure_team(repo: TeamRepository) -> tuple[UUID, bool]:
    """Return (team_id, was_created)."""
    try:
        team = await repo.get_by_slug(DEMO_TEAM_SLUG)
        return team.id, False
    except NotFoundError:
        team = await repo.create(TeamCreate(name=DEMO_TEAM_NAME, slug=DEMO_TEAM_SLUG))
        return team.id, True


async def _wipe_team_data(session: AsyncSession, team_id: UUID) -> None:
    """Delete all demo data scoped to ``team_id``.

    Order matters because of foreign-key cascades:

    1. Decisions reference objectives (and KRs) → delete decisions first
    2. KRs reference objectives → handled by the ObjectiveORM cascade
    3. Objectives reference team → delete next
    4. Learnings reference team → delete next
    5. Users reference team → delete last
    """
    objective_ids = (
        (await session.execute(select(ObjectiveORM.id).where(ObjectiveORM.team_id == team_id)))
        .scalars()
        .all()
    )

    if objective_ids:
        await session.execute(
            delete(DecisionORM).where(DecisionORM.objective_id.in_(objective_ids))
        )
    await session.execute(delete(ObjectiveORM).where(ObjectiveORM.team_id == team_id))
    await session.execute(
        delete(OrganizationalLearningORM).where(OrganizationalLearningORM.team_id == team_id)
    )
    await session.execute(delete(UserORM).where(UserORM.team_id == team_id))
    await session.flush()


async def _seed_users(session: AsyncSession, *, team_id: UUID) -> dict[str, UUID]:
    """Create demo users via raw ORM (no UserRepository in this codebase yet).

    Returns a map from email → id so callers can wire ownership.
    """
    user_ids: dict[str, UUID] = {}
    for demo_user in USERS:
        orm = UserORM(
            email=demo_user.email,
            full_name=demo_user.full_name,
            role=demo_user.role,
            team_id=team_id,
            is_active=True,
            password_hash="not-a-real-hash",  # noqa: S106 — demo seed only
        )
        session.add(orm)
        await session.flush()
        await session.refresh(orm)
        user_ids[demo_user.email] = orm.id
    return user_ids


async def _seed_objectives(
    repo: ObjectiveRepository,
    *,
    team_id: UUID,
    user_ids: dict[str, UUID],
) -> dict[str, UUID]:
    """Seed objectives. Returns title → id so decisions can reference them."""
    objective_id_by_title: dict[str, UUID] = {}
    for demo_okr in OBJECTIVES:
        owner_id = _require_user(user_ids, demo_okr.owner_email)
        objective = await repo.create(
            _build_objective_payload(demo_okr, team_id=team_id),
            owner_id=owner_id,
        )

        # Status, current values, and KR statuses live behind the create payload
        # — apply them as a follow-up patch since the demo wants to show
        # mid-quarter progress, not just freshly-drafted state.
        await _patch_objective_status_and_progress(repo, objective, demo_okr)

        objective_id_by_title[demo_okr.title] = objective.id
    return objective_id_by_title


def _build_objective_payload(demo_okr: DemoObjective, *, team_id: UUID) -> ObjectiveCreate:
    return ObjectiveCreate(
        title=demo_okr.title,
        description=demo_okr.description,
        team_id=team_id,
        quarter=Quarter(year=demo_okr.quarter_year, quarter=demo_okr.quarter_q),
        key_results=[
            KeyResultCreate(
                description=kr.description,
                metric_type=kr.metric_type,
                baseline_value=kr.baseline_value,
                target_value=kr.target_value,
                current_value=kr.current_value,
                unit=kr.unit,
                weight=kr.weight,
            )
            for kr in demo_okr.key_results
        ],
    )


async def _patch_objective_status_and_progress(
    repo: ObjectiveRepository,
    objective: Objective,
    demo_okr: DemoObjective,
) -> None:
    """Apply status and per-KR status that the create payload doesn't carry."""
    # Use the repository's session directly — these patches don't have a clean
    # repository surface yet, so we mutate ORM rows. This is the only place in
    # the seed that bypasses a repository.
    session = repo._session

    await session.execute(
        ObjectiveORM.__table__.update()
        .where(ObjectiveORM.id == objective.id)
        .values(status=demo_okr.status)
    )

    for kr_domain, kr_demo in zip(objective.key_results, demo_okr.key_results, strict=True):
        await session.execute(
            KeyResultORM.__table__.update()
            .where(KeyResultORM.id == kr_domain.id)
            .values(status=kr_demo.status, current_value=kr_demo.current_value)
        )
    await session.flush()


async def _seed_decisions(
    repo: DecisionRepository,
    *,
    objective_id_by_title: dict[str, UUID],
    user_ids: dict[str, UUID],
) -> int:
    """Seed decisions for each objective."""
    count = 0
    for demo_decision in DECISIONS:
        objective_id = objective_id_by_title.get(demo_decision.objective_title)
        if objective_id is None:
            logger.warning(
                "Decision references unknown objective %r — skipping",
                demo_decision.objective_title,
            )
            continue
        actor_id = _require_user(user_ids, demo_decision.actor_email)
        await repo.create(
            _build_decision_payload(demo_decision, objective_id=objective_id),
            actor_id=actor_id,
        )
        count += 1
    return count


def _build_decision_payload(demo_decision: DemoDecision, *, objective_id: UUID) -> DecisionCreate:
    return DecisionCreate(
        event_type=demo_decision.event_type,
        objective_id=objective_id,
        summary=demo_decision.summary,
        chosen=demo_decision.chosen,
        tradeoff=demo_decision.tradeoff,
        alternatives=[
            Alternative(option=alt.option, reason_rejected=alt.reason_rejected)
            for alt in demo_decision.alternatives
        ],
        evidence=[
            Evidence(source=ev.source, claim=ev.claim, link=ev.link)
            for ev in demo_decision.evidence
        ],
    )


async def _seed_learnings(
    repo: OrganizationalLearningRepository,
    *,
    team_id: UUID,
    objective_id_by_title: dict[str, UUID],
) -> int:
    """Seed organizational learnings."""
    for demo_learning in LEARNINGS:
        affected_ids = [
            str(objective_id_by_title[title])
            for title in demo_learning.affected_objective_titles
            if title in objective_id_by_title
        ]
        await repo.create(
            OrganizationalLearningCreate(
                team_id=team_id,
                quarter=demo_learning.quarter,
                title=demo_learning.title,
                description=demo_learning.description,
                category=demo_learning.category,
                occurrences=demo_learning.occurrences,
                affected_okr_ids=affected_ids,
            )
        )
    return len(LEARNINGS)


def _require_user(user_ids: dict[str, UUID], email: str) -> UUID:
    if email not in user_ids:
        raise KeyError(
            f"Demo data references user {email!r} but it wasn't seeded — "
            "check cascade.scripts.demo_data.USERS"
        )
    return user_ids[email]


# -- CLI ----------------------------------------------------------------------


async def _amain(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m cascade.scripts.seed_demo",
        description="Seed (or refresh) the cascade demo dataset.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Wipe existing demo team data before re-seeding (idempotent refresh)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Log each step",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        try:
            result = await seed_demo(session, reset=args.reset)
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    if result.get("skipped"):
        print(
            f"Demo team {result['team_id']} already exists; pass --reset to refresh.",
            file=sys.stderr,
        )
    else:
        verb = "Created" if result["team_was_created"] else "Refreshed"
        print(
            f"{verb} demo team {result['team_id']} with "
            f"{result['users']} users, {result['objectives']} OKRs, "
            f"{result['decisions']} decisions, {result['learnings']} learnings.",
            file=sys.stderr,
        )
        print(f"\nTeam ID for the operator console sidebar:\n  {result['team_id']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_amain(argv))


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "seed_demo"]
