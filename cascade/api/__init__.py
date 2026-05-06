"""cascade REST API.

Read-side projection over the OKR state, decisions, and organizational
learnings. Mutations flow through :mod:`cascade.mcp` because that's where the
agent loop lives.

Run locally::

    uvicorn cascade.api.main:app --reload --host 0.0.0.0 --port 8000

OpenAPI docs at ``/docs``.
"""
