import os
import smtplib
import imaplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict, Any, Optional
from src.db import get_connection

class SMTPEmailAdapter:
    """
    SMTP Email Adapter for transmitting outbound emails when environment variables are set.
    Fails over gracefully to local SQLite storage in local-first dev mode.
    """
    def __init__(self):
        self.smtp_host = os.getenv("SMTP_HOST", "")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = os.getenv("SMTP_USER", "")
        self.smtp_pass = os.getenv("SMTP_PASS", "")
        self.is_configured = bool(self.smtp_host and self.smtp_user and self.smtp_pass)

    def send_email(self, to_addr: str, subject: str, body: str) -> Dict[str, Any]:
        from_addr = self.smtp_user or "user@assistant.local"

        if self.is_configured:
            try:
                msg = MIMEMultipart()
                msg["From"] = from_addr
                msg["To"] = to_addr
                msg["Subject"] = subject
                msg.attach(MIMEText(body, "plain"))

                with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10) as server:
                    server.starttls()
                    server.login(self.smtp_user, self.smtp_pass)
                    server.send_message(msg)

                return {"status": "sent", "mode": "SMTP", "from": from_addr, "to": to_addr}
            except Exception as ex:
                return {"status": "error", "mode": "SMTP", "error": str(ex)}

        return {"status": "sent", "mode": "LOCAL_SQLITE", "from": from_addr, "to": to_addr}

class IMAPEmailAdapter:
    """
    IMAP Email Adapter for pulling unread/recent incoming messages when environment variables are set.
    Fails over gracefully to local SQLite storage in local-first dev mode.
    """
    def __init__(self):
        self.imap_host = os.getenv("IMAP_HOST", "")
        self.imap_port = int(os.getenv("IMAP_PORT", "993"))
        self.imap_user = os.getenv("IMAP_USER", "")
        self.imap_pass = os.getenv("IMAP_PASS", "")
        self.is_configured = bool(self.imap_host and self.imap_user and self.imap_pass)

    def fetch_recent_emails(self, limit: int = 5) -> List[Dict[str, Any]]:
        if not self.is_configured:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, sender, recipient, subject, body, folder, status, created_at FROM emails ORDER BY created_at DESC LIMIT ?",
                (limit,)
            )
            rows = [dict(r) for r in cursor.fetchall()]
            conn.close()
            return rows

        try:
            with imaplib.IMAP4_SSL(self.imap_host, self.imap_port) as mail:
                mail.login(self.imap_user, self.imap_pass)
                mail.select("INBOX")
                _, search_data = mail.search(None, "ALL")
                msg_ids = search_data[0].split()[-limit:]

                fetched_emails = []
                for m_id in reversed(msg_ids):
                    _, msg_data = mail.fetch(m_id, "(RFC822)")
                    for response_part in msg_data:
                        if isinstance(response_part, tuple):
                            msg = email.message_from_bytes(response_part[1])
                            fetched_emails.append({
                                "id": f"imap_{m_id.decode()}",
                                "sender": msg.get("From", "unknown"),
                                "recipient": msg.get("To", "user"),
                                "subject": msg.get("Subject", "(No Subject)"),
                                "body": str(msg.get_payload()),
                                "folder": "inbox",
                                "status": "READ",
                                "created_at": msg.get("Date", "")
                            })
                return fetched_emails
        except Exception as ex:
            print(f"[IMAP Adapter Warning] Failed to connect: {ex}. Falling back to SQLite.")
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, sender, recipient, subject, body, folder, status, created_at FROM emails ORDER BY created_at DESC LIMIT ?",
                (limit,)
            )
            rows = [dict(r) for r in cursor.fetchall()]
            conn.close()
            return rows
