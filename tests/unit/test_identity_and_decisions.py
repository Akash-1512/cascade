"""Tests for User, Team, Decision, and CheckIn domain models."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from cascade.domain.checkin import CheckIn
from cascade.domain.decision import Alternative, Decision, Evidence
from cascade.domain.enums import (
    CheckInConfidence,
    DecisionEventType,
    KeyResultStatus,
    UserRole,
)
from cascade.domain.identity import Team, User


def _now() -> datetime:
    return datetime.now(tz=UTC)


class TestTeamSlug:
    @pytest.mark.unit
    @pytest.mark.parametrize("good", ["product", "p", "engineering-platform", "team-1", "a1b2"])
    def test_valid_slugs_accepted(self, good: str) -> None:
        team = Team(
            name="Test Team",
            slug=good,
            created_at=_now(),
            updated_at=_now(),
        )
        assert team.slug == good

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "bad",
        [
            "Product",  # uppercase
            "team_with_underscore",
            "-leading-dash",
            "trailing-dash-",
            "with space",
            "",
        ],
    )
    def test_invalid_slugs_rejected(self, bad: str) -> None:
        with pytest.raises(ValidationError):
            Team(name="Test Team", slug=bad, created_at=_now(), updated_at=_now())


class TestUser:
    @pytest.mark.unit
    def test_invalid_email_rejected(self) -> None:
        with pytest.raises(ValidationError):
            User(
                email="not-an-email",
                full_name="Alex Doe",
                role=UserRole.CONTRIBUTOR,
                team_id=uuid4(),
                created_at=_now(),
                updated_at=_now(),
            )

    @pytest.mark.unit
    def test_valid_user(self) -> None:
        user = User(
            email="alex@example.com",
            full_name="Alex Doe",
            role=UserRole.MANAGER,
            team_id=uuid4(),
            created_at=_now(),
            updated_at=_now(),
        )
        assert user.role == UserRole.MANAGER
        assert user.is_active is True

    @pytest.mark.unit
    def test_user_is_frozen(self) -> None:
        """Users are immutable value objects — mutations require new instances."""
        user = User(
            email="alex@example.com",
            full_name="Alex Doe",
            role=UserRole.MANAGER,
            team_id=uuid4(),
            created_at=_now(),
            updated_at=_now(),
        )
        with pytest.raises(ValidationError):
            user.full_name = "Bob"  # type: ignore[misc]


class TestDecisionEvidence:
    @pytest.mark.unit
    def test_alternatives_can_be_empty(self) -> None:
        d = Decision(
            event_type=DecisionEventType.OBJECTIVE_COMMIT,
            objective_id=uuid4(),
            summary="Committed Q2 enterprise expansion objective",
            chosen="Pursue enterprise expansion",
            actor_id=uuid4(),
            created_at=_now(),
        )
        assert d.alternatives == []

    @pytest.mark.unit
    def test_evidence_with_link(self) -> None:
        e = Evidence(
            source="Customer interview Q1 cohort",
            claim="Three of five customers cited integration as their top pain",
            link="https://example.com/research/q1-cohort",
        )
        assert e.link is not None

    @pytest.mark.unit
    def test_alternative_requires_reason(self) -> None:
        with pytest.raises(ValidationError):
            Alternative(option="Status quo", reason_rejected="")

    @pytest.mark.unit
    def test_decision_with_full_context(self) -> None:
        d = Decision(
            event_type=DecisionEventType.KR_TARGET_CHANGE,
            objective_id=uuid4(),
            key_result_id=uuid4(),
            summary="Lowered enterprise win-rate target from 30% to 25%",
            alternatives=[
                Alternative(
                    option="Hold target at 30%",
                    reason_rejected="Insufficient SDR coverage to deliver volume",
                ),
                Alternative(
                    option="Drop the KR",
                    reason_rejected="Removes the only quantitative signal we have on motion",
                ),
            ],
            chosen="Lowered to 25% with weekly review",
            tradeoff="Accepts slower growth in Q2 to fund hiring runway",
            evidence=[
                Evidence(
                    source="Pipeline review Apr 14",
                    claim="Coverage ratio dropped from 4.0x to 2.6x quarter over quarter",
                ),
            ],
            actor_id=uuid4(),
            created_at=_now(),
        )
        assert len(d.alternatives) == 2
        assert d.tradeoff is not None


class TestCheckIn:
    @pytest.mark.unit
    def test_valid_checkin(self) -> None:
        ci = CheckIn(
            key_result_id=uuid4(),
            progress_value=42.0,
            confidence=CheckInConfidence.MEDIUM,
            status=KeyResultStatus.AT_RISK,
            blockers="Waiting on data team for instrumentation",
            narrative="Slipped a week behind plan because of dashboard rework.",
            author_id=uuid4(),
            created_at=_now(),
        )
        assert ci.confidence == CheckInConfidence.MEDIUM

    @pytest.mark.unit
    def test_blank_narrative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CheckIn(
                key_result_id=uuid4(),
                progress_value=42.0,
                confidence=CheckInConfidence.HIGH,
                status=KeyResultStatus.ON_TRACK,
                narrative="",
                author_id=uuid4(),
                created_at=_now(),
            )
