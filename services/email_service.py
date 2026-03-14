"""Email service: Gmail SMTP for outbound, Gmail IMAP for inbound."""
from __future__ import annotations
import os
import re
import smtplib
import imaplib
import email as email_lib
from email.mime.text import MIMEText
from email.header import decode_header
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()


def send_email_via_gmail(to_email: str, to_name: str, subject: str, body: str) -> str | None:
    """Send an email via Gmail SMTP using an App Password."""
    gmail_user = os.getenv("GMAIL_USER")
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD")

    if not gmail_user or not gmail_pass or gmail_pass.startswith("xxxx"):
        print(f"[EMAIL STUB] Would send to {to_email}: {subject}")
        return "stub-no-gmail-creds"

    # Sanitize non-breaking spaces and other unicode whitespace that Claude may produce
    to_email = to_email.replace("\xa0", "").strip()
    to_name = to_name.replace("\xa0", " ").strip()
    subject = subject.replace("\xa0", " ")
    body = body.replace("\xa0", " ")

    msg = MIMEText(body, _charset="utf-8")
    msg["Subject"] = subject
    msg["From"] = f"Cliff <{gmail_user}>"
    msg["To"] = f"{to_name} <{to_email}>"

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_pass)
        server.send_message(msg)

    print(f"[EMAIL SENT] To: {to_email} | Subject: {subject}")
    return f"gmail-{datetime.utcnow().isoformat()}"


def poll_gmail_inbox() -> list[dict]:
    """Poll Gmail via IMAP for replies with [SUP-*] in subject. Returns parsed emails."""
    gmail_user = os.getenv("GMAIL_USER")
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD")

    if not gmail_user or not gmail_pass or gmail_pass.startswith("xxxx"):
        print("[GMAIL STUB] No Gmail credentials configured, skipping poll.")
        return []

    parsed_emails = []
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(gmail_user, gmail_pass)
        mail.select("inbox")

        # Search for all unread emails
        _, message_numbers = mail.search(None, "UNSEEN")

        for num in message_numbers[0].split():
            if not num:
                continue
            _, msg_data = mail.fetch(num, "(RFC822)")
            msg = email_lib.message_from_bytes(msg_data[0][1])

            subject = ""
            raw_subject = msg.get("Subject", "")
            decoded_parts = decode_header(raw_subject)
            for part, encoding in decoded_parts:
                if isinstance(part, bytes):
                    subject += part.decode(encoding or "utf-8")
                else:
                    subject += part

            from_addr = msg.get("From", "")
            # Extract just the email address
            email_match = re.search(r"<(.+?)>", from_addr)
            from_email_addr = email_match.group(1) if email_match else from_addr

            # Skip emails sent by ourselves (prevent self-processing loops)
            if from_email_addr.lower() == gmail_user.lower():
                mail.store(num, "+FLAGS", "\\Seen")
                continue

            # Extract body
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode("utf-8", errors="replace")
                        break
            else:
                body = msg.get_payload(decode=True).decode("utf-8", errors="replace")

            # Extract task ID from subject [SUP-{id}]
            task_match = re.search(r"\[SUP-(\d+)\]", subject)
            task_id = int(task_match.group(1)) if task_match else None

            parsed_emails.append({
                "from_email": from_email_addr,
                "subject": subject,
                "body": body,
                "task_id": task_id,
            })

            # Mark as read
            mail.store(num, "+FLAGS", "\\Seen")

        mail.logout()
    except Exception as e:
        print(f"[GMAIL ERROR] {e}")

    return parsed_emails
