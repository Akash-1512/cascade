# Agents

cascade has six agents. Each is a node in the LangGraph state machine, with a typed
input contract and a typed output contract. None of them call each other directly — the
Supervisor router decides what runs next based on the shared `OKRState`.

## Shared state

```python
class OKRState(BaseModel):
    okr_id: UUID | None = None
    intent: str | None = None             # raw user input for new OKRs
    objective: Objective | None = None
    key_results: list[KeyResult] = []
    parent_okr_id: UUID | None = None     # for alignment

    conversation: list[Message] = []
    retrieved: RetrievedContext | None = None
    decisions_made: list[DecisionDraft] = []

    critique: CritiqueResult | None = None
    alignment: AlignmentResult | None = None
    risk: RiskAssessment | None = None

    awaiting_human: HumanInterrupt | None = None
    next_agent: AgentName | None = None
    trace_id: str
```

Every agent reads what it needs and writes only its scoped fields. State mutations are
deterministic — no agent peeks at fields owned by another.

## Drafter

**Purpose:** convert strategic intent into a well-formed Objective + KRs.

**Input:** `intent` (free text), optional `parent_okr_id`.

**Output:** `objective`, `key_results`.

**Prompt strategy:** few-shot with three exemplars (good O+KR, bad O+KR with critique,
fixed version). Temperature 0.2. JSON-mode output validated against the Pydantic schema.

**Why this matters:** the difference between "improve customer experience" and "raise
NPS from 32 to 45 by end of Q3 across the SMB segment" is the entire value of OKRs. The
Drafter does not produce the second on the first try — it produces a candidate that the
Critic shreds and the Drafter then revises.

## Critic

**Purpose:** evaluate a drafted OKR against four dimensions and a vague-language
classifier.

**Output:** `critique` with per-dimension scores and an overall verdict:

- `specificity` — is the Objective concrete enough to know whether you're working on it?
- `measurability` — are KRs quantified with explicit targets and timeframes?
- `ambition` — would a 0.7 score be a real stretch, or comfortably achievable?
- `alignment_hint` — does this plausibly ladder up to the parent? (Aligner does the rigorous check.)

**Prompt strategy:** structured output with chain-of-thought disabled — we want crisp
verdicts, not essays. Vague-language classifier is a separate small-model call against a
curated phrase list.

**Routing:** if overall < 0.7, loop to Drafter with the critique attached. Cap at 3
iterations; after that, escalate to HITL.

## Aligner

**Purpose:** check vertical alignment to parent OKR and horizontal conflicts with peer
OKRs.

**Input:** `objective`, `key_results`, `parent_okr_id`.

**Output:** `alignment` with a vertical score, a list of horizontal conflicts, and a
recommendation.

**How:** GraphRAG over the OKR tree. Retrieves the parent and siblings, then asks the
LLM to identify support, neutrality, or conflict. Conflicts are surfaced with the
specific KR text that conflicts and a one-sentence rationale.

**Why this is hard:** a SMB-segment NPS goal might conflict with an enterprise-segment
expansion goal in ways that aren't obvious from titles alone. The retrieval needs to
pull *content*, not just titles.

## Check-in Coach

**Purpose:** run weekly or biweekly progress conversations.

**Input:** `okr_id`, fresh `conversation` from the user.

**Output:** updated `key_results.progress`, a list of `decisions_made`, and a coaching
response.

**Behaviour:** asks for three things — current score, what changed since last check-in,
what's blocking. If the user mentions a decision (target change, descope, reframe), the
Coach captures it as a `DecisionDraft` for the user to confirm.

**HITL:** any target change triggers an interrupt. The user must explicitly confirm.

## Reflector

**Purpose:** quarterly retrospective; extract patterns and push them into organizational
memory.

**Input:** all OKRs and check-ins for the quarter.

**Output:** a retrospective document and a set of `OrganizationalLearning` rows persisted
to the memory layer.

**Behaviour:** clusters check-ins by theme (e.g., "underestimated dependency on data
team"), extracts patterns, and writes them as first-class memory entries linked back to
the source OKRs.

## Risk Sentinel

**Purpose:** velocity-based at-risk prediction with HITL intervention review.

**Input:** an OKR and its check-in history.

**Output:** `risk` with a probability of missing the target, top contributing factors, and
recommended interventions.

**Behaviour:** runs daily on a schedule. If risk crosses a configurable threshold (default
0.6), opens an HITL interrupt with the recommended interventions. The owner approves, modifies, or
dismisses.

**Why a separate agent:** isolating risk logic lets us swap in a more sophisticated
predictor (Bayesian, time-series) without disturbing the rest of the graph.

## Supervisor (router)

Not an agent — a deterministic router. Reads `next_agent` from state, falls through to
default routing rules. Pure function. Trivially testable.

## Human-in-the-loop interrupts

Three points trigger interrupts:

1. **OKR commit** — after Drafter+Critic+Aligner converge, before persisting
2. **Target reduction** — Check-in Coach captures a lowered target
3. **Risk intervention** — Risk Sentinel recommends action

Interrupts use LangGraph's `interrupt()` primitive. State is checkpointed in Postgres;
the graph resumes when the human responds via API or UI.
