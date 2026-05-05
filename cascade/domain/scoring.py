"""OKR scoring functions.

All scoring is pure and deterministic. Functions take a :class:`KeyResult` (or its
fields) and return a score in ``[0.0, 1.0]``. Google's OKR convention is that a 0.7
score is the goal — full 1.0 is reserved for genuine stretch outcomes.

The functions here intentionally do not round, format, or compose. Callers decide how
to display a score.
"""

from __future__ import annotations

from cascade.domain.enums import MetricType


def score_linear(baseline: float, current: float, target: float) -> float:
    """Score progress between ``baseline`` and ``target`` linearly.

    ``baseline`` is the starting value, ``target`` is the goal. ``current`` is the
    most recent measurement. The return value is clamped to ``[0.0, 1.0]``.

    The function handles both increasing targets (``target > baseline``) and
    decreasing targets (``target < baseline`` — e.g., reduce churn from 8% to 4%) by
    reversing the direction of progress.

    A ``baseline == target`` is treated as a binary check: ``current >= target`` is
    ``1.0``, otherwise ``0.0``. This avoids division-by-zero and matches author
    intent for KRs phrased as "maintain X".

    Examples:
        >>> score_linear(baseline=0, current=70, target=100)
        0.7
        >>> score_linear(baseline=8, current=6, target=4)
        0.5
        >>> score_linear(baseline=100, current=120, target=100)
        1.0
    """
    if baseline == target:
        return 1.0 if current >= target else 0.0
    progress = (current - baseline) / (target - baseline)
    return max(0.0, min(1.0, progress))


def score_boolean(achieved: bool) -> float:
    """Return ``1.0`` if achieved, ``0.0`` otherwise."""
    return 1.0 if achieved else 0.0


def score_milestone(milestones_completed: int, milestones_total: int) -> float:
    """Score as the fraction of milestones reached.

    Raises:
        ValueError: if ``milestones_total`` is zero or negative, or
            ``milestones_completed`` is outside ``[0, milestones_total]``.
    """
    if milestones_total <= 0:
        raise ValueError("milestones_total must be positive")
    if milestones_completed < 0 or milestones_completed > milestones_total:
        raise ValueError("milestones_completed must be within [0, milestones_total]")
    return milestones_completed / milestones_total


def score_key_result(
    metric_type: MetricType,
    baseline: float,
    current: float,
    target: float,
) -> float:
    """Dispatch to the appropriate scoring function based on metric type.

    For ``MILESTONE`` metrics, ``current`` is the count of completed milestones and
    ``target`` is the total — :func:`score_milestone` is used.

    For ``BOOLEAN`` metrics, ``current >= target`` collapses to a true/false check via
    :func:`score_boolean`.

    Other metric types fall through to :func:`score_linear`.
    """
    if metric_type == MetricType.MILESTONE:
        return score_milestone(int(current), int(target))
    if metric_type == MetricType.BOOLEAN:
        return score_boolean(current >= target)
    return score_linear(baseline, current, target)


def score_objective(key_result_scores: list[tuple[float, float]]) -> float:
    """Aggregate a list of ``(weight, score)`` pairs into an Objective score.

    Weights are normalised before aggregation, so they do not need to sum to 1.0.
    An empty input returns ``0.0`` — an Objective with no scored KRs is unscored, not
    a failure.

    Examples:
        >>> score_objective([(1.0, 0.7), (1.0, 0.5), (1.0, 0.9)])
        0.7
        >>> score_objective([(2.0, 1.0), (1.0, 0.0)])
        0.6666666666666666
        >>> score_objective([])
        0.0
    """
    if not key_result_scores:
        return 0.0
    total_weight = sum(w for w, _ in key_result_scores)
    if total_weight == 0:
        return 0.0
    return sum(w * s for w, s in key_result_scores) / total_weight
