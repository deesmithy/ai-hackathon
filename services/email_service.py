"""Email service: Resend for outbound, Gmail IMAP for inbound."""
import os
import re
import imaplib
import email as email_lib
from email.header import decode_header
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()


def send_email_via_resend(to_email: str, to_name: str, subject: str, body: str) -> str | None:
    """Send an email via the Resend API. Returns the Resend message ID."""
    api_key = os.getenv("RESEND_API_KEY")
    from_email = os.getenv("RESEND_FROM_EMAIL", "superintendent@example.com")

    if not api_key or api_key.startswith("re_..."):
        print(f"[EMAIL STUB] Would send to {to_email}: {subject}")
        return "stub-no-resend-key"

    import resend
    resend.api_key = api_key

    result = resend.Emails.send({
        "from": f"Superintendent AI <{from_email}>",
        "to": [f"{to_name} <{to_email}>"],
        "subject": subject,
        "text": body,
    })
    return result.get("id")


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

        # Search for unread emails with SUP- in subject
        _, message_numbers = mail.search(None, '(UNSEEN SUBJECT "SUP-")')

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
