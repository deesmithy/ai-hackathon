"""Email service: mock email via DB. No real SMTP/IMAP needed."""
from __future__ import annotations
import os
import re
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()


def send_email_via_gmail(to_email: str, to_name: str, subject: str, body: str) -> str | None:
    """Mock send — the email is already logged in DB by the caller in agent/tools.py.
    This just prints a log line and returns a stub ID."""
    # Sanitize non-breaking spaces and other unicode whitespace that Claude may produce
    to_email = to_email.replace("\xa0", "").strip()
    to_name = to_name.replace("\xa0", " ").strip()
    subject = subject.replace("\xa0", " ")
    body = body.replace("\xa0", " ")

    print(f"[EMAIL SENT] To: {to_name} <{to_email}> | Subject: {subject}")
    return f"mock-{datetime.utcnow().isoformat()}"


def poll_gmail_inbox() -> list[dict]:
    """Poll the DB for unprocessed inbound emails (written by the simulator).
    Returns parsed emails in the same format the old IMAP poller used."""
    from database import SessionLocal
    from models import Email

    db = SessionLocal()
    try:
        unprocessed = (
            db.query(Email)
            .filter(Email.direction == "inbound", Email.processed == False)
            .order_by(Email.created_at)
            .all()
        )

        parsed = []
        for e in unprocessed:
            # Extract task ID from subject [SUP-{id}]
            task_id = None
            if e.subject:
                task_match = re.search(r"\[SUP-(\d+)\]", e.subject)
                task_id = int(task_match.group(1)) if task_match else None

            parsed.append({
                "from_email": e.from_email or "",
                "subject": e.subject or "",
                "body": e.body or "",
                "task_id": task_id,
            })

            # Mark as processed
            e.processed = True

        db.commit()
        return parsed
    except Exception as ex:
        print(f"[POLL ERROR] {ex}")
        db.rollback()
        return []
    finally:
        db.close()
