# ADR-0001: LangGraph as the agent orchestration framework

- **Status:** Accepted
- **Date:** 2026-05-05
- **Deciders:** @Akash-1512

## Context

cascade runs a multi-stage workflow over OKRs: drafting, critiquing, aligning, checking in,
reflecting, and risk-monitoring. Each stage has its own prompt strategy, its own retrieval
needs, and its own success criteria. The stages are not strictly linear — a Critic may
loop back to the Drafter; a Risk Sentinel can interrupt mid-flow and demand human input.

We need an orchestration layer that:

1. Models conditional, cyclic graphs — not just DAGs
2. Persists state durably so HITL pauses can resume hours or days later
3. Exposes tracing hooks for observability
4. Supports streaming partial outputs to the UI
5. Has stable public APIs and active maintenance

## Decision

Use **LangGraph** as the orchestration framework.

State is held in a typed `OKRState` Pydantic model. Nodes are agent functions. Edges are
either deterministic (after Drafter, always go to Critic) or conditional (after Critic,
route based on score). The Supervisor is a router node, not a meta-agent — keeping it
deterministic gives us predictable test surface area.

Persistence uses LangGraph's `PostgresSaver` against the same Postgres instance that holds
the domain data. This keeps the operational footprint to a single database.

## Consequences

### Positive

- Cyclic graphs and HITL interrupts are first-class, not patched on
- LangSmith integration is built-in; agent traces are free
- Streaming is supported end-to-end (state updates → API → UI)
- `PostgresSaver` removes the need for Redis or a custom checkpointer

### Negative

- LangGraph is younger than LangChain and the API has shifted minor versions twice in the
  past year. We pin to a known-good minor and re-evaluate per release.
- The mental model (state, nodes, edges, channels) has a learning curve for contributors
  used to plain function chains.

### Neutral

- We are tied to the LangChain ecosystem for messages, tools, and prompts. This is
  acceptable given the breadth of integrations.

## Alternatives considered

- **PydanticAI** — clean Pydantic-native API, but no first-class graph or HITL primitives
  at the time of writing. Considered for individual agent internals; not for orchestration.
- **AutoGen (v0.4)** — multi-agent conversation patterns are good but deterministic routing
  and persistent HITL interrupts are awkward to express.
- **Custom state machine** — minimum viable, but rebuilding tracing, persistence, and
  streaming would consume disproportionate effort for no differentiation.
- **CrewAI** — opinionated toward role-playing agents; less suited to a workflow with
  hard contracts between stages.

## References

- LangGraph docs: https://langchain-ai.github.io/langgraph/
- ETH Zurich finding on monolithic context injection: see `docs/architecture/memory.md`
