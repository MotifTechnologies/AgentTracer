"""OpenAI-compatible chat client with a configurable reasoning field key.

Contains code from ArtificialAnalysis/Stirrup
(https://github.com/ArtificialAnalysis/Stirrup), licensed under the MIT
License — see the NOTICE file at the repository root. The ``generate``
implementation below adapts ``stirrup.clients.chat_completions_client``
(stirrup 0.2.0), which hardcodes the ``reasoning_content`` response field.
Reasoning field names differ per model/server (``reasoning_content``,
``reasoning``, ``thinking``, ...), so the key is a required constructor
argument here; the pinned stirrup version keeps this adaptation stable.
"""

from __future__ import annotations

from time import perf_counter
from typing import Any

from openai import BadRequestError
from stirrup import (
    AssistantBlock,
    AssistantMessage,
    ChatMessage,
    ContextOverflowError,
    OutputTokenLimitError,
    ReasoningBlock,
    TextBlock,
    TokenUsage,
    Tool,
    ToolCall,
)
from stirrup.clients import ChatCompletionsClient
from stirrup.clients.utils import to_openai_messages, to_openai_tools

# Sentinel for models that emit no reasoning channel at all.
NO_REASONING = "none"


class ReasoningKeyChatClient(ChatCompletionsClient):
    """ChatCompletionsClient that reads reasoning text from a configured key.

    ``reasoning_key`` is mandatory (fail-fast lives in config validation):
    a wrong or missing key would silently strip thinking from every generated
    trajectory. Pass ``"none"`` explicitly for non-reasoning models.
    """

    def __init__(self, *args: Any, reasoning_key: str, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if not reasoning_key:
            raise ValueError(
                "reasoning_key is required ('none' for non-reasoning models)"
            )
        self._reasoning_key = reasoning_key

    async def generate(
        self,
        messages: list[ChatMessage],
        tools: dict[str, Tool],
    ) -> AssistantMessage:
        request_kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": to_openai_messages(messages),
            "max_completion_tokens": self._max_tokens,
            **self._kwargs,
        }
        if tools:
            request_kwargs["tools"] = to_openai_tools(tools)
            request_kwargs["tool_choice"] = "auto"
        if self._reasoning_effort:
            request_kwargs["reasoning_effort"] = self._reasoning_effort

        request_start_time = perf_counter()
        try:
            response = await self._client.chat.completions.create(**request_kwargs)
        except BadRequestError as e:
            if e.code != "context_length_exceeded":
                raise
            raise ContextOverflowError(str(e)) from e
        request_end_time = perf_counter()

        choice = response.choices[0]
        if choice.finish_reason in ("max_tokens", "length"):
            raise OutputTokenLimitError(
                model_slug=self.model_slug,
                max_tokens=self._max_tokens,
                provider_reason=choice.finish_reason,
            )

        msg = choice.message
        blocks: list[AssistantBlock] = []

        if self._reasoning_key != NO_REASONING:
            reasoning_content = getattr(msg, self._reasoning_key, None)
            if reasoning_content is None and getattr(msg, "model_extra", None):
                reasoning_content = msg.model_extra.get(self._reasoning_key)
            if reasoning_content:
                blocks.append(ReasoningBlock(content=reasoning_content))

        if msg.content:
            blocks.append(TextBlock(text=msg.content))

        blocks.extend(
            ToolCall.from_provider(
                provider_id=tc.id,
                name=tc.function.name,
                arguments=tc.function.arguments or "",
            )
            for tc in (msg.tool_calls or [])
        )

        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0
        reasoning_tokens = 0
        if usage and getattr(usage, "completion_tokens_details", None):
            reasoning_tokens = (
                getattr(usage.completion_tokens_details, "reasoning_tokens", 0) or 0
            )

        return AssistantMessage(
            blocks=blocks,
            token_usage=TokenUsage(
                input=input_tokens,
                answer=output_tokens - reasoning_tokens,
                reasoning=reasoning_tokens,
            ),
            request_start_time=request_start_time,
            request_end_time=request_end_time,
        )
