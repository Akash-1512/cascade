"""Demo data for ``cascade.scripts.seed_demo``.

The seed script writes one team, two users, three OKRs across two quarters,
eight decisions, and three organizational learnings. Everything in this
module is plain Python data — the orchestrator just walks it and calls the
repositories.

Why declare it here rather than inline in the orchestrator? Because a
reviewer reading the demo data is reading what cascade is *for* — the OKRs
look real, the decisions show why-it-changed reasoning, the learnings
demonstrate the organizational memory. Keeping it readable matters more
than keeping it short.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from cascade.domain.enums import (
    DecisionEventType,
    KeyResultStatus,
    MetricType,
    ObjectiveStatus,
    UserRole,
)

# A fixed team slug so the seed can detect existing data and refresh it
# rather than creating duplicates. "demo-team" is reserved for this purpose.
DEMO_TEAM_SLUG = "demo-team"
DEMO_TEAM_NAME = "Demo Team"


@dataclass(frozen=True)
class DemoUser:
    email: str
    full_name: str
    role: UserRole


@dataclass(frozen=True)
class DemoKeyResult:
    description: str
    metric_type: MetricType
    baseline_value: float
    target_value: float
    current_value: float
    unit: str | None
    weight: float
    status: KeyResultStatus


@dataclass(frozen=True)
class DemoObjective:
    title: str
    description: str
    quarter_year: int
    quarter_q: int
    status: ObjectiveStatus
    owner_email: str
    key_results: list[DemoKeyResult]


@dataclass(frozen=True)
class DemoAlternative:
    option: str
    reason_rejected: str


@dataclass(frozen=True)
class DemoEvidence:
    source: str
    claim: str
    link: str | None = None


@dataclass(frozen=True)
class DemoDecision:
    objective_title: str  # match by title — id is generated at seed time
    event_type: DecisionEventType
    summary: str
    chosen: str
    tradeoff: str | None
    alternatives: list[DemoAlternative] = field(default_factory=list)
    evidence: list[DemoEvidence] = field(default_factory=list)
    actor_email: str = "alex@demo.cascade"


LearningCategory = Literal[
    "execution", "planning", "alignment", "estimation", "external", "process"
]


@dataclass(frozen=True)
class DemoLearning:
    quarter: str
    title: str
    description: str
    category: LearningCategory
    occurrences: int
    affected_objective_titles: list[str] = field(default_factory=list)


# -- the actual demo content --------------------------------------------------

USERS: list[DemoUser] = [
    DemoUser(
        email="alex@demo.cascade",
        full_name="Alex Martinez",
        role=UserRole.MANAGER,
    ),
    DemoUser(
        email="sam@demo.cascade",
        full_name="Sam Chen",
        role=UserRole.CONTRIBUTOR,
    ),
]


OBJECTIVES: list[DemoObjective] = [
    # --- Active OKR for the current quarter ---------------------------------
    DemoObjective(
        title="Reach product-market fit in the SMB segment this quarter",
        description=(
            "Convert the Q1 enterprise pilot insights into a focused SMB push. "
            "Validate that the self-serve onboarding flow produces activated "
            "weekly usage, not just signups."
        ),
        quarter_year=2026,
        quarter_q=2,
        status=ObjectiveStatus.ACTIVE,
        owner_email="alex@demo.cascade",
        key_results=[
            DemoKeyResult(
                description="Lift weekly active accounts from 200 to 800",
                metric_type=MetricType.NUMBER,
                baseline_value=200,
                target_value=800,
                current_value=480,
                unit="accounts",
                weight=0.4,
                status=KeyResultStatus.ON_TRACK,
            ),
            DemoKeyResult(
                description="Move trial-to-paid conversion from 6% to 14%",
                metric_type=MetricType.PERCENTAGE,
                baseline_value=6,
                target_value=14,
                current_value=9,
                unit=None,
                weight=0.4,
                status=KeyResultStatus.AT_RISK,
            ),
            DemoKeyResult(
                description="Cut median time-to-first-value from 22 to 8 minutes",
                metric_type=MetricType.NUMBER,
                baseline_value=22,
                target_value=8,
                current_value=14,
                unit="minutes",
                weight=0.2,
                status=KeyResultStatus.ON_TRACK,
            ),
        ],
    ),
    # --- Active OKR for the current quarter, in a riskier state -------------
    DemoObjective(
        title="Ship the v2 retention engine ahead of the renewals window",
        description=(
            "Replace the rules-based churn-risk engine with a feature-store "
            "backed model. Required before the Aug-Sept renewals push so the "
            "CSMs have a probability score on every account."
        ),
        quarter_year=2026,
        quarter_q=2,
        status=ObjectiveStatus.ACTIVE,
        owner_email="sam@demo.cascade",
        key_results=[
            DemoKeyResult(
                description="Deploy v2 model to staging with parity on the validation set",
                metric_type=MetricType.MILESTONE,
                baseline_value=0,
                target_value=1,
                current_value=1,
                unit=None,
                weight=0.3,
                status=KeyResultStatus.ACHIEVED,
            ),
            DemoKeyResult(
                description="Reduce p95 scoring latency from 240ms to under 80ms",
                metric_type=MetricType.NUMBER,
                baseline_value=240,
                target_value=80,
                current_value=180,
                unit="ms",
                weight=0.3,
                status=KeyResultStatus.AT_RISK,
            ),
            DemoKeyResult(
                description="Earn CSM team sign-off on the new account-detail UI",
                metric_type=MetricType.MILESTONE,
                baseline_value=0,
                target_value=1,
                current_value=0,
                unit=None,
                weight=0.4,
                status=KeyResultStatus.OFF_TRACK,
            ),
        ],
    ),
    # --- A closed OKR from the prior quarter for the trail to point at ------
    DemoObjective(
        title="Land the first three enterprise design partners",
        description=("Q1 push to validate enterprise demand. Used as input for the Q2 SMB pivot."),
        quarter_year=2026,
        quarter_q=1,
        status=ObjectiveStatus.ACHIEVED,
        owner_email="alex@demo.cascade",
        key_results=[
            DemoKeyResult(
                description="Sign 3 enterprise design partner contracts",
                metric_type=MetricType.NUMBER,
                baseline_value=0,
                target_value=3,
                current_value=3,
                unit="contracts",
                weight=0.5,
                status=KeyResultStatus.ACHIEVED,
            ),
            DemoKeyResult(
                description="Run 5 weeks of joint shipping cadence with each partner",
                metric_type=MetricType.NUMBER,
                baseline_value=0,
                target_value=5,
                current_value=5,
                unit="weeks",
                weight=0.5,
                status=KeyResultStatus.ACHIEVED,
            ),
        ],
    ),
]


DECISIONS: list[DemoDecision] = [
    DemoDecision(
        objective_title="Reach product-market fit in the SMB segment this quarter",
        event_type=DecisionEventType.OBJECTIVE_COMMIT,
        summary="Committed Q2 SMB OKR after Q1 enterprise pilot review",
        chosen="Pivot from enterprise breadth to SMB conversion focus",
        tradeoff=(
            "Defers enterprise expansion to Q3. We accept slower top-line ARR "
            "growth in exchange for a clearer learning signal on product-market fit."
        ),
        alternatives=[
            DemoAlternative(
                option="Keep dual focus (enterprise + SMB)",
                reason_rejected=(
                    "Q1 retro showed the team's bandwidth couldn't sustain two "
                    "fundamentally different motions; quality slipped on both."
                ),
            ),
            DemoAlternative(
                option="Double down on enterprise",
                reason_rejected=(
                    "Pilot data showed 6-9 month sales cycles; the team won't "
                    "have outcome-bearing signal in time for Q3 planning."
                ),
            ),
        ],
        evidence=[
            DemoEvidence(
                source="Q1 retrospective",
                claim="3 of 4 enterprise pilots cited integration cost as the blocker",
                link="https://example.com/q1-retro",
            ),
        ],
    ),
    DemoDecision(
        objective_title="Reach product-market fit in the SMB segment this quarter",
        event_type=DecisionEventType.KR_TARGET_CHANGE,
        summary="Lowered trial-to-paid target from 18% to 14% after pricing audit",
        chosen="14% conversion target",
        tradeoff=(
            "Less ambitious headline number, but the team is no longer aiming "
            "at a number that requires a price change we haven't approved."
        ),
        alternatives=[
            DemoAlternative(
                option="Keep the 18% target",
                reason_rejected=(
                    "Held a sandbagging discussion; finance pushed back that "
                    "18% would require either a price cut or a free-trial "
                    "extension we can't fund this quarter."
                ),
            ),
        ],
        evidence=[
            DemoEvidence(
                source="Pricing model v3",
                claim="18% conversion at current price implies negative gross margin on SMB tier",
            ),
        ],
    ),
    DemoDecision(
        objective_title="Ship the v2 retention engine ahead of the renewals window",
        event_type=DecisionEventType.OBJECTIVE_COMMIT,
        summary="Committed v2 retention engine OKR with HITL escalation for the latency KR",
        chosen="Proceed with v2 build; latency target raised by Aligner intervention",
        tradeoff=(
            "Accepted a 80ms p95 instead of the originally proposed 50ms — the "
            "tighter target conflicted with the model's feature richness and "
            "the Aligner flagged a blocking conflict with the data team's quarter."
        ),
        alternatives=[
            DemoAlternative(
                option="Original 50ms target",
                reason_rejected=(
                    "Aligner detected blocking conflict with data team's "
                    "feature-store rollout; would require shadow infra they "
                    "weren't planning to ship until Q3."
                ),
            ),
        ],
        evidence=[
            DemoEvidence(
                source="Alignment check",
                claim="Vertical alignment 0.92, horizontal blocking conflict resolved by raising latency target",
            ),
        ],
        actor_email="sam@demo.cascade",
    ),
    DemoDecision(
        objective_title="Ship the v2 retention engine ahead of the renewals window",
        event_type=DecisionEventType.RISK_INTERVENTION,
        summary="Risk Sentinel flagged CSM sign-off KR; intervention scheduled",
        chosen="Schedule weekly CSM working session through end of quarter",
        tradeoff=(
            "Costs 90 minutes of senior CSM time per week, but the alternative "
            "is shipping a UI the CSMs reject in week 12."
        ),
        alternatives=[
            DemoAlternative(
                option="Wait for the CSMs to surface concerns asynchronously",
                reason_rejected=(
                    "Async feedback loops have 7-10 day latency; the renewals "
                    "window starts in 8 weeks."
                ),
            ),
        ],
        evidence=[
            DemoEvidence(
                source="Risk Sentinel assessment",
                claim="velocity stalled, requires_intervention=true",
            ),
        ],
        actor_email="sam@demo.cascade",
    ),
    DemoDecision(
        objective_title="Land the first three enterprise design partners",
        event_type=DecisionEventType.OBJECTIVE_COMMIT,
        summary="Committed Q1 enterprise design-partner OKR",
        chosen="3 partners, 5 weeks of joint cadence each",
        tradeoff=(
            "5 weeks per partner is below industry-standard 8-week design-partner "
            "engagements; we accept shorter learning windows for breadth."
        ),
        alternatives=[
            DemoAlternative(
                option="2 partners, 8 weeks each",
                reason_rejected="Would not generate enough horizontal signal across verticals",
            ),
        ],
        evidence=[],
    ),
    DemoDecision(
        objective_title="Land the first three enterprise design partners",
        event_type=DecisionEventType.OBJECTIVE_CLOSE,
        summary="Closed Q1 OKR — all KRs achieved",
        chosen="Mark achieved; learnings carried forward into Q2 SMB OKR",
        tradeoff=None,
        alternatives=[],
        evidence=[
            DemoEvidence(
                source="Final partner readout",
                claim="3/3 partners signed; 5/5 cadences completed; 12 net learnings logged",
            ),
        ],
    ),
    DemoDecision(
        objective_title="Reach product-market fit in the SMB segment this quarter",
        event_type=DecisionEventType.KR_DESCOPE,
        summary="Removed the SOC 2 readiness KR — does not belong in a product OKR",
        chosen="Move SOC 2 readiness to the security team's OKR",
        tradeoff="Slightly less full-stack accountability under one OKR owner",
        alternatives=[
            DemoAlternative(
                option="Keep it as a dependency KR",
                reason_rejected=(
                    "Critic flagged it as fundamentally not a product team "
                    "outcome; ownership confusion would hurt both teams."
                ),
            ),
        ],
        evidence=[],
    ),
    DemoDecision(
        objective_title="Ship the v2 retention engine ahead of the renewals window",
        event_type=DecisionEventType.KR_REPLACE,
        summary="Replaced 'precision/recall' KR with 'CSM sign-off'",
        chosen="CSM sign-off as the third KR",
        tradeoff=(
            "Loses a quantitative KR in favour of a qualitative one. Accepted "
            "because the model already meets parity on validation; the real "
            "risk is operator adoption, not model quality."
        ),
        alternatives=[
            DemoAlternative(
                option="Original precision/recall KR",
                reason_rejected=(
                    "Reflector's last-quarter learning showed the team has "
                    "shipped technically excellent models that CSMs ignored — "
                    "metric was measuring the wrong thing."
                ),
            ),
        ],
        evidence=[
            DemoEvidence(
                source="Q1 reflector themes",
                claim="'Underestimated CSM adoption friction' theme cited 3 times",
            ),
        ],
        actor_email="sam@demo.cascade",
    ),
]


LEARNINGS: list[DemoLearning] = [
    DemoLearning(
        quarter="2026Q1",
        title="Underestimated CSM adoption friction on data products",
        description=(
            "Three Q1 OKRs shipped technically-correct ML or analytics work that "
            "the CSM team didn't end up using. In each case the engineering "
            "metric (precision, latency, coverage) was hit but the operator-"
            "adoption metric was not measured. We need to add a CSM-sign-off "
            "or daily-active-CSM KR to any data product OKR."
        ),
        category="alignment",
        occurrences=3,
    ),
    DemoLearning(
        quarter="2026Q1",
        title="Cross-team feature-store rollouts have been our largest schedule risk",
        description=(
            "Two of four Q1 OKRs slipped because they assumed feature-store "
            "availability that the data team hadn't committed to. Pattern: "
            "we plan against feature richness, the data team plans against "
            "ingestion stability. Aligner now flags any feature-store "
            "dependency for explicit cross-team negotiation before commit."
        ),
        category="estimation",
        occurrences=2,
    ),
    DemoLearning(
        quarter="2026Q1",
        title="5-week design-partner cadences are too short for enterprise insights",
        description=(
            "Q1 ran 3 partners at 5 weeks each. The first 2 weeks were process "
            "setup, the last week was wrap-up; only 2 of 5 weeks generated "
            "novel signal. Recommend 8-week minimum for the next enterprise "
            "engagement; revisit at Q3 partnership review."
        ),
        category="process",
        occurrences=2,
    ),
]


__all__ = [
    "DECISIONS",
    "DEMO_TEAM_NAME",
    "DEMO_TEAM_SLUG",
    "LEARNINGS",
    "OBJECTIVES",
    "USERS",
    "DemoAlternative",
    "DemoDecision",
    "DemoEvidence",
    "DemoKeyResult",
    "DemoLearning",
    "DemoObjective",
    "DemoUser",
]
