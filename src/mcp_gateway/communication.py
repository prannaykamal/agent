from langchain_core.tools import tool

from src.tools import mcp_invocation


def _invoke(provider_id, hints, args, label):
    result = mcp_invocation.invoke_provider_tool(
        provider_ids=(provider_id,),
        tool_hints=hints,
        arguments=args,
    )
    return result.to_text(label)


@tool
def email_read(limit: int = 5) -> str:
    """Reads recent Gmail messages through Gmail MCP only."""
    return _invoke("gmail", ("read", "list", "messages"), {"limit": limit}, "Gmail MCP")


@tool
def email_search(query: str) -> str:
    """Searches Gmail through Gmail MCP only."""
    return _invoke("gmail", ("search", "query", "messages"), {"query": query}, "Gmail MCP")


@tool
def email_draft(to: str, subject: str, body: str) -> str:
    """Creates a Gmail draft through Gmail MCP only, if provider exposes drafting."""
    return _invoke("gmail", ("draft", "create_draft"), {"to": to, "subject": subject, "body": body}, "Gmail MCP")


@tool
def email_send(to: str, subject: str, body: str) -> str:
    """Sends Gmail through Gmail MCP only. Requires HITL approval by policy."""
    return _invoke("gmail", ("send", "send_message"), {"to": to, "subject": subject, "body": body}, "Gmail MCP")


@tool
def whatsapp_read(limit: int = 5) -> str:
    """Reads WhatsApp messages through WhatsApp MCP only."""
    return _invoke("whatsapp", ("read", "list", "messages"), {"limit": limit}, "WhatsApp MCP")


@tool
def whatsapp_send(recipient: str, message: str) -> str:
    """Sends WhatsApp messages through WhatsApp MCP only. Requires HITL approval by policy."""
    return _invoke("whatsapp", ("send", "send_message"), {"recipient": recipient, "message": message}, "WhatsApp MCP")


@tool
def telegram_read(limit: int = 5) -> str:
    """Reads Telegram messages through Telegram MCP only."""
    return _invoke("telegram", ("read", "list", "messages"), {"limit": limit}, "Telegram MCP")


@tool
def telegram_send(chat_id: str, text: str) -> str:
    """Sends Telegram messages through Telegram MCP only. Requires HITL approval by policy."""
    return _invoke("telegram", ("send", "send_message"), {"chat_id": chat_id, "text": text}, "Telegram MCP")
