"""Integration tests for the REST API.

We override the ``get_session`` dependency to use the test SQLite engine
shared across the integration suite. The auth dependency is exercised with
dev-mode UUID tokens.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from cascade.api.dependencies import get_session
from cascade.api.main import app
from cascade.config import get_settings


@pytest_asyncio.fixture
async def api_client(engine: AsyncEngine, session: AsyncSession) -> AsyncIterator[TestClient]:
    """A TestClient with the database dependency overridden to use the test engine.

    The fixture takes both ``engine`` (to make schema available) and
    ``session`` (to get a session that's already wired to the test DB) so we
    can either share the test session or spin up new ones bound to the same
    engine.
    """
    settings = get_settings()
    # Force dev auth mode for tests — JWT verification isn't wired in.
    settings.api_auth_mode = "dev"

    test_sessionmaker = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with test_sessionmaker() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    app.dependency_overrides[get_session] = _override_get_session
    # Also expose the test sessionmaker via app.state so /health/ready uses it
    # instead of trying to connect to a real Postgres.
    app.state.sessionmaker = test_sessionmaker
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _auth_header() -> dict[str, str]:
    """A valid dev-mode bearer token (any UUID will do)."""
    return {"Authorization": f"Bearer {uuid4()}"}


# --- Health -----------------------------------------------------------------


@pytest.mark.integration
async def test_health_returns_version(api_client: TestClient) -> None:
    response = api_client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert "cascade_env" in body


@pytest.mark.integration
async def test_readiness_checks_database(api_client: TestClient) -> None:
    response = api_client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"


# --- Auth -------------------------------------------------------------------


@pytest.mark.integration
async def test_protected_route_rejects_missing_token(api_client: TestClient) -> None:
    response = api_client.get(f"/v1/teams/{uuid4()}/okrs")
    assert response.status_code == 401
    assert "Authorization" in response.json()["detail"]


@pytest.mark.integration
async def test_dev_mode_rejects_non_uuid_token(api_client: TestClient) -> None:
    response = api_client.get(
        f"/v1/teams/{uuid4()}/okrs",
        headers={"Authorization": "Bearer not-a-uuid"},
    )
    assert response.status_code == 401


# --- OKR routes -------------------------------------------------------------


@pytest.mark.integration
async def test_list_okrs_returns_summaries(api_client: TestClient, session: AsyncSession) -> None:
    from cascade.domain.enums import MetricType
    from cascade.domain.okr import KeyResultCreate, ObjectiveCreate, Quarter
    from cascade.storage.repositories.objective import ObjectiveRepository
    from tests.integration.factories import seed_team, seed_user

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
                    description="Lift weekly active accounts",
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

    response = api_client.get(f"/v1/teams/{team.id}/okrs", headers=_auth_header())
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["items"][0]["title"].startswith("Reach PMF")


@pytest.mark.integration
async def test_list_okrs_filters_by_quarter(api_client: TestClient, session: AsyncSession) -> None:
    from cascade.domain.enums import MetricType
    from cascade.domain.okr import KeyResultCreate, ObjectiveCreate, Quarter
    from cascade.storage.repositories.objective import ObjectiveRepository
    from tests.integration.factories import seed_team, seed_user

    team = await seed_team(session)
    user = await seed_user(session, team_id=team.id)
    repo = ObjectiveRepository(session)
    for q in (1, 2):
        await repo.create(
            ObjectiveCreate(
                title=f"OKR for Q{q} of 2026",
                team_id=team.id,
                quarter=Quarter(year=2026, quarter=q),
                key_results=[
                    KeyResultCreate(
                        description=f"A KR for Q{q}",
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

    response = api_client.get(f"/v1/teams/{team.id}/okrs?quarter=2026Q1", headers=_auth_header())
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert "Q1" in body["items"][0]["title"]


@pytest.mark.integration
async def test_list_okrs_invalid_quarter_returns_422(api_client: TestClient) -> None:
    response = api_client.get(f"/v1/teams/{uuid4()}/okrs?quarter=invalid", headers=_auth_header())
    assert response.status_code == 422


@pytest.mark.integration
async def test_get_okr_returns_full_view(api_client: TestClient, session: AsyncSession) -> None:
    from cascade.domain.enums import MetricType
    from cascade.domain.okr import KeyResultCreate, ObjectiveCreate, Quarter
    from cascade.storage.repositories.objective import ObjectiveRepository
    from tests.integration.factories import seed_team, seed_user

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
                    description="Lift weekly active accounts from 200 to 800",
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

    response = api_client.get(f"/v1/okrs/{okr.id}", headers=_auth_header())
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(okr.id)
    assert len(body["key_results"]) == 1
    # Linear scoring: (500-200)/(800-200) = 0.5
    assert body["key_results"][0]["score"] == pytest.approx(0.5)


@pytest.mark.integration
async def test_get_okr_returns_404_for_unknown_id(api_client: TestClient) -> None:
    response = api_client.get(f"/v1/okrs/{uuid4()}", headers=_auth_header())
    assert response.status_code == 404


@pytest.mark.integration
async def test_get_okr_score_returns_breakdown(
    api_client: TestClient, session: AsyncSession
) -> None:
    from cascade.domain.enums import MetricType
    from cascade.domain.okr import KeyResultCreate, ObjectiveCreate, Quarter
    from cascade.storage.repositories.objective import ObjectiveRepository
    from tests.integration.factories import seed_team, seed_user

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
                    description="Lift weekly active accounts from 200 to 800",
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

    response = api_client.get(f"/v1/okrs/{okr.id}/score", headers=_auth_header())
    assert response.status_code == 200
    body = response.json()
    assert body["objective_id"] == str(okr.id)
    assert body["overall_score"] == pytest.approx(0.5)
    assert len(body["key_result_scores"]) == 1


# --- Decision routes --------------------------------------------------------


@pytest.mark.integration
async def test_list_decisions_returns_causal_trail(
    api_client: TestClient, session: AsyncSession
) -> None:
    from cascade.domain.decision import Alternative, DecisionCreate
    from cascade.domain.enums import DecisionEventType, MetricType
    from cascade.domain.okr import KeyResultCreate, ObjectiveCreate, Quarter
    from cascade.storage.repositories.decision import DecisionRepository
    from cascade.storage.repositories.objective import ObjectiveRepository
    from tests.integration.factories import seed_team, seed_user

    team = await seed_team(session)
    user = await seed_user(session, team_id=team.id)
    okr = await ObjectiveRepository(session).create(
        ObjectiveCreate(
            title="An OKR with a decision attached for testing",
            team_id=team.id,
            quarter=Quarter(year=2026, quarter=2),
            key_results=[
                KeyResultCreate(
                    description="A KR for the test scenario",
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
                Alternative(
                    option="Hold Q1 targets",
                    reason_rejected="No longer relevant for Q2",
                )
            ],
            chosen="Proceed with new SMB focus",
            tradeoff="Defers enterprise expansion to Q3",
        ),
        actor_id=user.id,
    )
    await session.commit()

    response = api_client.get(f"/v1/okrs/{okr.id}/decisions", headers=_auth_header())
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["items"][0]["chosen"] == "Proceed with new SMB focus"
    assert "tradeoff" in body["items"][0]


# --- Learning routes --------------------------------------------------------


@pytest.mark.integration
async def test_list_learnings_returns_themes(api_client: TestClient, session: AsyncSession) -> None:
    from cascade.domain.organizational_learning import OrganizationalLearningCreate
    from cascade.storage.repositories.organizational_learning import (
        OrganizationalLearningRepository,
    )
    from tests.integration.factories import seed_team

    team = await seed_team(session)
    repo = OrganizationalLearningRepository(session)
    await repo.create(
        OrganizationalLearningCreate(
            team_id=team.id,
            quarter="2026Q2",
            title="Underestimated dependency on data team",
            description="Multiple OKRs slipped because instrumentation took longer than planned.",
            category="estimation",
            occurrences=3,
        )
    )
    await session.commit()

    response = api_client.get(f"/v1/teams/{team.id}/learnings", headers=_auth_header())
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["items"][0]["category"] == "estimation"


@pytest.mark.integration
async def test_list_learnings_filters_by_category(
    api_client: TestClient, session: AsyncSession
) -> None:
    from cascade.domain.organizational_learning import OrganizationalLearningCreate
    from cascade.storage.repositories.organizational_learning import (
        OrganizationalLearningRepository,
    )
    from tests.integration.factories import seed_team

    team = await seed_team(session)
    repo = OrganizationalLearningRepository(session)
    for category in ("estimation", "process", "execution"):
        await repo.create(
            OrganizationalLearningCreate(
                team_id=team.id,
                quarter="2026Q2",
                title=f"Theme for {category}",
                description=f"Description for {category} category theme",
                category=category,  # type: ignore[arg-type]
                occurrences=2,
            )
        )
    await session.commit()

    response = api_client.get(
        f"/v1/teams/{team.id}/learnings?category=estimation",
        headers=_auth_header(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["items"][0]["category"] == "estimation"
