# cascade.agents

Six agents that coach OKR owners through drafting, alignment, weekly check-ins,
quarterly retrospectives, and risk reviews. Plus the shared contracts that
every agent and the orchestrator use as their type-safe communication surface.

## What each agent does

| Agent | Purpose | Trigger | Output |
|---|---|---|---|
| **Drafter** | Convert intent into a well-formed Objective + KRs | LangGraph Drafter→Critic→Aligner loop | `ProposedObjective` |
| **Critic** | Score drafts on specificity, measurability, ambition, structure | Same loop as Drafter | `CritiqueResult` with verdict |
| **Aligner** | Vertical alignment to parent + horizontal conflict detection | After a passing critique | `AlignmentResult` with typed conflicts |
| **Check-in Coach** | Turn free-text owner messages into structured updates | Cadence (weekly) | `CoachResponse` with updates + coaching message |
| **Reflector** | Quarterly retrospective — themes, wins, losses, recommendations | Quarter close | `ReflectionResult` with categorised themes |
| **Risk Sentinel** | Velocity-based at-risk prediction with interventions | Scheduled | `RiskAssessment` with `requires_intervention` flag |

The Drafter, Critic, and Aligner participate in the same LangGraph state machine.
The Check-in Coach, Reflector, and Risk Sentinel run on independent triggers —
they share contracts and state types but not the entry path.

## Files

```
agents/
├── __init__.py        Public API
├── contracts.py       Pydantic types every agent emits/consumes
├── llm.py             Chat-model factory with retry + fallback;
│                      FakeChatModel for hermetic tests
├── drafter.py         Drafter agent + memory-aware revision support
├── critic.py          Critic agent with deterministic verdict normalisation
├── aligner.py         Aligner agent with verdict normalisation
├── checkin_coach.py   Check-in Coach with forced-confirmation on target changes
├── reflector.py       Reflector with check-in-by-OKR grouping
├── risk_sentinel.py   Risk Sentinel with intervention threshold normalisation
└── prompts/           Jinja2 templates per agent
    ├── __init__.py
    ├── drafter.j2
    ├── critic.j2
    ├── aligner.j2
    ├── checkin_coach.j2
    ├── reflector.j2
    └── risk_sentinel.j2
```

## Verdict normalisation

The Critic, Aligner, and Risk Sentinel all override the LLM's verdict when
dimension scores or other signals contradict it. This makes the gates
deterministic regardless of LLM variance.

**Critic:** any dimension below 0.7 forces `needs_revision`; below 0.4 forces
`reject`.

**Aligner:** any blocking conflict OR vertical_score < 0.4 forces `blocked`.
Any warning conflict OR vertical_score < 0.7 forces `needs_review`.

**Risk Sentinel:** `requires_intervention` is forced True when score > 0.5 OR
velocity is `stalled`.

## The contracts module

`contracts.py` is the type-safe surface every agent shares. Each agent's output
is a Pydantic model with `extra="forbid"`, so a malformed LLM response fails
validation immediately rather than propagating bad state into the orchestrator.

Notable types:

- **`ProposedObjective`** — what the Drafter emits
- **`CritiqueResult`** — what the Critic emits, includes per-dimension scores
- **`AlignmentResult`** — vertical score + typed conflicts
- **`CoachResponse`** — structured updates + coaching message + follow-ups
- **`ReflectionResult`** — categorised themes + wins + losses + recommendations
- **`RiskAssessment`** — risk score + velocity + factors + interventions
- **`HumanInterrupt`** — escalation marker with reason and payload

## How the Drafter uses memory

The Drafter optionally accepts a `ContextBuilder`. When wired in, the prompt
template renders a "Relevant memory" section listing recent decisions on the
OKR with their tradeoffs, plus the top retrieved transcript chunks.

```python
proposal = await draft_objective(
    intent="Reach PMF in SMB",
    model=model,
    context_builder=builder,  # optional — wires in causal + conversational memory
    okr_id=existing_okr.id,   # for revisions of an existing Objective
    team_id=team.id,
    quarter="2026Q2",
)
```

This closes the loop on revisions: the Drafter sees what alternatives were
already considered and rejected, what tradeoff the team previously accepted,
and the prior Critic suggestions.

## Testing

Every agent has a unit test file in `tests/unit/test_<agent>.py`. The tests use
`FakeChatModel` to feed deterministic canned responses through the structured
output path, then assert on the parsed result.

The Drafter additionally has `tests/unit/test_drafter_with_memory.py` covering
the `ContextBuilder` integration.

## Adding an agent

1. Add a contract type to `contracts.py` (Pydantic model, `extra="forbid"`)
2. Add a Jinja prompt template to `prompts/<name>.j2`
3. Implement the async function in `<name>.py` following the pattern:
   - Accept `model: BaseChatModel` and any context arguments
   - Render the prompt
   - Try `with_structured_output`; fall back to raw JSON parse
   - Apply any verdict / threshold normalisation
   - Return the contract type
4. Add unit tests in `tests/unit/test_<name>.py`
5. Wire into the orchestrator graph if it participates in the Drafter loop;
   otherwise add a trigger entry point

## See also

- [Architecture: agents](../../docs/architecture/agents.md)
- [Architecture: memory](../../docs/architecture/memory.md)
- [Orchestrator](../orchestrator/README.md)
