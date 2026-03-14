"""9 tools the Claude agent can call."""
import json
from datetime import datetime, date
from database import SessionLocal
from models import Project, Task, Contractor, Email, OutreachQueue, Alert
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
                       scheduled_end: str | None = None, notes: str | None = None) -> dict:
    """Update a task's status and optionally its dates."""
    db = SessionLocal()
    try:
        task = db.query(Task).get(task_id)
        if not task:
            return {"error": f"Task {task_id} not found"}
        task.status = status
        if scheduled_start:
            task.scheduled_start = date.fromisoformat(scheduled_start)
        if scheduled_end:
            task.scheduled_end = date.fromisoformat(scheduled_end)
        if status == "in_progress" and not task.actual_start:
            task.actual_start = date.today()
        if status == "complete" and not task.actual_end:
            task.actual_end = date.today()
        task.updated_at = datetime.utcnow()
        db.commit()
        return {"task_id": task_id, "status": status}
    finally:
        db.close()


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
                "alert_type": {"type": "string", "enum": ["behind_schedule", "no_response", "task_blocked", "risk"]},
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
}
