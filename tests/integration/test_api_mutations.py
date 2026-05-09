"""Integration tests for the REST API mutation endpoints.

Mirrors the fixture and dev-mode-auth conventions of ``test_api_routes.py``
but lives in its own file because the surface is large enough to read on its
own. Tests are scoped tightly: each one seeds the minimum precondition (a
team, a user, sometimes an OKR), POSTs, and asserts on the response. Cross-
cutting concerns (auth, status codes) are covered once and not retested per
endpoint.
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
    """A TestClient with the database dependency overridden to use the test engine."""
    settings = get_settings()
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
    app.state.sessionmaker = test_sessionmaker
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _auth_header(user_id: str | None = None) -> dict[str, str]:
    """A valid dev-mode bearer token. Pass user_id to attribute writes to a specific user."""
    return {"Authorization": f"Bearer {user_id or uuid4()}"}


# -- POST /v1/okrs/{objective_id}/decisions ----------------------------------


@pytest.mark.integration
async def test_post_decision_returns_201_with_location_header(
    api_client: TestClient, session: AsyncSession
) -> None:
    from cascade.domain.enums import MetricType
    from cascade.domain.okr import KeyResultCreate, ObjectiveCreate, Quarter
    from cascade.storage.repositories.objective import ObjectiveRepository
    from tests.integration.factories import seed_team, seed_user

    team = await seed_team(session)
    user = await seed_user(session, team_id=team.id)
    okr = await ObjectiveRepository(session).create(
        ObjectiveCreate(
            title="OKR for testing decisions POST",
            team_id=team.id,
            quarter=Quarter(year=2026, quarter=2),
            key_results=[
                KeyResultCreate(
                    description="A test KR for the integration scenario",
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

    body = {
        "event_type": "objective_commit",
        "summary": "Committed after Q1 pipeline review and stakeholder sign-off",
        "chosen": "Proceed with the SMB pivot",
        "tradeoff": "Defers enterprise expansion to Q3",
        "alternatives": [
            {
                "option": "Hold Q1 targets",
                "reason_rejected": "No longer relevant after pipeline review",
            }
        ],
        "evidence": [
            {"source": "Q1 retrospective", "claim": "3 of 4 pilots cited integration cost"}
        ],
        "actor_id": str(user.id),
    }

    response = api_client.post(f"/v1/okrs/{okr.id}/decisions", json=body, headers=_auth_header())
    assert response.status_code == 201, response.text
    assert response.headers.get("Location") == f"/v1/okrs/{okr.id}/decisions"
    payload = response.json()
    assert payload["chosen"] == "Proceed with the SMB pivot"
    assert payload["objective_id"] == str(okr.id)
    assert payload["actor_id"] == str(user.id)
    assert len(payload["alternatives"]) == 1


@pytest.mark.integration
async def test_post_decision_attributes_to_principal_when_actor_id_omitted(
    api_client: TestClient, session: AsyncSession
) -> None:
    """If actor_id isn't in the body, the principal's user_id is used."""
    from cascade.domain.enums import MetricType
    from cascade.domain.okr import KeyResultCreate, ObjectiveCreate, Quarter
    from cascade.storage.repositories.objective import ObjectiveRepository
    from tests.integration.factories import seed_team, seed_user

    team = await seed_team(session)
    user = await seed_user(session, team_id=team.id)
    okr = await ObjectiveRepository(session).create(
        ObjectiveCreate(
            title="OKR for testing principal attribution",
            team_id=team.id,
            quarter=Quarter(year=2026, quarter=2),
            key_results=[
                KeyResultCreate(
                    description="A test KR for the integration scenario",
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

    body = {
        "event_type": "objective_commit",
        "summary": "Committed without explicit actor_id in the body for testing",
        "chosen": "Use principal's user_id",
        "alternatives": [],
        "evidence": [],
    }
    # Use the seeded user's id as the bearer token (dev mode).
    response = api_client.post(
        f"/v1/okrs/{okr.id}/decisions",
        json=body,
        headers=_auth_header(user_id=str(user.id)),
    )
    assert response.status_code == 201, response.text
    assert response.json()["actor_id"] == str(user.id)


@pytest.mark.integration
async def test_post_decision_returns_404_for_missing_okr(
    api_client: TestClient, session: AsyncSession
) -> None:
    from tests.integration.factories import seed_team, seed_user

    team = await seed_team(session)
    user = await seed_user(session, team_id=team.id)
    await session.commit()

    body = {
        "event_type": "objective_commit",
        "summary": "Decision targeting a missing Objective for the not-found path",
        "chosen": "X",
        "alternatives": [],
        "evidence": [],
        "actor_id": str(user.id),
    }
    nonexistent = uuid4()
    response = api_client.post(
        f"/v1/okrs/{nonexistent}/decisions", json=body, headers=_auth_header()
    )
    assert response.status_code == 404
    assert str(nonexistent) in response.json()["detail"]


@pytest.mark.integration
async def test_post_decision_validates_event_type(api_client: TestClient) -> None:
    """Unknown event_type strings → 422 with FastAPI's default validation error."""
    body = {
        "event_type": "definitely_not_a_real_event_type",
        "summary": "Some summary that is plenty long enough to clear validation",
        "chosen": "X",
    }
    response = api_client.post(f"/v1/okrs/{uuid4()}/decisions", json=body, headers=_auth_header())
    assert response.status_code == 422


# -- POST /v1/teams/{team_id}/learnings --------------------------------------


@pytest.mark.integration
async def test_post_learning_returns_201_with_canonical_response(
    api_client: TestClient, session: AsyncSession
) -> None:
    from tests.integration.factories import seed_team

    team = await seed_team(session)
    await session.commit()

    body = {
        "quarter": "2026Q1",
        "title": "Underestimated CSM adoption friction on data products",
        "description": (
            "Three Q1 OKRs shipped technically-correct work that the CSM team "
            "didn't end up using. Pattern indicates a missing operator-adoption KR."
        ),
        "category": "alignment",
        "occurrences": 3,
    }

    response = api_client.post(f"/v1/teams/{team.id}/learnings", json=body, headers=_auth_header())
    assert response.status_code == 201, response.text
    assert response.headers.get("Location") == f"/v1/teams/{team.id}/learnings"
    payload = response.json()
    assert payload["title"].startswith("Underestimated")
    assert payload["team_id"] == str(team.id)
    assert payload["category"] == "alignment"
    assert payload["occurrences"] == 3


@pytest.mark.integration
async def test_post_learning_returns_404_for_missing_team(api_client: TestClient) -> None:
    nonexistent = uuid4()
    body = {
        "quarter": "2026Q1",
        "title": "An organizational learning whose team does not exist",
        "description": "Should fail before insertion with a clean 404 message.",
        "category": "process",
        "occurrences": 1,
    }
    response = api_client.post(
        f"/v1/teams/{nonexistent}/learnings", json=body, headers=_auth_header()
    )
    assert response.status_code == 404
    assert str(nonexistent) in response.json()["detail"]


@pytest.mark.integration
async def test_post_learning_validates_quarter_format(api_client: TestClient) -> None:
    body = {
        "quarter": "2026-Q1",  # wrong format
        "title": "A learning",
        "description": "Description.",
        "category": "process",
        "occurrences": 1,
    }
    response = api_client.post(f"/v1/teams/{uuid4()}/learnings", json=body, headers=_auth_header())
    assert response.status_code == 422


# -- POST /v1/key-results/{key_result_id}/checkins ---------------------------


@pytest.mark.integration
async def test_post_checkin_returns_201_with_status_derived_from_confidence(
    api_client: TestClient, session: AsyncSession
) -> None:
    """Without an explicit new_status, confidence drives the persisted status."""
    from cascade.domain.enums import MetricType
    from cascade.domain.okr import KeyResultCreate, ObjectiveCreate, Quarter
    from cascade.storage.repositories.objective import ObjectiveRepository
    from tests.integration.factories import seed_team, seed_user

    team = await seed_team(session)
    user = await seed_user(session, team_id=team.id)
    okr = await ObjectiveRepository(session).create(
        ObjectiveCreate(
            title="OKR for testing checkin POST",
            team_id=team.id,
            quarter=Quarter(year=2026, quarter=2),
            key_results=[
                KeyResultCreate(
                    description="A test KR for the integration scenario",
                    metric_type=MetricType.NUMBER,
                    baseline_value=0,
                    target_value=100,
                    current_value=20,
                )
            ],
        ),
        owner_id=user.id,
    )
    kr_id = okr.key_results[0].id
    await session.commit()

    body = {
        "progress_value": 35.0,
        "confidence": "high",
        "narrative": "On track — pipeline conversion improved week-over-week.",
        "author_id": str(user.id),
    }
    response = api_client.post(
        f"/v1/key-results/{kr_id}/checkins", json=body, headers=_auth_header()
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    # high confidence → on_track
    assert payload["status"] == "on_track"
    assert payload["progress_value"] == 35.0
    assert payload["author_id"] == str(user.id)


@pytest.mark.integration
async def test_post_checkin_respects_explicit_new_status_override(
    api_client: TestClient, session: AsyncSession
) -> None:
    """When new_status is given, it overrides the confidence-derived default."""
    from cascade.domain.enums import MetricType
    from cascade.domain.okr import KeyResultCreate, ObjectiveCreate, Quarter
    from cascade.storage.repositories.objective import ObjectiveRepository
    from tests.integration.factories import seed_team, seed_user

    team = await seed_team(session)
    user = await seed_user(session, team_id=team.id)
    okr = await ObjectiveRepository(session).create(
        ObjectiveCreate(
            title="OKR for explicit-status override test",
            team_id=team.id,
            quarter=Quarter(year=2026, quarter=2),
            key_results=[
                KeyResultCreate(
                    description="A test KR for the integration scenario",
                    metric_type=MetricType.NUMBER,
                    baseline_value=0,
                    target_value=100,
                    current_value=10,
                )
            ],
        ),
        owner_id=user.id,
    )
    kr_id = okr.key_results[0].id
    await session.commit()

    body = {
        "progress_value": 12.0,
        "confidence": "high",  # would normally produce on_track
        "narrative": "Numbers look fine but I'm reading a structural risk for next quarter.",
        "new_status": "at_risk",  # explicit override
        "author_id": str(user.id),
    }
    response = api_client.post(
        f"/v1/key-results/{kr_id}/checkins", json=body, headers=_auth_header()
    )
    assert response.status_code == 201
    assert response.json()["status"] == "at_risk"


@pytest.mark.integration
async def test_post_checkin_returns_404_for_missing_kr(api_client: TestClient) -> None:
    body = {
        "progress_value": 50.0,
        "confidence": "medium",
        "narrative": "Targeting a non-existent KR — should 404.",
    }
    nonexistent = uuid4()
    response = api_client.post(
        f"/v1/key-results/{nonexistent}/checkins", json=body, headers=_auth_header()
    )
    assert response.status_code == 404
    assert str(nonexistent) in response.json()["detail"]


# -- POST /v1/teams/{team_id}/okrs -------------------------------------------


@pytest.mark.integration
async def test_post_okr_creates_objective_with_kr_returns_201(
    api_client: TestClient, session: AsyncSession
) -> None:
    from tests.integration.factories import seed_team, seed_user

    team = await seed_team(session)
    user = await seed_user(session, team_id=team.id)
    await session.commit()

    body = {
        "title": "Reach product-market fit in the SMB segment this quarter",
        "description": "Convert Q1 enterprise pilot insights into an SMB push.",
        "quarter": "2026Q2",
        "owner_id": str(user.id),
        "key_results": [
            {
                "description": "Lift weekly active accounts from 200 to 800",
                "metric_type": "number",
                "baseline_value": 200,
                "target_value": 800,
                "current_value": 200,
                "unit": "accounts",
                "weight": 0.5,
            },
            {
                "description": "Move trial-to-paid conversion from 6% to 14%",
                "metric_type": "percentage",
                "baseline_value": 6,
                "target_value": 14,
                "current_value": 6,
                "weight": 0.5,
            },
        ],
    }

    response = api_client.post(f"/v1/teams/{team.id}/okrs", json=body, headers=_auth_header())
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["title"].startswith("Reach product-market fit")
    assert payload["team_id"] == str(team.id)
    assert payload["owner_id"] == str(user.id)
    assert payload["status"] == "draft"  # newly-created OKRs start as draft
    assert len(payload["key_results"]) == 2
    # Location header points at the canonical GET path
    assert response.headers["Location"] == f"/v1/okrs/{payload['id']}"


@pytest.mark.integration
async def test_post_okr_returns_404_for_missing_team(
    api_client: TestClient, session: AsyncSession
) -> None:
    from tests.integration.factories import seed_team, seed_user

    real_team = await seed_team(session)
    user = await seed_user(session, team_id=real_team.id)
    await session.commit()

    body = {
        "title": "OKR targeting a missing team for the not-found path",
        "quarter": "2026Q2",
        "owner_id": str(user.id),
        "key_results": [
            {
                "description": "Some KR",
                "metric_type": "number",
                "baseline_value": 0,
                "target_value": 1,
                "weight": 1.0,
            }
        ],
    }
    nonexistent = uuid4()
    response = api_client.post(f"/v1/teams/{nonexistent}/okrs", json=body, headers=_auth_header())
    assert response.status_code == 404
    assert str(nonexistent) in response.json()["detail"]


@pytest.mark.integration
async def test_post_okr_returns_404_for_missing_parent(
    api_client: TestClient, session: AsyncSession
) -> None:
    from tests.integration.factories import seed_team, seed_user

    team = await seed_team(session)
    user = await seed_user(session, team_id=team.id)
    await session.commit()

    nonexistent_parent = uuid4()
    body = {
        "title": "Child OKR with a parent that does not exist",
        "quarter": "2026Q2",
        "owner_id": str(user.id),
        "parent_objective_id": str(nonexistent_parent),
        "key_results": [
            {
                "description": "Some KR",
                "metric_type": "number",
                "baseline_value": 0,
                "target_value": 1,
                "weight": 1.0,
            }
        ],
    }
    response = api_client.post(f"/v1/teams/{team.id}/okrs", json=body, headers=_auth_header())
    assert response.status_code == 404
    assert str(nonexistent_parent) in response.json()["detail"]


@pytest.mark.integration
async def test_post_okr_validates_kr_weight_range(
    api_client: TestClient, session: AsyncSession
) -> None:
    from tests.integration.factories import seed_team, seed_user

    team = await seed_team(session)
    user = await seed_user(session, team_id=team.id)
    await session.commit()

    body = {
        "title": "OKR with an invalid KR weight (>1.0)",
        "quarter": "2026Q2",
        "owner_id": str(user.id),
        "key_results": [
            {
                "description": "KR",
                "metric_type": "number",
                "baseline_value": 0,
                "target_value": 1,
                "weight": 1.5,  # invalid: must be <= 1.0
            }
        ],
    }
    response = api_client.post(f"/v1/teams/{team.id}/okrs", json=body, headers=_auth_header())
    assert response.status_code == 422


# -- Cross-cutting: auth ------------------------------------------------------


@pytest.mark.integration
async def test_post_decision_rejects_missing_token(api_client: TestClient) -> None:
    """All POST endpoints share the same auth dependency — testing one suffices."""
    body = {
        "event_type": "objective_commit",
        "summary": "Will not be persisted because the request has no auth header",
        "chosen": "X",
    }
    response = api_client.post(f"/v1/okrs/{uuid4()}/decisions", json=body)
    assert response.status_code in (401, 403)
