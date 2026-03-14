"""
Contractor Reply Simulator — DB-based mock email system.

Reads unreplied outbound emails from the database, generates realistic
contractor replies using Claude, and writes them back as inbound emails.
The superintendent's poller picks them up from DB automatically.

Run:        .venv/bin/python simulate_replies.py
One pass:   .venv/bin/python simulate_replies.py --once
"""
import os
import sys
import time
import random
from datetime import datetime

import anthropic
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

REPLY_PROMPT = """\
You are role-playing as a real construction subcontractor who just received an \
email from a superintendent named Cliff about a job. Write a realistic, brief reply.

IMPORTANT CONTEXT:
- These projects are always NEW CONSTRUCTION or UNFINISHED BASEMENT buildouts.
- There is NEVER mold, asbestos, demolition of old work, or renovation-specific issues.
- Do NOT ask about or mention mold, asbestos, lead paint, existing conditions, or remediation.
- Keep questions practical: materials, access, scheduling, crew size, dumpster, permits, etc.

IMPORTANT RULES:
- Write ONLY the email body text. No subject line, no headers, no "From:", etc.
- Keep it short — 2-5 sentences, like a real contractor would text/email.
- Be casual but professional (think: a busy tradesperson replying on their phone).
- Do NOT mention that you are an AI or that this is a simulation.
- Do NOT include any email headers or metadata.

Your current schedule commitments:
{schedule_info}

How many emails have already gone back and forth on this thread: {thread_depth}

You MUST pick EXACTLY ONE of these response types based on the roll AND your schedule:
- Roll: {roll}/100

**If this is a SCHEDULE CONFIRMATION email** (subject contains "Schedule Confirmation"):
  - If the proposed dates overlap with your existing commitments above, you MUST counter-propose \
    dates that don't conflict. Mention your existing commitment as the reason and suggest starting \
    after it ends. Keep the same duration.
  - If roll <= 40 and no conflicts: Counter-propose slightly different dates (e.g., "I can't \
    start until [2-5 days later]"). Give a brief, specific reason — wrapping up a small side job, \
    waiting on a materials delivery, family commitment, crew availability, etc.
  - If roll <= 50 and thread_depth >= 3: You're fed up with the back-and-forth. Tell them you're \
    pulling out — the schedule isn't working for you. Be polite but firm.
  - Otherwise (no conflicts): Confirm the proposed dates. Say something like "Those dates work \
    for me" or "I can make that schedule work."

**If this is a FOLLOW-UP or REPLY from the superintendent** (looks like a response to something \
you said earlier):
  - If they're explaining why your proposed dates don't work:
    - If roll <= 30: Push back. Insist your dates are the only ones that work, or say you'll \
      need to think about it. Be a little difficult but not rude.
    - If roll <= 50: Offer a compromise — split the difference on dates, or ask if you can \
      start 1-2 days later than what they proposed.
    - Otherwise: Accept their reasoning and confirm their proposed dates.
  - If they're asking you to confirm something: Confirm it simply.
  - If thread_depth >= 4 and roll <= 25: Ghost them. Do NOT reply at all. Return the exact \
    text "NO_REPLY" (this simulates going silent).

**If this is an INITIAL OUTREACH email** (not a schedule confirmation or follow-up):
  - If you have schedule conflicts with the dates mentioned in the email, mention you're booked \
    during that period but could start after your current job ends. This overrides the roll.
  - If roll <= 10: NOT AVAILABLE. Politely decline — give a brief believable reason (booked \
    solid, taking time off, committed to another GC).
  - If roll 11-25: REQUEST MORE INFO. Ask ONE specific practical question before committing \
    (square footage, material specs, access/parking, permit status, crew count needed).
  - If roll > 25: YES, I CAN DO THE JOB. Confirm you're available and sound naturally enthusiastic.

The email you received:
---
Subject: {subject}
Body:
{body}
---

Your reply (body text only):"""


def get_unreplied_outbound():
    """Find outbound emails that don't have a corresponding inbound reply yet."""
    from database import SessionLocal
    from models import Email

    db = SessionLocal()
    try:
        outbound = db.query(Email).filter(Email.direction == "outbound").order_by(Email.created_at).all()
        inbound = db.query(Email).filter(Email.direction == "inbound").all()

        # For each outbound, check if there's an inbound with same task+contractor created after it
        unreplied = []
        for out in outbound:
            has_reply = any(
                inp.task_id == out.task_id
                and inp.contractor_id == out.contractor_id
                and inp.created_at > out.created_at
                for inp in inbound
            )
            if not has_reply:
                unreplied.append({
                    "id": out.id,
                    "task_id": out.task_id,
                    "contractor_id": out.contractor_id,
                    "subject": out.subject or "",
                    "body": out.body or "",
                    "to_email": out.to_email or "",
                })

        return unreplied
    finally:
        db.close()


def get_contractor_info(contractor_id):
    """Get contractor name and email from DB."""
    from database import SessionLocal
    from models import Contractor

    db = SessionLocal()
    try:
        c = db.query(Contractor).filter(Contractor.id == contractor_id).first()
        if c:
            return {"name": c.name, "email": c.email}
        return {"name": "Contractor", "email": ""}
    finally:
        db.close()


def get_contractor_commitments(contractor_id):
    """Look up existing schedule commitments for a contractor."""
    from database import SessionLocal
    from models import OutreachQueue, Task

    db = SessionLocal()
    try:
        entries = db.query(OutreachQueue).filter(
            OutreachQueue.contractor_id == contractor_id,
            OutreachQueue.status.in_(["accepted", "sent"]),
        ).all()

        commitments = []
        for e in entries:
            task = db.query(Task).get(e.task_id)
            if task and task.status in ("committed", "in_progress") and task.scheduled_start:
                commitments.append({
                    "start": str(task.scheduled_start),
                    "end": str(task.scheduled_end) if task.scheduled_end else str(task.scheduled_start),
                    "task_name": task.name,
                })
        return commitments
    finally:
        db.close()


def get_thread_depth(task_id, contractor_id):
    """Count how many emails have gone back and forth on this task+contractor thread."""
    from database import SessionLocal
    from models import Email

    db = SessionLocal()
    try:
        count = db.query(Email).filter(
            Email.task_id == task_id,
            Email.contractor_id == contractor_id,
        ).count()
        return count
    finally:
        db.close()


def generate_reply(subject, body, contractor_id=None, task_id=None):
    """Use Claude to generate a realistic contractor reply. Returns (reply_text, response_type)."""
    roll = random.randint(1, 100)
    response_type = "NOT AVAILABLE" if roll <= 10 else "MORE INFO" if roll <= 25 else "YES"

    commitments = get_contractor_commitments(contractor_id) if contractor_id else []
    if commitments:
        schedule_info = "\n".join(
            f"- {c['task_name']}: {c['start']} to {c['end']}" for c in commitments
        )
    else:
        schedule_info = "You have no current commitments."

    thread_depth = get_thread_depth(task_id, contractor_id) if task_id and contractor_id else 0

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{
            "role": "user",
            "content": REPLY_PROMPT.format(
                roll=roll, subject=subject, body=body,
                schedule_info=schedule_info, thread_depth=thread_depth,
            ),
        }],
    )

    reply_text = response.content[0].text.strip()
    has_conflicts = len(commitments) > 0
    print(f"    Roll={roll}, Depth={thread_depth}, Commitments={len(commitments)} → {response_type}{' (has schedule conflicts!)' if has_conflicts else ''}")
    return reply_text, response_type


def save_inbound_email(task_id, contractor_id, subject, body, from_email):
    """Write an inbound email to the DB. The superintendent's poller will pick it up."""
    from database import SessionLocal
    from models import Email

    db = SessionLocal()
    try:
        email = Email(
            task_id=task_id,
            contractor_id=contractor_id,
            direction="inbound",
            subject=f"Re: {subject}",
            body=body,
            from_email=from_email,
            processed=False,
        )
        db.add(email)
        db.commit()
    finally:
        db.close()


def run_once():
    """One pass: find unreplied outbound emails, generate and save replies."""
    unreplied = get_unreplied_outbound()
    if not unreplied:
        print("[SIM] No unreplied outbound emails.")
        return 0

    print(f"[SIM] Found {len(unreplied)} unreplied outbound email(s).\n")

    for e in unreplied:
        contractor = get_contractor_info(e["contractor_id"])
        print(f"  {contractor['name']} — {e['subject'][:70]}")

        try:
            reply_body, response_type = generate_reply(
                e["subject"], e["body"], e["contractor_id"], e["task_id"],
            )

            # "NO_REPLY" = contractor is ghosting (simulated silence)
            if reply_body.strip() == "NO_REPLY":
                print(f"    [GHOST] Contractor is ghosting — no reply generated.\n")
                continue

            print(f"    Reply: {reply_body[:100]}...")

            save_inbound_email(
                task_id=e["task_id"],
                contractor_id=e["contractor_id"],
                subject=e["subject"],
                body=reply_body,
                from_email=contractor["email"],
            )
            print(f"    Saved to DB.\n")
        except Exception as ex:
            print(f"    ERROR: {ex}\n")

    return len(unreplied)


def main():
    print("=" * 60)
    print("  Contractor Reply Simulator (DB-based)")
    print("=" * 60)
    print()

    if "--once" in sys.argv:
        count = run_once()
        print(f"Done. Generated {count} reply/replies.")
    else:
        print("Running in loop mode (checks every 10 seconds). Ctrl+C to stop.\n")
        try:
            while True:
                run_once()
                print(f"--- Next check in 10s ---\n")
                time.sleep(10)
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
