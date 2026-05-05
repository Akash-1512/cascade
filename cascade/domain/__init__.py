"""cascade domain models.

This package contains the value objects, enums, and pure functions that describe what
an OKR *is*. It has no dependencies on storage, agents, or the API — those layers
import *from* here, never the other way around.
"""

from cascade.domain.checkin import CheckIn, CheckInCreate
from cascade.domain.decision import (
    Alternative,
    Decision,
    DecisionCreate,
    Evidence,
)
from cascade.domain.enums import (
    CheckInConfidence,
    DecisionEventType,
    KeyResultStatus,
    MetricType,
    ObjectiveStatus,
    UserRole,
)
from cascade.domain.identity import Team, TeamCreate, User, UserCreate
from cascade.domain.okr import (
    KeyResult,
    KeyResultCreate,
    Objective,
    ObjectiveCreate,
    Quarter,
)
from cascade.domain.scoring import (
    score_boolean,
    score_key_result,
    score_linear,
    score_milestone,
    score_objective,
)

__all__ = [
    "Alternative",
    "CheckIn",
    "CheckInConfidence",
    "CheckInCreate",
    "Decision",
    "DecisionCreate",
    "DecisionEventType",
    "Evidence",
    "KeyResult",
    "KeyResultCreate",
    "KeyResultStatus",
    "MetricType",
    "Objective",
    "ObjectiveCreate",
    "ObjectiveStatus",
    "Quarter",
    "Team",
    "TeamCreate",
    "User",
    "UserCreate",
    "UserRole",
    "score_boolean",
    "score_key_result",
    "score_linear",
    "score_milestone",
    "score_objective",
]
