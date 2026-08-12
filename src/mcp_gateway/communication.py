from langchain_core.tools import tool

from src.external_providers import telegram_bot_api, whatsapp_api
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
    """Reports WhatsApp API direct-provider status; message send uses direct API after HITL approval."""
    return whatsapp_api.read_status(limit=limit).to_text("WhatsApp API")


@tool
def whatsapp_send(recipient: str, message: str) -> str:
    """Sends WhatsApp messages through the direct WhatsApp API. Requires HITL approval by policy."""
    return whatsapp_api.send_message(recipient=recipient, message=message).to_text("WhatsApp API")


@tool
def telegram_read(limit: int = 5) -> str:
    """Reports Telegram Bot API direct-provider status; sends use direct API after HITL approval."""
    return telegram_bot_api.read_status(limit=limit).to_text("Telegram Bot API")


@tool
def telegram_send(chat_id: str, text: str) -> str:
    """Sends Telegram messages through the direct Telegram Bot API. Requires HITL approval by policy."""
    return telegram_bot_api.send_message(chat_id=chat_id, text=text).to_text("Telegram Bot API")
