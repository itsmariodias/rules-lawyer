"""The LangGraph tool-calling agent.  History is in the checkpointer."""

from __future__ import annotations

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, ToolCallLimitMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AnyMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.base import BaseCheckpointSaver

from rules_lawyer.chat.agent.prompts import prompt
from rules_lawyer.chat.agent.tools import TOOLS
from rules_lawyer.chat.retrieval import cypher
from rules_lawyer.config import get_settings

SYSTEM_PROMPT = prompt("system")


# Every tool result opens with the ``[id] Heading (type, p.N)`` of what it
# read, which this keeps along with a line or two of the text.
EARLIER_LOOKUP_CHARS = 300


def with_earlier_lookups_cut(messages: list[AnyMessage]) -> list[AnyMessage]:
    """The conversation as the model is sent it: earlier turns' tool results cut
    to ``EARLIER_LOOKUP_CHARS``, the current turn whole.

    Args:
        messages: The thread's messages, oldest first.

    Returns:
        The same messages, with each tool result before the last question
        cut at a word boundary and marked as cut.
    """
    questions = [index for index, message in enumerate(messages)
                 if isinstance(message, HumanMessage)]
    if not questions:
        return messages
    current = questions[-1]
    earlier = []
    for message in messages[:current]:
        if (isinstance(message, ToolMessage)
                and len(str(message.content)) > EARLIER_LOOKUP_CHARS):
            cut = str(message.content)[:EARLIER_LOOKUP_CHARS].rsplit(" ", 1)[0]
            message = message.model_copy(update={
                "content": f"{cut} … (cut: an earlier turn's lookup)"})
        earlier.append(message)
    return earlier + messages[current:]


class CutEarlierLookups(AgentMiddleware):
    """Applies ``with_earlier_lookups_cut`` to each model call.

    The request is changed, not the state, so the checkpointer still stores
    every lookup whole for the trace and ``/lookups``.
    """

    def wrap_model_call(self, request, handler):
        """Call the model on the cut conversation."""
        return handler(request.override(
            messages=with_earlier_lookups_cut(request.messages)))

    async def awrap_model_call(self, request, handler):
        """Call the model on the cut conversation."""
        return await handler(request.override(
            messages=with_earlier_lookups_cut(request.messages)))


class LookupBudget(ToolCallLimitMiddleware):
    """``ToolCallLimitMiddleware`` whose refused calls say why in the trace.

    The library marks a call past the limit ``status="error"``, which the
    trace would show as a failed lookup; the artifact gives it its own status.
    """

    def after_model(self, state, runtime):
        """Count the model's tool calls, refusing those past the limit."""
        update = super().after_model(state, runtime)
        for message in (update or {}).get("messages", []):
            if isinstance(message, ToolMessage):
                message.artifact = {"status": "skipped",
                                    "summary": "max tool calls reached"}
        return update


def system_prompt() -> str:
    """``system.md`` plus the derived graph schema.

    If the graph is unreachable the schema is omitted rather than failing the
    agent build; the tools then report the outage themselves.

    Returns:
        The full system prompt.
    """
    try:
        return f"{SYSTEM_PROMPT}\n\n{cypher.schema()}"
    except Exception:  # noqa: BLE001 - any of the driver's connection failures
        return SYSTEM_PROMPT


def build_agent(model: BaseChatModel,
                checkpointer: BaseCheckpointSaver | None = None):
    """Compile the agent for one turn, with the current system prompt.

    Compiled per turn, not cached: it costs about 2ms, and the prompt then
    gains the graph schema as soon as the graph is reachable.

    Args:
        model: The chat model that answers.
        checkpointer: Where conversation state is stored.

    Returns:
        A compiled LangGraph agent.
    """
    return create_agent(
        model=model,
        tools=TOOLS,
        system_prompt=system_prompt(),
        middleware=[
            CutEarlierLookups(),
            # A run is one question (a retry too).  "continue" answers calls
            # past the limit with an error the model reads, so it answers
            # from what it has; "end" would replace the answer with a notice.
            LookupBudget(
                run_limit=get_settings().chat.max_tool_calls,
                exit_behavior="continue"),
        ],
        checkpointer=checkpointer,
    )
