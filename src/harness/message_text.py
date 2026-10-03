"""Plain text from LangChain message content.

Some providers (Gemini 3, Anthropic) return ``AIMessage.content`` as a list of
content blocks, e.g. ``[{"type": "text", "text": "pong", "extras": {"signature": ...}}]``.
The message object must stay intact in graph state (Gemini needs the thought
signatures on follow-up tool calls), but anything shown to the user, stored as a
chat turn, or written to memory must use only the text blocks.
"""

from typing import Any


def content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type", "text") == "text" and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "".join(parts)
    return str(content)


def message_text(message: Any) -> str:
    return content_text(getattr(message, "content", message))
