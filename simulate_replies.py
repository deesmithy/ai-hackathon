"""
Contractor Reply Simulator — for demo purposes.

Logs into the subcontractor Gmail (GMAIL_SUB_EMAIL / GMAIL_SUB_PASSWORD),
reads unread outreach emails from Superintendent AI, and sends back
realistic human replies using Claude.

Run manually:   python simulate_replies.py
Run once:       python simulate_replies.py --once
"""
import os
import re
import sys
import time
import smtplib
import imaplib
import email as email_lib
from email.mime.text import MIMEText
from email.header import decode_header
from datetime import datetime

import anthropic
from dotenv import load_dotenv

load_dotenv()

# --- Config ---
SUB_EMAIL = os.getenv("GMAIL_SUB_EMAIL")
SUB_PASSWORD = os.getenv("GMAIL_SUB_PASSWORD")
SUPERINTENDENT_EMAIL = os.getenv("GMAIL_USER")  # The "from" address we expect
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

REPLY_PROMPT = """\
You are role-playing as a real construction subcontractor who just received an \
email from a superintendent AI system about a job. You are reading the email \
below and writing a realistic, brief reply.

IMPORTANT RULES:
- Write ONLY the email body text. No subject line, no headers, no "From:", etc.
- Keep it short — 2-5 sentences, like a real contractor would text/email.
- Be casual but professional (think: a busy tradesperson replying on their phone).
- Do NOT mention that you are an AI or that this is a simulation.
- Do NOT include any email headers or metadata.

RESPONSE TYPE (pick one based on the roll below):
- Roll: {roll}/100
- If roll <= 12: DECLINE the job. Give a brief, believable reason \
  (already booked, scheduling conflict, too far away, etc.). Be polite.
- If roll 13-25: ASK A QUESTION before committing. Ask about timeline, \
  pay rate, materials, site access, scope, etc. One specific question.
- If roll > 25: ACCEPT the job. Confirm availability, mention when you \
  could start (within the next 1-2 weeks), and express enthusiasm naturally.

The outreach email you received:
---
Subject: {subject}
Body:
{body}
---

Your reply (body text only):"""


def fetch_unread_outreach() -> list[dict]:
    """Fetch unread emails with [SUP-*] in subject from the sub inbox."""
    if not SUB_EMAIL or not SUB_PASSWORD:
        print("[SIM] GMAIL_SUB_EMAIL / GMAIL_SUB_PASSWORD not set, aborting.")
        return []

    emails = []
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(SUB_EMAIL, SUB_PASSWORD)
        mail.select("inbox")

        # Only unread emails with SUP- in subject
        _, message_numbers = mail.search(None, '(UNSEEN SUBJECT "SUP-")')

        for num in message_numbers[0].split():
            if not num:
                continue
            _, msg_data = mail.fetch(num, "(RFC822)")
            msg = email_lib.message_from_bytes(msg_data[0][1])

            # Decode subject
            subject = ""
            raw_subject = msg.get("Subject", "")
            decoded_parts = decode_header(raw_subject)
            for part, encoding in decoded_parts:
                if isinstance(part, bytes):
                    subject += part.decode(encoding or "utf-8")
                else:
                    subject += part

            # Sender
            from_addr = msg.get("From", "")
            email_match = re.search(r"<(.+?)>", from_addr)
            from_email = email_match.group(1) if email_match else from_addr

            # Recipient (To header) — we need this to know which contractor alias
            to_addr = msg.get("To", "")
            to_match = re.search(r"<(.+?)>", to_addr)
            to_email = to_match.group(1) if to_match else to_addr

            # Extract the contractor display name from the To header
            to_name_match = re.match(r"(.+?)\s*<", to_addr)
            to_name = to_name_match.group(1).strip().strip('"') if to_name_match else ""

            # Body
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode("utf-8", errors="replace")
                        break
            else:
                body = msg.get_payload(decode=True).decode("utf-8", errors="replace")

            # Skip if this email was sent BY the sub account (avoid self-reply loop)
            if from_email and SUB_EMAIL and from_email.lower().split("+")[0] == SUB_EMAIL.lower().split("+")[0]:
                print(f"[SIM] Skipping self-sent email: {subject}")
                mail.store(num, "+FLAGS", "\\Seen")
                continue

            # Also skip if it looks like a reply (Re: prefix) — don't chain
            if subject.lower().startswith("re:"):
                print(f"[SIM] Skipping reply-to-reply: {subject}")
                mail.store(num, "+FLAGS", "\\Seen")
                continue

            emails.append({
                "num": num,
                "from_email": from_email,
                "to_email": to_email,
                "to_name": to_name,
                "subject": subject,
                "body": body.strip(),
            })

            # Mark as read
            mail.store(num, "+FLAGS", "\\Seen")

        mail.logout()
    except Exception as e:
        print(f"[SIM ERROR] IMAP: {e}")

    return emails


def generate_reply(subject: str, body: str) -> str:
    """Use Claude to generate a realistic contractor reply."""
    import random
    roll = random.randint(1, 100)

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{
            "role": "user",
            "content": REPLY_PROMPT.format(roll=roll, subject=subject, body=body),
        }],
    )

    reply_text = response.content[0].text.strip()
    print(f"[SIM] Roll={roll} → {'DECLINE' if roll <= 12 else 'QUESTION' if roll <= 25 else 'ACCEPT'}")
    return reply_text


def send_reply(to_email: str, from_alias: str, from_name: str, subject: str, body: str):
    """Send a reply from the sub Gmail account using the plus-alias as the From."""
    msg = MIMEText(body, _charset="utf-8")
    msg["Subject"] = f"Re: {subject}"
    msg["From"] = f"{from_name} <{from_alias}>"
    msg["To"] = to_email
    msg["In-Reply-To"] = ""  # Could track message-id but not needed for demo

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(SUB_EMAIL, SUB_PASSWORD)
        server.send_message(msg)

    print(f"[SIM] Replied as {from_name} <{from_alias}> → {to_email}")


def run_once():
    """One pass: fetch unread outreach, generate replies, send them."""
    emails = fetch_unread_outreach()
    if not emails:
        print("[SIM] No new outreach emails found.")
        return 0

    print(f"[SIM] Found {len(emails)} outreach email(s) to reply to.\n")

    for e in emails:
        print(f"  Processing: {e['subject']}")
        print(f"    To: {e['to_name']} <{e['to_email']}>")

        try:
            reply_body = generate_reply(e["subject"], e["body"])
            print(f"    Reply: {reply_body[:100]}...")

            send_reply(
                to_email=e["from_email"],        # Reply to superintendent
                from_alias=e["to_email"],         # Use the plus-alias the email was sent to
                from_name=e["to_name"] or "Contractor",
                subject=e["subject"],
                body=reply_body,
            )
            print()
        except Exception as ex:
            print(f"    ERROR: {ex}\n")

    return len(emails)


def main():
    print("=" * 60)
    print("  Contractor Reply Simulator")
    print("=" * 60)
    print(f"  Sub account:   {SUB_EMAIL}")
    print(f"  Superintendent: {SUPERINTENDENT_EMAIL}")
    print()

    if not SUB_EMAIL or not SUB_PASSWORD:
        print("ERROR: GMAIL_SUB_EMAIL and GMAIL_SUB_PASSWORD must be set in .env")
        sys.exit(1)

    if "--once" in sys.argv:
        count = run_once()
        print(f"\nDone. Replied to {count} email(s).")
    else:
        print("Running in loop mode (checks every 30 seconds). Ctrl+C to stop.\n")
        try:
            while True:
                run_once()
                print(f"--- Sleeping 30s (next check at {datetime.now().strftime('%H:%M:%S')}) ---\n")
                time.sleep(30)
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
