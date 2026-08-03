import uuid
from typing import List, Dict, Any
from langchain_core.tools import tool
from src.db import get_connection
from src.mcp_gateway.email_adapters import SMTPEmailAdapter, IMAPEmailAdapter

# --- Email MCP Tools ---

@tool
def email_read(limit: int = 5) -> str:
    """Reads recent incoming email messages using IMAP or local SQLite emails table."""
    adapter = IMAPEmailAdapter()
    rows = adapter.fetch_recent_emails(limit=limit)

    if not rows:
        return f"[Email MCP] Inbox empty. No emails found."

    email_list = [f"- ID: {r['id']} | From: {r['sender']} | Subject: '{r['subject']}' [{r.get('folder', 'inbox').upper()}]" for r in rows]
    return f"[Email MCP] Top {len(rows)} emails:\n" + "\n".join(email_list)

@tool
def email_search(query: str) -> str:
    """Searches email inbox for a keyword or sender in SQLite emails table."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, sender, recipient, subject, body, folder
        FROM emails
        WHERE subject LIKE ? OR body LIKE ? OR sender LIKE ?
        ORDER BY created_at DESC
        LIMIT 5
        """,
        (f"%{query}%", f"%{query}%", f"%{query}%")
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return f"[Email MCP] Search results for '{query}': No matching emails found."

    email_list = [f"- ID: {r['id']} | From: {r['sender']} | Subject: '{r['subject']}'" for r in rows]
    return f"[Email MCP] Search results for '{query}':\n" + "\n".join(email_list)

@tool
def email_draft(to: str, subject: str, body: str) -> str:
    """Drafts an email message and saves it to SQLite emails table with folder='draft'."""
    msg_id = f"email_{uuid.uuid4().hex[:8]}"
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO emails (id, sender, recipient, subject, body, folder, status, created_at)
        VALUES (?, 'user@assistant.local', ?, ?, ?, 'draft', 'DRAFT', datetime('now'))
        """,
        (msg_id, to, subject, body)
    )
    conn.commit()
    conn.close()

    return f"[Email MCP - Draft Saved] Draft ID {msg_id} saved to drafts. To: {to} | Subject: '{subject}'."


@tool
def email_send(to: str, subject: str, body: str) -> str:
    """
    Sends an email to an external recipient via SMTP (or local SQLite) and stores it in SQLite emails table with folder='sent'.
    HIGH RISK OPERATION: Requires Human-In-The-Loop approval.
    """
    adapter = SMTPEmailAdapter()
    smtp_res = adapter.send_email(to_addr=to, subject=subject, body=body)

    msg_id = f"email_{uuid.uuid4().hex[:8]}"
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO emails (id, sender, recipient, subject, body, folder, status, created_at)
        VALUES (?, ?, ?, ?, ?, 'sent', 'SENT', datetime('now'))
        """,
        (msg_id, smtp_res.get("from", "user@assistant.local"), to, subject, body)
    )
    conn.commit()
    conn.close()

    mode = smtp_res.get("mode", "LOCAL_SQLITE")
    return f"[Email MCP - SENT ({mode})] Successfully sent email {msg_id} to {to} with subject '{subject}'."

# --- WhatsApp MCP Tools ---

@tool
def whatsapp_read(limit: int = 5) -> str:
    """Reads recent WhatsApp messages from local SQLite whatsapp_messages table."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, sender, recipient, message, status, created_at
        FROM whatsapp_messages
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,)
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return f"[WhatsApp MCP (Local SQLite Storage)] No WhatsApp messages found."

    msg_list = [f"- [{r['created_at']}] {r['sender']} -> {r['recipient']}: '{r['message']}'" for r in rows]
    return f"[WhatsApp MCP (Local SQLite Storage)] Top {len(rows)} messages:\n" + "\n".join(msg_list)

@tool
def whatsapp_send(recipient: str, message: str) -> str:
    """
    Sends a WhatsApp message via WhatsApp Cloud API (if configured) or logs to local SQLite table.
    HIGH RISK OPERATION: Requires Human-In-The-Loop approval.
    """
    import os, urllib.request, json
    token = os.getenv("WHATSAPP_API_TOKEN")
    phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")

    api_sent = False
    if token and phone_id:
        try:
            url = f"https://graph.facebook.com/v18.0/{phone_id}/messages"
            payload = json.dumps({
                "messaging_product": "whatsapp",
                "to": recipient,
                "type": "text",
                "text": {"body": message}
            }).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    api_sent = True
        except Exception:
            pass

    msg_id = f"wa_{uuid.uuid4().hex[:8]}"
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO whatsapp_messages (id, sender, recipient, message, status, created_at)
        VALUES (?, 'me', ?, ?, ?, datetime('now'))
        """,
        (msg_id, recipient, message, "SENT_REAL" if api_sent else "LOCAL_SENT")
    )
    conn.commit()
    conn.close()

    mode_tag = "LIVE_API" if api_sent else "Local SQLite Storage"
    return f"[WhatsApp MCP ({mode_tag}) - SENT] Message {msg_id} logged to local storage for {recipient}: '{message}'"

# --- Telegram MCP Tools ---

@tool
def telegram_read(limit: int = 5) -> str:
    """Reads recent Telegram chat messages from local SQLite telegram_messages table."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, chat_id, message, status, created_at
        FROM telegram_messages
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,)
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return f"[Telegram MCP (Local SQLite Storage)] No Telegram messages found."

    msg_list = [f"- [{r['created_at']}] Chat {r['chat_id']}: '{r['message']}'" for r in rows]
    return f"[Telegram MCP (Local SQLite Storage)] Top {len(rows)} messages:\n" + "\n".join(msg_list)

@tool
def telegram_send(chat_id: str, text: str) -> str:
    """
    Sends a message to a Telegram chat using Telegram Bot API (if TELEGRAM_BOT_TOKEN is set) or logs to local SQLite table.
    HIGH RISK OPERATION: Requires Human-In-The-Loop approval.
    """
    import os, urllib.request, json
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    api_sent = False

    if bot_token and not bot_token.startswith("your_"):
        try:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = json.dumps({
                "chat_id": chat_id,
                "text": text
            }).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    api_sent = True
        except Exception:
            pass

    msg_id = f"tg_{uuid.uuid4().hex[:8]}"
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO telegram_messages (id, chat_id, message, status, created_at)
        VALUES (?, ?, ?, ?, datetime('now'))
        """,
        (msg_id, chat_id, text, "SENT_REAL" if api_sent else "LOCAL_SENT")
    )
    conn.commit()
    conn.close()

    mode_tag = "LIVE_BOT_API" if api_sent else "Local SQLite Storage"
    return f"[Telegram MCP ({mode_tag}) - SENT] Message {msg_id} logged to local storage for chat '{chat_id}': '{text}'"


