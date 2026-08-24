from langchain_core.tools import tool

from src.external_providers import telegram_bot_api, whatsapp_api
from src.tools import mcp_invocation
from src.tools.mcp_invocation import MCPInvocationStatus


def _gmail_message_args(to: str, subject: str, body: str):
    recipients = [to] if isinstance(to, str) else to
    return {"to": recipients, "subject": subject, "body": body}


def _invoke(provider_id, hints, args, label):
    result = mcp_invocation.invoke_provider_tool(
        provider_ids=(provider_id,),
        tool_hints=hints,
        arguments=args,
    )
    return result.to_text(label)


@tool
def email_read(limit: int = 5) -> str:
    """Reads recent Gmail Inbox messages through Gmail MCP. Use email_search for Sent or other queries."""
    return _invoke("gmail", ("read", "list", "messages"), {"limit": limit}, "Gmail MCP")


@tool
def email_search(query: str) -> str:
    """Searches Gmail through Gmail MCP only."""
    return _invoke("gmail", ("search", "query", "messages"), {"query": query}, "Gmail MCP")


@tool
def email_draft(to: str, subject: str, body: str) -> str:
    """Create a Gmail draft through the connected Gmail MCP provider.

    Always call this tool when the user asks to draft, compose, or write an email.
    Do not give Gmail website instructions instead of calling this tool.
    Arguments: to (recipient email), subject, body.
    """
    return _invoke("gmail", ("draft", "create_draft"), _gmail_message_args(to, subject, body), "Gmail MCP")


@tool
def email_send(to: str, subject: str, body: str, draft_id: str = "") -> str:
    """Send Gmail through Gmail MCP after HITL approval.

    Use this only when the user explicitly asks to send. For drafts, call email_draft instead.
    After creating a draft, copy the exact to/subject/body from that draft tool result.
    Never invent placeholder addresses such as name@example.com.
    If a Gmail draft id is known, pass draft_id so the existing draft is sent.
    Falls back to creating a draft if send is not exposed by the provider.
    """
    args = _gmail_message_args(to, subject, body)
    if str(draft_id or "").strip():
        args["draft_id"] = str(draft_id).strip()
    result = mcp_invocation.invoke_provider_tool(
        provider_ids=("gmail",),
        tool_hints=("send", "send_message"),
        arguments=args,
    )
    if result.status != MCPInvocationStatus.TOOL_UNAVAILABLE:
        return result.to_text("Gmail MCP")
    draft = mcp_invocation.invoke_provider_tool(
        provider_ids=("gmail",),
        tool_hints=("draft", "create_draft"),
        arguments=args,
    )
    if draft.ok:
        return f"{draft.to_text('Gmail MCP')} Gmail MCP created a draft because send is not exposed by the configured provider."
    return draft.to_text("Gmail MCP")


@tool
def whatsapp_read(limit: int = 5) -> str:
    """Reads recent WhatsApp messages from the local inbox (webhook-backed Cloud API)."""
    return whatsapp_api.read_messages(limit=limit).to_text("WhatsApp API")


@tool
def whatsapp_send(recipient: str, message: str) -> str:
    """Sends WhatsApp messages through the direct WhatsApp API. Requires HITL approval by policy."""
    return whatsapp_api.send_message(recipient=recipient, message=message).to_text("WhatsApp API")


@tool
def telegram_read(limit: int = 5) -> str:
    """Reads recent Telegram bot updates via getUpdates and the local message store."""
    return telegram_bot_api.read_messages(limit=limit).to_text("Telegram Bot API")


@tool
def telegram_send(chat_id: str, text: str) -> str:
    """Sends Telegram messages through the direct Telegram Bot API. Requires HITL approval by policy."""
    return telegram_bot_api.send_message(chat_id=chat_id, text=text).to_text("Telegram Bot API")
