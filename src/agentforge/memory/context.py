"""Short-term (execution) memory: keeping the conversation within budget.

Old tool outputs dominate context growth in agent loops. Beyond the most
recent ``keep_recent`` messages, large tool results are replaced with a short
placeholder. Message structure (tool_use / tool_result pairing) is preserved,
which every provider API requires.
"""

from __future__ import annotations

from agentforge.llm.types import ContentPart, Message, ToolResultPart

ELIDE_THRESHOLD = 800


def compact_history(messages: list[Message], keep_recent: int) -> list[Message]:
    if len(messages) <= keep_recent:
        return messages
    cutoff = len(messages) - keep_recent
    compacted: list[Message] = []
    for index, message in enumerate(messages):
        if index == 0 or index >= cutoff:
            compacted.append(message)
            continue
        parts: list[ContentPart] = []
        changed = False
        for part in message.content:
            if isinstance(part, ToolResultPart) and len(part.content) > ELIDE_THRESHOLD:
                preview = part.content[:200].rstrip()
                parts.append(
                    ToolResultPart(
                        tool_use_id=part.tool_use_id,
                        content=f"{preview}\n[earlier output elided: {len(part.content)} chars]",
                        is_error=part.is_error,
                    )
                )
                changed = True
            else:
                parts.append(part)
        compacted.append(Message(role=message.role, content=parts) if changed else message)
    return compacted
