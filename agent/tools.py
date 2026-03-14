"""9 tools the Claude agent can call."""
from __future__ import annotations
import json
from datetime import datetime, date
from database import SessionLocal
from models import Project, Task, Contractor, Email, OutreachQueue, Alert, TerminationFlow
from services.email_service import send_email_via_gmail


def get_project_context(project_id: int) -> dict:
    """Get full project state: tasks, dates, contractors, outreach status."""
    db = SessionLocal()
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            return {"error": f"Project {project_id} not found"}

        tasks = db.query(Task).filter(Task.project_id == project_id).order_by(Task.sequence_order).all()
        task_list = []
        for t in tasks:
            outreach = db.query(OutreachQueue).filter(OutreachQueue.task_id == t.id).all()
            task_list.append({
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "specialty_needed": t.specialty_needed,
                "status": t.status,
                "sequence_order": t.sequence_order,
                "depends_on_task": t.depends_on_task,
                "estimated_days": t.estimated_days,
                "scheduled_start": str(t.scheduled_start) if t.scheduled_start else None,
                "scheduled_end": str(t.scheduled_end) if t.scheduled_end else None,
                "dates_confirmed": t.dates_confirmed,
                "actual_start": str(t.actual_start) if t.actual_start else None,
                "actual_end": str(t.actual_end) if t.actual_end else None,
                "outreach": [
                    {
                        "contractor_id": o.contractor_id,
                        "contractor_name": db.query(Contractor).get(o.contractor_id).name if db.query(Contractor).get(o.contractor_id) else "Unknown",
                        "priority_order": o.priority_order,
                        "status": o.status,
                        "sent_at": str(o.sent_at) if o.sent_at else None,
                    }
                    for o in outreach
                ],
            })

        alerts = db.query(Alert).filter(Alert.project_id == project_id).order_by(Alert.created_at.desc()).limit(10).all()

        return {
            "project": {
                "id": project.id,
                "name": project.name,
                "description": project.description,
                "status": project.status,
                "start_date": str(project.start_date) if project.start_date else None,
                "target_end_date": str(project.target_end_date) if project.target_end_date else None,
            },
            "tasks": task_list,
            "alerts": [{"id": a.id, "type": a.alert_type, "message": a.message, "is_read": a.is_read} for a in alerts],
        }
    finally:
        db.close()


def get_contractor_roster(specialty: str | None = None) -> list[dict]:
    """List active contractors, optionally filtered by specialty."""
    db = SessionLocal()
    try:
        query = db.query(Contractor).filter(Contractor.active == True)
        if specialty:
            query = query.filter(Contractor.specialty == specialty)
        contractors = query.order_by(
            (Contractor.rating_reliability + Contractor.rating_quality).desc()
        ).all()
        return [
            {
                "id": c.id,
                "name": c.name,
                "email": c.email,
                "phone": c.phone,
                "specialty": c.specialty,
                "rating_reliability": c.rating_reliability,
                "rating_price": c.rating_price,
                "rating_quality": c.rating_quality,
            }
            for c in contractors
        ]
    finally:
        db.close()


def create_task(project_id: int, name: str, description: str, specialty_needed: str,
                estimated_days: int, sequence_order: int, depends_on_task_id: int | None = None) -> dict:
    """Create a task in the database."""
    db = SessionLocal()
    try:
        task = Task(
            project_id=project_id,
            name=name,
            description=description,
            specialty_needed=specialty_needed,
            estimated_days=estimated_days,
            sequence_order=sequence_order,
            depends_on_task=depends_on_task_id,
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return {"id": task.id, "name": task.name, "status": "created"}
    finally:
        db.close()


def assign_contractor_to_task(task_id: int, contractor_id: int, priority_order: int = 1) -> dict:
    """Create an outreach queue entry assigning a contractor to a task."""
    db = SessionLocal()
    try:
        entry = OutreachQueue(
            task_id=task_id,
            contractor_id=contractor_id,
            priority_order=priority_order,
        )
        db.add(entry)
        task = db.query(Task).get(task_id)
        if task:
            task.status = "assigned"
        db.commit()
        return {"task_id": task_id, "contractor_id": contractor_id, "priority_order": priority_order, "status": "assigned"}
    finally:
        db.close()


def send_email(to_email: str, to_name: str, subject: str, body: str,
               task_id: int, contractor_id: int) -> dict:
    """Send an email via Gmail SMTP and log it."""
    # Sanitize any non-breaking spaces Claude may inject
    to_email = to_email.replace("\xa0", "").strip()
    to_name = to_name.replace("\xa0", " ").strip()
    subject = subject.replace("\xa0", " ")
    body = body.replace("\xa0", " ")

    db = SessionLocal()
    try:
        resend_id = send_email_via_gmail(to_email, to_name, subject, body)

        email_record = Email(
            task_id=task_id,
            contractor_id=contractor_id,
            direction="outbound",
            subject=subject,
            body=body,
            to_email=to_email,
            resend_id=resend_id,
        )
        db.add(email_record)

        outreach = db.query(OutreachQueue).filter(
            OutreachQueue.task_id == task_id,
            OutreachQueue.contractor_id == contractor_id,
        ).first()
        if outreach:
            outreach.status = "sent"
            outreach.sent_at = datetime.utcnow()

        task = db.query(Task).get(task_id)
        if task:
            task.status = "outreach_sent"

        db.commit()
        return {"status": "sent", "resend_id": resend_id, "to": to_email}
    finally:
        db.close()


def update_task_status(task_id: int, status: str, scheduled_start: str | None = None,
                       scheduled_end: str | None = None, notes: str | None = None,
                       dates_confirmed: bool | None = None) -> dict:
    """Update a task's status and optionally its dates."""
    db = SessionLocal()
    try:
        task = db.query(Task).get(task_id)
        if not task:
            return {"error": f"Task {task_id} not found"}

        dates_changed = False
        task.status = status
        if scheduled_start:
            new_start = date.fromisoformat(scheduled_start)
            if task.scheduled_start != new_start:
                dates_changed = True
            task.scheduled_start = new_start
        if scheduled_end:
            new_end = date.fromisoformat(scheduled_end)
            if task.scheduled_end != new_end:
                dates_changed = True
            task.scheduled_end = new_end
        if dates_confirmed is not None:
            task.dates_confirmed = dates_confirmed
        if status == "in_progress" and not task.actual_start:
            task.actual_start = date.today()
        if status == "complete" and not task.actual_end:
            task.actual_end = date.today()
        task.updated_at = datetime.utcnow()
        db.commit()

        # If dates changed, cascade-reschedule unconfirmed downstream tasks
        if dates_changed:
            _reschedule_downstream_from_tool(db, task_id)

        return {"task_id": task_id, "status": status, "dates_confirmed": task.dates_confirmed}
    finally:
        db.close()


def _reschedule_downstream_from_tool(db, changed_task_id: int):
    """When a task's dates change via tool call, update downstream unconfirmed tasks."""
    from datetime import timedelta

    changed = db.query(Task).get(changed_task_id)
    if not changed or not changed.scheduled_end:
        return

    queue = [changed_task_id]
    while queue:
        parent_id = queue.pop(0)
        parent = db.query(Task).get(parent_id)
        if not parent or not parent.scheduled_end:
            continue

        dependents = db.query(Task).filter(Task.depends_on_task == parent_id).all()
        for dep in dependents:
            if dep.dates_confirmed:
                continue
            est = dep.estimated_days or 5
            new_start = parent.scheduled_end + timedelta(days=1)
            new_end = new_start + timedelta(days=est - 1)
            if dep.scheduled_start != new_start or dep.scheduled_end != new_end:
                dep.scheduled_start = new_start
                dep.scheduled_end = new_end
                queue.append(dep.id)

    db.commit()


def create_alert(project_id: int, alert_type: str, message: str, task_id: int | None = None) -> dict:
    """Create a status alert."""
    db = SessionLocal()
    try:
        alert = Alert(
            project_id=project_id,
            task_id=task_id,
            alert_type=alert_type,
            message=message,
        )
        db.add(alert)
        db.commit()
        db.refresh(alert)
        return {"id": alert.id, "type": alert_type, "message": message}
    finally:
        db.close()


def get_email_threads(task_id: int) -> list[dict]:
    """Return full sent/received email history for a task."""
    db = SessionLocal()
    try:
        emails = db.query(Email).filter(Email.task_id == task_id).order_by(Email.created_at).all()
        return [
            {
                "id": e.id,
                "direction": e.direction,
                "subject": e.subject,
                "body": e.body,
                "from_email": e.from_email,
                "to_email": e.to_email,
                "created_at": str(e.created_at),
            }
            for e in emails
        ]
    finally:
        db.close()


def update_project_status(project_id: int, status: str) -> dict:
    """Update overall project status."""
    db = SessionLocal()
    try:
        project = db.query(Project).get(project_id)
        if not project:
            return {"error": f"Project {project_id} not found"}
        project.status = status
        project.updated_at = datetime.utcnow()
        db.commit()
        return {"project_id": project_id, "status": status}
    finally:
        db.close()


def create_termination_flow(task_id: int, outgoing_contractor_id: int,
                             incoming_contractor_id: int, reason: str) -> dict:
    """Create a termination flow and alert for the superintendent to review."""
    db = SessionLocal()
    try:
        task = db.query(Task).get(task_id)
        if not task:
            return {"error": f"Task {task_id} not found"}

        flow = TerminationFlow(
            task_id=task_id,
            outgoing_contractor_id=outgoing_contractor_id,
            incoming_contractor_id=incoming_contractor_id,
            reason=reason,
            status="pending_approval",
        )
        db.add(flow)
        db.flush()

        outgoing = db.query(Contractor).get(outgoing_contractor_id)
        incoming = db.query(Contractor).get(incoming_contractor_id)

        alert = Alert(
            project_id=task.project_id,
            task_id=task_id,
            alert_type="termination_recommendation",
            message=(
                f"Termination recommended for {outgoing.name if outgoing else 'contractor'} "
                f"on task '{task.name}'. Proposed replacement: {incoming.name if incoming else 'contractor'}. "
                f"Reason: {reason} (Flow ID: {flow.id})"
            ),
        )
        db.add(alert)
        db.commit()
        db.refresh(flow)
        return {"flow_id": flow.id, "status": flow.status}
    finally:
        db.close()


def get_termination_flow(flow_id: int) -> dict:
    """Get full details of a termination flow."""
    db = SessionLocal()
    try:
        flow = db.query(TerminationFlow).get(flow_id)
        if not flow:
            return {"error": f"TerminationFlow {flow_id} not found"}

        task = db.query(Task).get(flow.task_id)
        project = db.query(Project).get(task.project_id) if task else None
        outgoing = db.query(Contractor).get(flow.outgoing_contractor_id)
        incoming = db.query(Contractor).get(flow.incoming_contractor_id)

        return {
            "id": flow.id,
            "task_id": flow.task_id,
            "task_name": task.name if task else None,
            "project_id": project.id if project else None,
            "project_name": project.name if project else None,
            "outgoing_contractor_id": flow.outgoing_contractor_id,
            "outgoing_contractor_name": outgoing.name if outgoing else None,
            "outgoing_contractor_email": outgoing.email if outgoing else None,
            "incoming_contractor_id": flow.incoming_contractor_id,
            "incoming_contractor_name": incoming.name if incoming else None,
            "incoming_contractor_email": incoming.email if incoming else None,
            "reason": flow.reason,
            "status": flow.status,
            "superintendent_approved_at": str(flow.superintendent_approved_at) if flow.superintendent_approved_at else None,
            "replacement_confirmed_at": str(flow.replacement_confirmed_at) if flow.replacement_confirmed_at else None,
            "termination_sent_at": str(flow.termination_sent_at) if flow.termination_sent_at else None,
            "created_at": str(flow.created_at),
        }
    finally:
        db.close()


def get_contractor_schedule(contractor_id: int) -> dict:
    """Get a contractor's committed schedule across all projects."""
    db = SessionLocal()
    try:
        entries = db.query(OutreachQueue).filter(
            OutreachQueue.contractor_id == contractor_id,
            OutreachQueue.status.in_(["accepted", "sent"]),
        ).all()

        commitments = []
        for entry in entries:
            task = db.query(Task).get(entry.task_id)
            if task and task.status in ("committed", "in_progress") and task.scheduled_start and task.scheduled_end:
                project = db.query(Project).get(task.project_id)
                commitments.append({
                    "task_id": task.id,
                    "task_name": task.name,
                    "project_id": task.project_id,
                    "project_name": project.name if project else "Unknown",
                    "scheduled_start": str(task.scheduled_start),
                    "scheduled_end": str(task.scheduled_end),
                    "dates_confirmed": task.dates_confirmed,
                    "status": task.status,
                })

        contractor = db.query(Contractor).get(contractor_id)
        return {
            "contractor_id": contractor_id,
            "contractor_name": contractor.name if contractor else "Unknown",
            "commitments": sorted(commitments, key=lambda c: c["scheduled_start"]),
        }
    finally:
        db.close()


def advance_termination_flow(flow_id: int, new_status: str) -> dict:
    """Advance a termination flow to the next status and set the corresponding timestamp."""
    db = SessionLocal()
    try:
        flow = db.query(TerminationFlow).get(flow_id)
        if not flow:
            return {"error": f"TerminationFlow {flow_id} not found"}

        flow.status = new_status
        now = datetime.utcnow()

        if new_status == "replacement_outreach_sent":
            pass  # superintendent_approved_at set by the API endpoint
        elif new_status == "replacement_confirmed":
            flow.replacement_confirmed_at = now
        elif new_status == "termination_sent":
            flow.termination_sent_at = now
        elif new_status == "complete":
            pass

        flow.updated_at = now
        db.commit()
        return {"flow_id": flow_id, "status": new_status}
    finally:
        db.close()


def get_outreach_queue(task_id: int) -> dict:
    """Get the full outreach queue for a task — all contractors, their priority order, and response status."""
    db = SessionLocal()
    try:
        task = db.query(Task).get(task_id)
        if not task:
            return {"error": f"Task {task_id} not found"}

        project = db.query(Project).get(task.project_id) if task else None
        entries = db.query(OutreachQueue).filter(
            OutreachQueue.task_id == task_id
        ).order_by(OutreachQueue.priority_order).all()

        queue = []
        for e in entries:
            contractor = db.query(Contractor).get(e.contractor_id)
            queue.append({
                "priority_order": e.priority_order,
                "contractor_id": e.contractor_id,
                "contractor_name": contractor.name if contractor else "Unknown",
                "contractor_email": contractor.email if contractor else "",
                "contractor_specialty": contractor.specialty if contractor else "",
                "status": e.status,
                "sent_at": str(e.sent_at) if e.sent_at else None,
                "responded_at": str(e.responded_at) if e.responded_at else None,
            })

        next_available = next((e for e in queue if e["status"] == "pending"), None)
        all_exhausted = bool(queue) and all(e["status"] in ("declined", "no_response") for e in queue)

        return {
            "task_id": task_id,
            "task_name": task.name,
            "task_specialty": task.specialty_needed,
            "project_id": task.project_id,
            "project_name": project.name if project else None,
            "queue": queue,
            "next_available_contractor": next_available,
            "all_exhausted": all_exhausted,
        }
    finally:
        db.close()


def mark_outreach_status(task_id: int, contractor_id: int, status: str) -> dict:
    """Mark an outreach queue entry with a new status: accepted, declined, or no_response."""
    db = SessionLocal()
    try:
        entry = db.query(OutreachQueue).filter(
            OutreachQueue.task_id == task_id,
            OutreachQueue.contractor_id == contractor_id,
        ).first()
        if not entry:
            return {"error": f"No outreach entry found for task {task_id}, contractor {contractor_id}"}

        entry.status = status
        entry.responded_at = datetime.utcnow()

        task = db.query(Task).get(task_id)
        task_blocked = False
        if task:
            if status == "accepted":
                task.status = "committed"
            elif status in ("declined", "no_response"):
                remaining = db.query(OutreachQueue).filter(
                    OutreachQueue.task_id == task_id,
                    OutreachQueue.status == "pending",
                ).count()
                if remaining == 0:
                    task.status = "blocked"
                    task_blocked = True

        db.commit()
        return {
            "updated": True,
            "task_id": task_id,
            "contractor_id": contractor_id,
            "status": status,
            "task_now_blocked": task_blocked,
        }
    finally:
        db.close()


def save_termination_summary(flow_id: int, summary: str) -> dict:
    """Save an executive summary to a termination flow."""
    db = SessionLocal()
    try:
        flow = db.query(TerminationFlow).get(flow_id)
        if not flow:
            return {"error": f"TerminationFlow {flow_id} not found"}
        flow.summary = summary
        flow.updated_at = datetime.utcnow()
        db.commit()
        return {"flow_id": flow_id, "saved": True}
    finally:
        db.close()


# Tool definitions for Claude API
TOOL_DEFINITIONS = [
    {
        "name": "get_project_context",
        "description": "Get full project state including tasks, dates, contractors, and outreach status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "integer", "description": "The project ID"}
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "get_contractor_roster",
        "description": "List active contractors, optionally filtered by specialty.",
        "input_schema": {
            "type": "object",
            "properties": {
                "specialty": {"type": "string", "description": "Filter by specialty (e.g., framing, electrical, plumbing)"}
            },
            "required": [],
        },
    },
    {
        "name": "create_task",
        "description": "Create a new task for a project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "integer"},
                "name": {"type": "string"},
                "description": {"type": "string"},
                "specialty_needed": {"type": "string"},
                "estimated_days": {"type": "integer"},
                "sequence_order": {"type": "integer"},
                "depends_on_task_id": {"type": "integer", "description": "ID of task this depends on, or null"},
            },
            "required": ["project_id", "name", "description", "specialty_needed", "estimated_days", "sequence_order"],
        },
    },
    {
        "name": "assign_contractor_to_task",
        "description": "Assign a contractor to a task by creating an outreach queue entry.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"},
                "contractor_id": {"type": "integer"},
                "priority_order": {"type": "integer", "description": "1 = first choice"},
            },
            "required": ["task_id", "contractor_id"],
        },
    },
    {
        "name": "send_email",
        "description": "Send an outreach email to a contractor via Resend and log it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to_email": {"type": "string"},
                "to_name": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "task_id": {"type": "integer"},
                "contractor_id": {"type": "integer"},
            },
            "required": ["to_email", "to_name", "subject", "body", "task_id", "contractor_id"],
        },
    },
    {
        "name": "update_task_status",
        "description": "Update a task's status and optionally its scheduled dates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"},
                "status": {"type": "string", "enum": ["pending", "assigned", "outreach_sent", "committed", "in_progress", "complete", "blocked"]},
                "scheduled_start": {"type": "string", "description": "ISO date string"},
                "scheduled_end": {"type": "string", "description": "ISO date string"},
                "dates_confirmed": {"type": "boolean", "description": "Whether the contractor has confirmed these dates"},
                "notes": {"type": "string"},
            },
            "required": ["task_id", "status"],
        },
    },
    {
        "name": "create_alert",
        "description": "Create a project alert for the superintendent.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "integer"},
                "alert_type": {"type": "string", "enum": ["behind_schedule", "no_response", "task_blocked", "risk", "termination_recommendation"]},
                "message": {"type": "string"},
                "task_id": {"type": "integer"},
            },
            "required": ["project_id", "alert_type", "message"],
        },
    },
    {
        "name": "get_email_threads",
        "description": "Get full email history for a task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"}
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "update_project_status",
        "description": "Update the overall project status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "integer"},
                "status": {"type": "string", "enum": ["planning", "active", "behind", "at_risk", "complete"]},
            },
            "required": ["project_id", "status"],
        },
    },
    {
        "name": "create_termination_flow",
        "description": "Create a contractor termination flow with a pending_approval status and alert the superintendent.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "The task the contractor is being removed from"},
                "outgoing_contractor_id": {"type": "integer", "description": "ID of the contractor to be terminated"},
                "incoming_contractor_id": {"type": "integer", "description": "ID of the replacement contractor"},
                "reason": {"type": "string", "description": "Clear reason for the termination recommendation"},
            },
            "required": ["task_id", "outgoing_contractor_id", "incoming_contractor_id", "reason"],
        },
    },
    {
        "name": "get_termination_flow",
        "description": "Get full details of a termination flow including contractor names, task, and status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "flow_id": {"type": "integer", "description": "The termination flow ID"}
            },
            "required": ["flow_id"],
        },
    },
    {
        "name": "get_contractor_schedule",
        "description": "Get a contractor's committed schedule (all tasks they are booked for) across all projects. Use this to check for date conflicts before proposing dates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "contractor_id": {"type": "integer", "description": "The contractor ID"}
            },
            "required": ["contractor_id"],
        },
    },
    {
        "name": "advance_termination_flow",
        "description": "Advance a termination flow to a new status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "flow_id": {"type": "integer"},
                "new_status": {
                    "type": "string",
                    "enum": ["replacement_outreach_sent", "replacement_confirmed", "termination_sent", "complete", "cancelled"],
                },
            },
            "required": ["flow_id", "new_status"],
        },
    },
    {
        "name": "get_outreach_queue",
        "description": "Get the full outreach queue for a task — all contractors in priority order, their statuses, and who is next available.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "The task ID"}
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "mark_outreach_status",
        "description": "Mark an outreach queue entry with a new status. Use 'accepted' when contractor confirms, 'declined' when they say no, 'no_response' when they've gone silent. Automatically sets task to 'blocked' if all contractors in the queue are exhausted.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"},
                "contractor_id": {"type": "integer"},
                "status": {"type": "string", "enum": ["accepted", "declined", "no_response"]},
            },
            "required": ["task_id", "contractor_id", "status"],
        },
    },
    {
        "name": "save_termination_summary",
        "description": "Save a generated executive summary to a termination flow record.",
        "input_schema": {
            "type": "object",
            "properties": {
                "flow_id": {"type": "integer"},
                "summary": {"type": "string", "description": "The full markdown executive summary text"},
            },
            "required": ["flow_id", "summary"],
        },
    },
]

# Map tool names to functions
TOOL_FUNCTIONS = {
    "get_project_context": get_project_context,
    "get_contractor_roster": get_contractor_roster,
    "create_task": create_task,
    "assign_contractor_to_task": assign_contractor_to_task,
    "send_email": send_email,
    "update_task_status": update_task_status,
    "create_alert": create_alert,
    "get_email_threads": get_email_threads,
    "update_project_status": update_project_status,
    "create_termination_flow": create_termination_flow,
    "get_termination_flow": get_termination_flow,
    "get_contractor_schedule": get_contractor_schedule,
    "advance_termination_flow": advance_termination_flow,
    "get_outreach_queue": get_outreach_queue,
    "mark_outreach_status": mark_outreach_status,
    "save_termination_summary": save_termination_summary,
}
