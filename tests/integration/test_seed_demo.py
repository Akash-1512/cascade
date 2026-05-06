"""Integration tests for the demo seed.

Exercises the orchestrator end-to-end against the test database: counts,
idempotency on re-run, refresh-with-reset, decision references, and that
seeded OKRs match the demo data definitions.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cascade.scripts.demo_data import (
    DECISIONS,
    DEMO_TEAM_SLUG,
    LEARNINGS,
    OBJECTIVES,
    USERS,
)
from cascade.scripts.seed_demo import seed_demo
from cascade.storage.models import (
    DecisionORM,
    ObjectiveORM,
    OrganizationalLearningORM,
    TeamORM,
    UserORM,
)


@pytest.mark.integration
async def test_seed_creates_all_demo_entities(session: AsyncSession) -> None:
    """First-run seed creates the team and all expected entities."""
    result = await seed_demo(session)
    await session.commit()

    assert result["team_was_created"] is True
    assert result["skipped"] is False
    assert result["users"] == len(USERS)
    assert result["objectives"] == len(OBJECTIVES)
    assert result["decisions"] == len(DECISIONS)
    assert result["learnings"] == len(LEARNINGS)


@pytest.mark.integration
async def test_seed_creates_team_with_demo_slug(session: AsyncSession) -> None:
    """Team is reachable by the documented slug — the operator console relies on this."""
    await seed_demo(session)
    await session.commit()

    team = (
        await session.execute(select(TeamORM).where(TeamORM.slug == DEMO_TEAM_SLUG))
    ).scalar_one()
    assert team.name  # not asserting exact name to allow rebranding without test churn


@pytest.mark.integration
async def test_seeded_okrs_belong_to_demo_team(session: AsyncSession) -> None:
    await seed_demo(session)
    await session.commit()

    team = (
        await session.execute(select(TeamORM).where(TeamORM.slug == DEMO_TEAM_SLUG))
    ).scalar_one()
    okrs = (
        (await session.execute(select(ObjectiveORM).where(ObjectiveORM.team_id == team.id)))
        .scalars()
        .all()
    )
    assert len(okrs) == len(OBJECTIVES)


@pytest.mark.integration
async def test_seeded_decisions_reference_seeded_okrs(session: AsyncSession) -> None:
    """Every decision points at one of the seeded OKR ids — no orphans."""
    await seed_demo(session)
    await session.commit()

    team = (
        await session.execute(select(TeamORM).where(TeamORM.slug == DEMO_TEAM_SLUG))
    ).scalar_one()
    okr_ids = set(
        (await session.execute(select(ObjectiveORM.id).where(ObjectiveORM.team_id == team.id)))
        .scalars()
        .all()
    )
    decisions = (await session.execute(select(DecisionORM))).scalars().all()
    assert decisions, "No decisions seeded"
    for decision in decisions:
        assert decision.objective_id in okr_ids, (
            f"Decision {decision.id} points at {decision.objective_id}, "
            "which isn't in the demo team's OKRs"
        )


@pytest.mark.integration
async def test_second_run_without_reset_skips(session: AsyncSession) -> None:
    """Calling seed_demo twice without --reset is a no-op the second time."""
    await seed_demo(session)
    await session.commit()
    first_okr_count = len((await session.execute(select(ObjectiveORM))).scalars().all())

    second_result = await seed_demo(session)
    await session.commit()

    assert second_result["skipped"] is True
    assert second_result["team_was_created"] is False

    final_okr_count = len((await session.execute(select(ObjectiveORM))).scalars().all())
    assert final_okr_count == first_okr_count, (
        "Second seed without --reset duplicated OKRs — idempotency broken"
    )


@pytest.mark.integration
async def test_reset_refresh_keeps_counts_stable(session: AsyncSession) -> None:
    """Calling seed_demo twice with --reset on the second run produces the same counts."""
    await seed_demo(session)
    await session.commit()

    second_result = await seed_demo(session, reset=True)
    await session.commit()

    assert second_result["skipped"] is False
    assert second_result["team_was_created"] is False
    assert second_result["users"] == len(USERS)
    assert second_result["objectives"] == len(OBJECTIVES)
    assert second_result["decisions"] == len(DECISIONS)
    assert second_result["learnings"] == len(LEARNINGS)

    # And the database now has exactly one set of demo entities, not two.
    final_okrs = (await session.execute(select(ObjectiveORM))).scalars().all()
    assert len(final_okrs) == len(OBJECTIVES)
    final_decisions = (await session.execute(select(DecisionORM))).scalars().all()
    assert len(final_decisions) == len(DECISIONS)
    final_learnings = (await session.execute(select(OrganizationalLearningORM))).scalars().all()
    assert len(final_learnings) == len(LEARNINGS)
    final_users = (await session.execute(select(UserORM))).scalars().all()
    assert len(final_users) == len(USERS)


@pytest.mark.integration
async def test_reset_does_not_touch_non_demo_data(session: AsyncSession) -> None:
    """Reset wipes only the demo team's rows — production data on the same DB is safe."""
    # Seed a non-demo team and OKR.
    other_team = TeamORM(name="Other Team", slug="other-team")
    session.add(other_team)
    await session.flush()
    await session.refresh(other_team)
    other_user = UserORM(
        email="other@example.com",
        full_name="Other User",
        role="contributor",
        team_id=other_team.id,
        is_active=True,
        password_hash="x",
    )
    session.add(other_user)
    await session.flush()

    # Seed demo, then reset; the non-demo data must survive.
    await seed_demo(session)
    await session.commit()
    await seed_demo(session, reset=True)
    await session.commit()

    surviving_other = (
        await session.execute(select(TeamORM).where(TeamORM.slug == "other-team"))
    ).scalar_one_or_none()
    assert surviving_other is not None, (
        "Non-demo team was deleted — the reset path is leaking outside its scope"
    )


@pytest.mark.integration
async def test_seeded_learnings_have_meaningful_descriptions(
    session: AsyncSession,
) -> None:
    """Smoke check that the demo content is the real content, not placeholders.

    Reviewers seeing 'Lorem ipsum' on the operator console don't get the right
    impression. This test guards against accidentally checking in stub content.
    """
    await seed_demo(session)
    await session.commit()

    learnings = (await session.execute(select(OrganizationalLearningORM))).scalars().all()
    assert len(learnings) == len(LEARNINGS)
    for learning in learnings:
        assert "lorem" not in learning.description.lower()
        assert "todo" not in learning.title.lower()
        assert len(learning.description) > 100, (
            "Learning description is too short to be the real demo content"
        )
