"""LLM provider abstraction.

Wraps the chat models behind a single function so agents do not import provider SDKs
directly. Provides:

- Primary provider (Groq, LLaMA 3.3 70B) with retry on transient failures
- Fallback provider (Together AI) used when Groq is rate-limited or unavailable
- A test fake that returns deterministic outputs for unit tests

Returning a ``BaseChatModel`` keeps callers compatible with LangChain's
``with_structured_output`` and tracing decorators.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable

from cascade.config import Settings, get_settings


def get_chat_model(settings: Settings | None = None) -> BaseChatModel:
    """Return a chat model configured from settings, with retry and fallback.

    The returned object is a LangChain :class:`Runnable` — it composes cleanly with
    ``with_structured_output``, ``with_retry``, and tracing.
    """
    cfg = settings or get_settings()

    if cfg.groq_api_key is None:
        raise RuntimeError(
            "GROQ_API_KEY is not set. Configure it in .env or environment, "
            "or use FakeChatModel for tests."
        )

    # Imported lazily so tests that patch the LLM don't pay the import cost.
    from langchain_groq import ChatGroq

    primary = ChatGroq(
        api_key=cfg.groq_api_key,
        model=cfg.groq_model,
        temperature=0.2,
        max_retries=0,  # we drive retry ourselves so we can fall back cleanly
    )

    primary_with_retry = primary.with_retry(
        stop_after_attempt=3,
        wait_exponential_jitter=True,
    )

    if cfg.together_api_key is None:
        return primary_with_retry  # type: ignore[return-value]

    # Together AI exposes an OpenAI-compatible API; we use ChatOpenAI configured
    # against their endpoint to avoid pulling in another provider package.
    from langchain_openai import ChatOpenAI

    fallback = ChatOpenAI(
        api_key=cfg.together_api_key,  # type: ignore[arg-type]
        base_url="https://api.together.xyz/v1",
        model=cfg.together_model,
        temperature=0.2,
    )

    return primary_with_retry.with_fallbacks([fallback])  # type: ignore[return-value]


class FakeChatModel(BaseChatModel):
    """Deterministic chat model for tests.

    Returns the responses configured at construction time. When ``responses`` is
    exhausted, raises :class:`RuntimeError` so tests fail loudly instead of hanging
    on an unexpected extra call.
    """

    responses: list[str]
    call_log: list[list[Any]]

    def __init__(self, responses: list[str]) -> None:
        # Pydantic v1 / v2 BaseChatModel still uses model_config_validator semantics;
        # set fields explicitly via __dict__ to bypass.
        super().__init__(responses=list(responses), call_log=[])  # type: ignore[call-arg]

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _generate(  # type: ignore[override]
        self,
        messages: list[Any],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Any:
        from langchain_core.outputs import ChatGeneration, ChatResult

        if not self.responses:
            raise RuntimeError("FakeChatModel exhausted: no more configured responses")
        self.call_log.append(messages)
        text = self.responses.pop(0)
        message = AIMessage(content=text)
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(  # type: ignore[override]
        self,
        messages: list[Any],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Any:
        return self._generate(messages, stop, run_manager, **kwargs)


def with_structured_output(
    model: BaseChatModel,
    schema: type,
) -> Runnable[Any, Any]:
    """Configure a model to return a Pydantic instance.

    Single chokepoint so we can swap parser strategies (function calling, JSON
    mode, regex fallback) without touching agent code.
    """
    return model.with_structured_output(schema, method="json_mode")
