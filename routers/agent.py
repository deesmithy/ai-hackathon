from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Form, UploadFile, File
from typing import Optional
from datetime import date as date_type
from sqlalchemy.orm import Session
from datetime import datetime
from database import get_db
from models import Project, Email, Task, OutreachQueue, TerminationFlow, Contractor, Alert
from schemas import GeneratePlanRequest, AssignContractorsRequest, RunOutreachRequest, CheckStatusRequest, ProcessReplyRequest, EvaluateTerminationRequest, ApproveTerminationRequest, CancelTerminationRequest, TerminationFlowOut, DemoTerminationRequest, RegenerateTasksRequest, ReassignContractorsRequest
from agent.agent import run_agent, generate_tasks_direct, assign_and_draft_direct, generate_plan_and_assign_direct
from services.contractor_service import get_contractor_by_email

router = APIRouter(prefix="/api/agent", tags=["agent"])


def _build_assignment_list(db, project_id):
    tasks = db.query(Task).filter(Task.project_id == project_id).order_by(Task.sequence_order).all()
    result = []
    for t in tasks:
        entry = db.query(OutreachQueue).filter(
            OutreachQueue.task_id == t.id, OutreachQueue.priority_order == 1
        ).first()
        if entry:
            contractor = db.query(Contractor).filter(Contractor.id == entry.contractor_id).first()
            result.append({
                "task_id": t.id, "task_name": t.name, "specialty_needed": t.specialty_needed,
                "contractor_id": contractor.id if contractor else None,
                "contractor_name": contractor.name if contractor else "Unknown",
                "contractor_specialty": contractor.specialty if contractor else None,
                "rating_reliability": contractor.rating_reliability if contractor else None,
                "rating_quality": contractor.rating_quality if contractor else None,
                "rating_price": contractor.rating_price if contractor else None,
            })
    return result


@router.post("/poll-inbox")
def poll_inbox():
    """Manually trigger a Gmail inbox poll and process any replies."""
    from main import scheduled_poll_emails
    scheduled_poll_emails()
    return {"status": "done"}


def _build_plan_user_msg(project):
    user_msg = (
        f"Create a construction task plan for project ID {project.id}.\n"
        f"Project name: {project.name}\n"
        f"Description: {project.description}\n"
    )
    if project.start_date:
        user_msg += f"Start date: {project.start_date}\n"
    if project.target_end_date:
        user_msg += f"Target end date: {project.target_end_date}\n"
    if project.uploaded_file_content:
        user_msg += f"\nAdditional project document:\n{project.uploaded_file_content}\n"
    return user_msg


def _save_tasks_from_dicts(db, project_id: int, task_dicts: list[dict]) -> list[dict]:
    """Bulk-insert tasks from Claude's structured output and resolve depends_on references."""
    inserted = []
    for t in task_dicts:
        task = Task(
            project_id=project_id,
            name=t["name"],
            description=t.get("description"),
            specialty_needed=t.get("specialty_needed"),
            estimated_days=t.get("estimated_days"),
            sequence_order=t.get("sequence_order", 0),
        )
        db.add(task)
        db.flush()  # populate task.id before second pass
        inserted.append((task, t.get("depends_on_sequence")))

    # Second pass: resolve depends_on_sequence → actual task ID
    seq_to_id = {task.sequence_order: task.id for task, _ in inserted}
    for task, dep_seq in inserted:
        if dep_seq and dep_seq in seq_to_id:
            task.depends_on_task = seq_to_id[dep_seq]

    db.commit()
    return [
        {
            "id": task.id,
            "name": task.name,
            "description": task.description,
            "specialty_needed": task.specialty_needed,
            "estimated_days": task.estimated_days,
            "sequence_order": task.sequence_order,
        }
        for task, _ in inserted
    ]


def _save_tasks_and_assignments(db, project_id: int, task_dicts: list[dict]) -> list[dict]:
    """Bulk-insert tasks + outreach queue entries from the combined plan+assign output."""
    inserted = []
    for t in task_dicts:
        task = Task(
            project_id=project_id,
            name=t["name"],
            description=t.get("description"),
            specialty_needed=t.get("specialty_needed"),
            estimated_days=t.get("estimated_days"),
            sequence_order=t.get("sequence_order", 0),
        )
        db.add(task)
        db.flush()
        inserted.append((task, t.get("depends_on_sequence"), t.get("contractor_id")))

    # Resolve depends_on references
    seq_to_id = {task.sequence_order: task.id for task, _, _ in inserted}
    for task, dep_seq, _ in inserted:
        if dep_seq and dep_seq in seq_to_id:
            task.depends_on_task = seq_to_id[dep_seq]

    # Create outreach queue entries
    for task, _, contractor_id in inserted:
        if contractor_id:
            db.add(OutreachQueue(
                task_id=task.id,
                contractor_id=contractor_id,
                priority_order=1,
            ))
            task.status = "assigned"

    db.commit()

    # Build response with contractor details
    result = []
    for task, _, contractor_id in inserted:
        contractor = db.query(Contractor).filter(Contractor.id == contractor_id).first() if contractor_id else None
        result.append({
            "task_id": task.id,
            "task_name": task.name,
            "description": task.description,
            "specialty_needed": task.specialty_needed,
            "estimated_days": task.estimated_days,
            "sequence_order": task.sequence_order,
            "contractor_id": contractor.id if contractor else None,
            "contractor_name": contractor.name if contractor else "Unassigned",
            "rating_reliability": contractor.rating_reliability if contractor else None,
            "rating_quality": contractor.rating_quality if contractor else None,
            "rating_price": contractor.rating_price if contractor else None,
        })
    return result


def _auto_schedule_tasks(db: Session, project_id: int):
    """Compute scheduled_start and scheduled_end for all tasks based on dependencies and estimated_days."""
    from datetime import date, timedelta

    tasks = db.query(Task).filter(Task.project_id == project_id).order_by(Task.sequence_order).all()
    project = db.query(Project).filter(Project.id == project_id).first()
    base_date = project.start_date if project and project.start_date else date.today()

    # Build lookup: task_id -> task
    task_map = {t.id: t for t in tasks}
    # Track computed end dates
    end_dates = {}

    for t in tasks:
        est = t.estimated_days or 5
        if t.depends_on_task and t.depends_on_task in end_dates:
            # Start the day after the dependency ends
            start = end_dates[t.depends_on_task] + timedelta(days=1)
        else:
            start = base_date
        end = start + timedelta(days=est - 1)

        t.scheduled_start = start
        t.scheduled_end = end
        end_dates[t.id] = end

    # Update project target_end_date if not set
    if project and end_dates and not project.target_end_date:
        project.target_end_date = max(end_dates.values())

    db.commit()


def _reschedule_downstream(db: Session, changed_task_id: int):
    """When a task's dates change, cascade-update all downstream tasks that haven't confirmed dates yet."""
    from datetime import timedelta

    changed = db.query(Task).filter(Task.id == changed_task_id).first()
    if not changed or not changed.scheduled_end:
        return

    # Walk the dependency chain forward
    queue = [changed_task_id]
    rescheduled = []
    while queue:
        parent_id = queue.pop(0)
        parent = db.query(Task).filter(Task.id == parent_id).first()
        if not parent or not parent.scheduled_end:
            continue

        dependents = db.query(Task).filter(Task.depends_on_task == parent_id).all()
        for dep in dependents:
            # Only reschedule if dates aren't already confirmed by the contractor
            if dep.dates_confirmed:
                continue
            est = dep.estimated_days or 5
            new_start = parent.scheduled_end + timedelta(days=1)
            new_end = new_start + timedelta(days=est - 1)

            if dep.scheduled_start != new_start or dep.scheduled_end != new_end:
                dep.scheduled_start = new_start
                dep.scheduled_end = new_end
                rescheduled.append(dep)
                queue.append(dep.id)

    if rescheduled:
        db.commit()
        names = ", ".join(f"'{t.name}'" for t in rescheduled)
        print(f"[RESCHEDULE] Updated dates for {len(rescheduled)} downstream task(s): {names}")


def _auto_assign_and_outreach(project_id: int, project_name: str):
    """Assign contractors and send outreach emails via a single structured API call."""
    from database import SessionLocal
    from datetime import datetime as _dt
    from services.email_service import send_email_via_gmail
    from models import AgentAction

    assignments = assign_and_draft_direct(project_id, project_name)

    db = SessionLocal()
    try:
        for a in assignments:
            task = db.query(Task).get(a["task_id"])
            contractor = db.query(Contractor).get(a["contractor_id"])
            if not task or not contractor:
                continue

            # Skip if already assigned
            existing = db.query(OutreachQueue).filter(
                OutreachQueue.task_id == task.id,
                OutreachQueue.contractor_id == contractor.id,
            ).first()
            if existing:
                continue

            entry = OutreachQueue(
                task_id=task.id,
                contractor_id=contractor.id,
                priority_order=1,
                status="sent",
                sent_at=_dt.utcnow(),
            )
            db.add(entry)
            task.status = "outreach_sent"

            subject = a.get("subject", "").replace("\xa0", " ")
            body = a.get("body", "").replace("\xa0", " ")
            to_email = a.get("to_email", contractor.email).replace("\xa0", "").strip()
            to_name = a.get("to_name", contractor.name).replace("\xa0", " ").strip()

            resend_id = send_email_via_gmail(to_email, to_name, subject, body)

            db.add(Email(
                task_id=task.id,
                contractor_id=contractor.id,
                direction="outbound",
                subject=subject,
                body=body,
                to_email=to_email,
                resend_id=resend_id,
            ))

            db.add(AgentAction(
                project_id=project_id,
                task_id=task.id,
                agent_mode="email_drafter",
                action_type="send_email",
                description=f"Sent email to {to_name}: \"{subject}\"",
            ))

        project = db.query(Project).filter(Project.id == project_id).first()
        if project and project.status == "planning":
            project.status = "active"

        db.commit()
    finally:
        db.close()


@router.post("/create-and-plan")
async def create_and_plan(
    name: str = Form(...),
    description: str = Form(...),
    start_date: Optional[str] = Form(None),
    target_end_date: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    """Create a project and generate its task plan in a single request."""
    uploaded_file_content = None
    if file:
        raw = await file.read()
        if file.filename and file.filename.lower().endswith(".pdf"):
            import fitz
            doc = fitz.open(stream=raw, filetype="pdf")
            uploaded_file_content = "\n".join(page.get_text() for page in doc)
            doc.close()
        else:
            uploaded_file_content = raw.decode("utf-8", errors="ignore")

    project = Project(
        name=name,
        description=description,
        start_date=date_type.fromisoformat(start_date) if start_date else None,
        target_end_date=date_type.fromisoformat(target_end_date) if target_end_date else None,
        uploaded_file_content=uploaded_file_content,
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    user_msg = _build_plan_user_msg(project)
    task_dicts = generate_plan_and_assign_direct(user_msg)
    items = _save_tasks_and_assignments(db, project.id, task_dicts)
    return {"project_id": project.id, "items": items}


@router.post("/generate-plan")
def generate_plan(data: GeneratePlanRequest, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == data.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    user_msg = _build_plan_user_msg(project)
    task_dicts = generate_tasks_direct(user_msg)
    task_list = _save_tasks_from_dicts(db, project.id, task_dicts)
    _auto_schedule_tasks(db, project.id)

    # Automatically assign contractors and send outreach
    _auto_assign_and_outreach(project.id, project.name)

    return {"project_id": project.id, "tasks": task_list}


@router.post("/regenerate-tasks")
def regenerate_tasks(data: RegenerateTasksRequest, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == data.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Delete existing tasks (cascade deletes outreach queue entries)
    existing = db.query(Task).filter(Task.project_id == project.id).all()
    for t in existing:
        db.delete(t)
    db.commit()

    user_msg = _build_plan_user_msg(project)
    user_msg += f"\nUser feedback: {data.feedback}\nPlease revise accordingly."
    task_dicts = generate_plan_and_assign_direct(user_msg)
    items = _save_tasks_and_assignments(db, project.id, task_dicts)

    return {"project_id": project.id, "items": items}


@router.post("/assign-contractors")
def assign_contractors(data: AssignContractorsRequest, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == data.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    user_msg = f"Assign contractors to all unassigned tasks for project ID {project.id} ({project.name})."
    run_agent("contractor_assigner", user_msg)

    return {"project_id": project.id, "assignments": _build_assignment_list(db, project.id)}


@router.post("/reassign-contractors")
def reassign_contractors(data: ReassignContractorsRequest, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == data.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Clear all outreach queue entries and reset task statuses
    tasks = db.query(Task).filter(Task.project_id == project.id).all()
    for t in tasks:
        entries = db.query(OutreachQueue).filter(OutreachQueue.task_id == t.id).all()
        for e in entries:
            db.delete(e)
        t.status = "pending"
    db.commit()

    _auto_assign_and_outreach(project.id, project.name)

    return {"project_id": project.id, "assignments": _build_assignment_list(db, project.id)}


def _send_outreach_for_assigned(project_id: int, project_name: str):
    """Send outreach emails for tasks that are assigned but not yet emailed."""
    from database import SessionLocal
    from datetime import datetime as _dt
    from services.email_service import send_email_via_gmail
    from models import AgentAction

    email_drafts = assign_and_draft_direct(project_id, project_name)
    draft_map = {d["task_id"]: d for d in email_drafts}

    db = SessionLocal()
    try:
        tasks = db.query(Task).filter(
            Task.project_id == project_id,
            Task.status == "assigned",
        ).all()

        for task in tasks:
            entry = db.query(OutreachQueue).filter(
                OutreachQueue.task_id == task.id,
                OutreachQueue.priority_order == 1,
            ).first()
            if not entry:
                continue

            draft = draft_map.get(task.id)
            if not draft:
                continue

            subject = draft.get("subject", "").replace("\xa0", " ")
            body = draft.get("body", "").replace("\xa0", " ")
            contractor = db.query(Contractor).filter(Contractor.id == entry.contractor_id).first()
            if not contractor:
                continue

            to_email = draft.get("to_email", contractor.email).replace("\xa0", "").strip()
            to_name = draft.get("to_name", contractor.name).replace("\xa0", " ").strip()

            resend_id = send_email_via_gmail(to_email, to_name, subject, body)

            entry.status = "sent"
            entry.sent_at = _dt.utcnow()
            task.status = "outreach_sent"

            db.add(Email(
                task_id=task.id,
                contractor_id=contractor.id,
                direction="outbound",
                subject=subject,
                body=body,
                to_email=to_email,
                resend_id=resend_id,
            ))
            db.add(AgentAction(
                project_id=project_id,
                task_id=task.id,
                agent_mode="email_drafter",
                action_type="send_email",
                description=f"Sent outreach to {to_name}: \"{subject}\"",
            ))

        db.commit()
        print(f"[OUTREACH] Sent initial outreach for project {project_id}")
    except Exception as e:
        print(f"[OUTREACH] Error sending outreach: {e}")
    finally:
        db.close()


@router.post("/confirm-assignments")
def confirm_assignments(data: AssignContractorsRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == data.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    project.status = "active"
    db.commit()

    background_tasks.add_task(_send_outreach_for_assigned, project.id, project.name)

    return {"project_id": project.id, "status": project.status}


@router.post("/run-outreach")
def run_outreach(data: RunOutreachRequest, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == data.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    user_msg = (
        f"Send outreach emails for all assigned tasks in project ID {project.id} ({project.name}). "
        f"Only send to tasks with status 'assigned' that haven't been emailed yet."
    )
    result = run_agent("email_drafter", user_msg)
    return {"project_id": project.id, "result": result}


@router.post("/check-status")
def check_status(data: CheckStatusRequest, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == data.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    user_msg = f"Evaluate the current health of project ID {project.id} ({project.name}) and flag any issues."
    result = run_agent("status_monitor", user_msg)
    return {"project_id": project.id, "result": result}


@router.post("/inject-reply")
def inject_reply(data: ProcessReplyRequest, background_tasks: BackgroundTasks):
    """Save inbound email and process it asynchronously. Returns immediately so the UI doesn't hang."""
    import os, httpx

    def _run():
        port = int(os.getenv("APP_PORT", 8000))
        try:
            httpx.post(
                f"http://localhost:{port}/api/agent/process-reply",
                json={"from_email": data.from_email, "subject": data.subject, "body": data.body},
                timeout=180.0,
            )
        except Exception as e:
            print(f"[INJECT] Background processing error: {e}")

    background_tasks.add_task(_run)
    return {"status": "queued"}


@router.post("/process-reply")
def process_reply(data: ProcessReplyRequest, db: Session = Depends(get_db)):
    user_msg = (
        f"Process this inbound email reply:\n"
        f"From: {data.from_email}\n"
        f"Subject: {data.subject}\n"
        f"Body:\n{data.body}\n\n"
        f"Determine the contractor's intent and update the system accordingly."
    )

    # Try to extract task_id from subject
    import re
    task_match = re.search(r"\[SUP-(\d+)\]", data.subject)
    if task_match:
        task_id = int(task_match.group(1))
        task = db.query(Task).filter(Task.id == task_id).first()
        if task:
            user_msg += f"\nThis is regarding task ID {task_id} ({task.name}) in project ID {task.project_id}."

            # Log the inbound email (skip if already exists from simulator)
            contractor = get_contractor_by_email(db, data.from_email)
            existing = db.query(Email).filter(
                Email.direction == "inbound",
                Email.task_id == task_id,
                Email.from_email == data.from_email,
                Email.body == data.body,
            ).first()
            if not existing:
                inbound = Email(
                    task_id=task_id,
                    contractor_id=contractor.id if contractor else None,
                    direction="inbound",
                    subject=data.subject,
                    body=data.body,
                    from_email=data.from_email,
                    processed=True,  # already being processed — prevent scheduler from re-processing
                )
                db.add(inbound)
                db.commit()

            # Check for an active termination flow for this task
            term_flow = db.query(TerminationFlow).filter(
                TerminationFlow.task_id == task_id,
                TerminationFlow.status == "replacement_outreach_sent",
            ).first()
            if term_flow:
                user_msg += (
                    f"\nIMPORTANT: A termination flow (ID: {term_flow.id}) is active for this task "
                    f"in 'replacement_outreach_sent' status. If the contractor is confirming availability, "
                    f"call advance_termination_flow({term_flow.id}, 'replacement_confirmed')."
                )

    # Snapshot task state BEFORE processing to detect what changed
    pre_status = None
    pre_dates_confirmed = None
    if task_match:
        task_id = int(task_match.group(1))
        pre_task = db.query(Task).filter(Task.id == task_id).first()
        if pre_task:
            pre_status = pre_task.status
            pre_dates_confirmed = pre_task.dates_confirmed

    result = run_agent("reply_processor", user_msg)

    # After reply processing, check for post-processing actions
    if task_match:
        task_id = int(task_match.group(1))

        # --- Detect what changed ---
        db.expire_all()
        task_after = db.query(Task).filter(Task.id == task_id).first()
        status_changed = task_after and task_after.status != pre_status
        dates_just_confirmed = task_after and task_after.dates_confirmed and not pre_dates_confirmed

        # --- Helper: find the contractor for this task ---
        def _get_task_contractor(tid):
            oq = db.query(OutreachQueue).filter(
                OutreachQueue.task_id == tid,
                OutreachQueue.status.in_(["sent", "accepted"]),
            ).first()
            if oq:
                return db.query(Contractor).filter(Contractor.id == oq.contractor_id).first()
            return get_contractor_by_email(db, data.from_email)

        # --- 3. Reschedule downstream if dates changed ---
        db.expire_all()
        task_for_dates = db.query(Task).filter(Task.id == task_id).first()
        if task_for_dates and (task_for_dates.scheduled_start or task_for_dates.scheduled_end):
            _reschedule_downstream(db, task_id)

        # --- 4. Date negotiation cascade ---
        db.expire_all()
        task_for_dates = db.query(Task).filter(Task.id == task_id).first()
        if task_for_dates:
            # After acceptance: if task is committed + dates not confirmed + upstream confirmed → trigger date negotiator
            if task_for_dates.status == "committed" and not task_for_dates.dates_confirmed and pre_status != "committed":
                upstream_ok = True
                if task_for_dates.depends_on_task:
                    upstream = db.query(Task).filter(Task.id == task_for_dates.depends_on_task).first()
                    if upstream and not upstream.dates_confirmed:
                        upstream_ok = False
                if upstream_ok:
                    project = db.query(Project).filter(Project.id == task_for_dates.project_id).first()
                    outreach = db.query(OutreachQueue).filter(
                        OutreachQueue.task_id == task_id,
                        OutreachQueue.status.in_(["sent", "accepted"]),
                    ).first()
                    contractor = db.query(Contractor).filter(Contractor.id == outreach.contractor_id).first() if outreach else None
                    if contractor and project:
                        run_agent(
                            "date_negotiator",
                            f"Propose scheduled dates to contractor {contractor.name} (email: {contractor.email}, "
                            f"contractor ID: {contractor.id}) for task ID {task_id} ({task_for_dates.name}) "
                            f"in project ID {project.id} ({project.name}). "
                            f"Scheduled: {task_for_dates.scheduled_start} to {task_for_dates.scheduled_end}."
                        )
                        print(f"[DATE-NEGOTIATION] Triggered for task {task_id} ({task_for_dates.name})")

            # After date confirmation: find downstream tasks that are committed + dates not confirmed → trigger
            if dates_just_confirmed:
                downstream_tasks = db.query(Task).filter(
                    Task.depends_on_task == task_id,
                    Task.status == "committed",
                    Task.dates_confirmed == False,
                ).all()
                for dt in downstream_tasks:
                    project = db.query(Project).filter(Project.id == dt.project_id).first()
                    dt_outreach = db.query(OutreachQueue).filter(
                        OutreachQueue.task_id == dt.id,
                        OutreachQueue.status.in_(["sent", "accepted"]),
                    ).first()
                    dt_contractor = db.query(Contractor).filter(Contractor.id == dt_outreach.contractor_id).first() if dt_outreach else None
                    if dt_contractor and project:
                        run_agent(
                            "date_negotiator",
                            f"Propose scheduled dates to contractor {dt_contractor.name} (email: {dt_contractor.email}, "
                            f"contractor ID: {dt_contractor.id}) for task ID {dt.id} ({dt.name}) "
                            f"in project ID {project.id} ({project.name}). "
                            f"Scheduled: {dt.scheduled_start} to {dt.scheduled_end}. "
                            f"Upstream task '{task_for_dates.name}' dates are now confirmed through {task_for_dates.scheduled_end}."
                        )
                        print(f"[DATE-NEGOTIATION] Cascade triggered for downstream task {dt.id} ({dt.name})")

        # Check if a termination flow was just confirmed → run executor stage 2
        confirmed_flow = db.query(TerminationFlow).filter(
            TerminationFlow.task_id == task_id,
            TerminationFlow.status == "replacement_confirmed",
            TerminationFlow.termination_sent_at == None,
        ).first()
        if confirmed_flow:
            run_agent(
                "termination_executor",
                f"Execute stage 2: send termination notice and confirm new contract for termination flow ID {confirmed_flow.id}."
            )

        # Check if contractor declined → auto-assign next contractor and send outreach
        db.expire_all()
        task = db.query(Task).filter(Task.id == task_id).first()
        if task and task.status == "assigned":
            # The reply processor sets status back to 'assigned' on decline.
            # Check if the declining contractor's outreach was marked declined.
            declined = db.query(OutreachQueue).filter(
                OutreachQueue.task_id == task_id,
                OutreachQueue.status == "declined",
            ).first()
            if not declined:
                # Also check: if status is 'assigned' but contractor just replied,
                # this was likely a decline that reset the status
                contractor = get_contractor_by_email(db, data.from_email)
                if contractor:
                    oq = db.query(OutreachQueue).filter(
                        OutreachQueue.task_id == task_id,
                        OutreachQueue.contractor_id == contractor.id,
                    ).first()
                    if oq:
                        oq.status = "declined"
                        db.commit()
                        declined = oq

            if declined:
                # Find next available contractor for this specialty
                from services.contractor_service import get_contractors_by_specialty
                already_tried = [
                    o.contractor_id for o in
                    db.query(OutreachQueue).filter(OutreachQueue.task_id == task_id).all()
                ]
                candidates = get_contractors_by_specialty(db, task.specialty_needed)
                next_contractor = next(
                    (c for c in candidates if c.id not in already_tried), None
                )

                # If everyone's been tried, cycle back to the top of the list
                if not next_contractor and candidates:
                    next_contractor = candidates[0]

                if next_contractor:
                    # Assign and send outreach to the replacement
                    new_entry = OutreachQueue(
                        task_id=task_id,
                        contractor_id=next_contractor.id,
                        priority_order=len(already_tried) + 1,
                    )
                    db.add(new_entry)
                    db.commit()

                    project = db.query(Project).filter(Project.id == task.project_id).first()
                    run_agent(
                        "email_drafter",
                        f"Send an outreach email for task ID {task_id} ({task.name}) in project "
                        f"ID {project.id} ({project.name}) to contractor {next_contractor.name} "
                        f"(email: {next_contractor.email}, contractor ID: {next_contractor.id}). "
                        f"The previous contractor declined, so we need this replacement."
                    )
                    print(f"[AUTO-ESCALATION] Task {task_id}: {declined.contractor_id} declined → outreach sent to {next_contractor.name}")

    return {"result": result}


@router.post("/evaluate-termination")
def evaluate_termination(data: EvaluateTerminationRequest, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == data.task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    user_msg = (
        f"Evaluate whether contractor ID {data.contractor_id} should be terminated from "
        f"task ID {data.task_id} ('{task.name}') in project ID {task.project_id}. "
        f"Use get_project_context with project_id={task.project_id} and get_email_threads with task_id={data.task_id}. "
        f"The outgoing contractor ID is {data.contractor_id}."
    )
    if data.reason:
        user_msg += f"\nHint from superintendent: {data.reason}"

    result = run_agent("termination_advisor", user_msg)

    # Try to find the flow that was just created
    flow = db.query(TerminationFlow).filter(
        TerminationFlow.task_id == data.task_id,
        TerminationFlow.outgoing_contractor_id == data.contractor_id,
        TerminationFlow.status == "pending_approval",
    ).order_by(TerminationFlow.created_at.desc()).first()

    return {"flow_id": flow.id if flow else None, "summary": result}


@router.post("/approve-termination")
def approve_termination(data: ApproveTerminationRequest, db: Session = Depends(get_db)):
    flow = db.query(TerminationFlow).filter(TerminationFlow.id == data.flow_id).first()
    if not flow:
        raise HTTPException(status_code=404, detail="Termination flow not found")
    if flow.status != "pending_approval":
        raise HTTPException(status_code=400, detail=f"Flow is in status '{flow.status}', expected 'pending_approval'")

    flow.superintendent_approved_at = datetime.utcnow()
    db.commit()

    result = run_agent(
        "termination_executor",
        f"Execute stage 1: send replacement outreach for termination flow ID {flow.id}."
    )

    db.refresh(flow)
    return {"flow_id": flow.id, "status": flow.status, "result": result}


@router.post("/cancel-termination")
def cancel_termination(data: CancelTerminationRequest, db: Session = Depends(get_db)):
    flow = db.query(TerminationFlow).filter(TerminationFlow.id == data.flow_id).first()
    if not flow:
        raise HTTPException(status_code=404, detail="Termination flow not found")

    flow.status = "cancelled"
    flow.updated_at = datetime.utcnow()
    db.commit()

    return {"flow_id": flow.id, "status": "cancelled"}


@router.post("/demo-termination")
def demo_termination(data: DemoTerminationRequest, db: Session = Depends(get_db)):
    """Run a full termination demo: pick a committed contractor, fire them, simulate responses, generate summary."""
    import random
    from agent.tools import create_termination_flow as _create_flow, advance_termination_flow as _advance, get_contractor_roster as _roster

    # Find a task with an assigned/committed contractor
    task = (
        db.query(Task).join(OutreachQueue, OutreachQueue.task_id == Task.id)
        .filter(Task.project_id == data.project_id, Task.status.in_(["committed", "outreach_sent", "assigned"]))
        .first()
    )
    if not task:
        raise HTTPException(status_code=400, detail="No suitable task found. Assign contractors first.")

    outreach = db.query(OutreachQueue).filter(
        OutreachQueue.task_id == task.id,
        OutreachQueue.priority_order == 1
    ).first()
    if not outreach:
        raise HTTPException(status_code=400, detail="No contractor assigned to task.")

    outgoing = db.query(Contractor).filter(Contractor.id == outreach.contractor_id).first()
    project = db.query(Project).filter(Project.id == data.project_id).first()

    # Find best replacement (different contractor, same specialty)
    roster = _roster(task.specialty_needed)
    replacements = [c for c in roster if c["id"] != outgoing.id]
    if not replacements:
        raise HTTPException(status_code=400, detail="No replacement contractor available with matching specialty.")
    incoming_data = replacements[0]
    incoming = db.query(Contractor).filter(Contractor.id == incoming_data["id"]).first()

    # Step 1: Create termination flow
    reason = (
        f"{outgoing.name} confirmed the start date but has been completely unresponsive for 4 days — "
        f"no replies to follow-up emails or calls. The project schedule is at risk of slipping."
    )
    flow_result = _create_flow(
        task_id=task.id,
        outgoing_contractor_id=outgoing.id,
        incoming_contractor_id=incoming.id,
        reason=reason,
    )
    flow_id = flow_result["flow_id"]

    # Step 2: Superintendent approves (simulated)
    flow = db.query(TerminationFlow).filter(TerminationFlow.id == flow_id).first()
    flow.superintendent_approved_at = datetime.utcnow()
    db.commit()

    # Step 3: Executor stage 1 — email replacement contractor
    run_agent("termination_executor", f"Execute stage 1: send replacement outreach for termination flow ID {flow_id}.")

    # Step 4: Simulate replacement confirming availability
    _advance(flow_id, "replacement_confirmed")

    # Simulate incoming contractor's acceptance email
    accept_body = (
        f"Hi Cliff,\n\nThank you for reaching out! I'd be happy to take on the {task.name} work for {project.name}. "
        f"I'm available and can start as soon as needed. Please send over any details and I'll make it happen.\n\n"
        f"Looking forward to working with you.\n\nBest,\n{incoming.name}"
    )
    db.add(Email(
        task_id=task.id,
        contractor_id=incoming.id,
        direction="inbound",
        subject=f"Re: [SUP-{task.id}] {task.name} - Availability Inquiry - {project.name}",
        body=accept_body,
        from_email=incoming.email,
    ))
    db.commit()

    # Step 5: Executor stage 2 — send termination notice + confirm new contractor
    run_agent("termination_executor", f"Execute stage 2: send termination notice and confirm new contract for termination flow ID {flow_id}.")

    # Step 6: Simulate the fired contractor's reply (random emotional response)
    fired_replies = [
        (
            "This is absolutely unacceptable! I cleared my entire schedule for this job. "
            "You can't just terminate me over an email with no phone call first. "
            "50% is not enough — I expect full payment or I will be consulting my attorney. "
            "Do not contact me further until this is resolved properly."
        ),
        (
            f"Hi Cliff, I owe you an apology. I had a serious family emergency and completely dropped the ball on communication. "
            f"I understand if you've moved on, but is there any chance we can work something out? "
            f"I'm available now and would really like to make this right. "
            f"If not, I understand — just let me know about the 50% payment timeline."
        ),
        (
            "Message received. I accept the termination. "
            "Please confirm the 50% payment will be processed to my account on file within 30 days. "
            "It's been a pleasure working with you in the past and I hope we can work together again in the future."
        ),
        (
            "Wait — what?! I've been trying to reach you all week! My emails must have been going to spam. "
            "I am ready to start right now. Can we please get on a call today? "
            "I really don't want to lose this contract — I've already ordered materials."
        ),
        (
            "Cliff, I'm very disappointed. I've been a reliable contractor for years and this feels like a blindside. "
            "I did reach out twice but got no response from your side either. "
            "I'll accept the 50% but I want it on record that this communication went both ways. "
            "Please send payment details when ready."
        ),
    ]
    fired_body = random.choice(fired_replies)
    fired_subject = f"Re: [SUP-{task.id}] {task.name} - {project.name} - Contract Termination"

    db.add(Email(
        task_id=task.id,
        contractor_id=outgoing.id,
        direction="inbound",
        subject=fired_subject,
        body=fired_body,
        from_email=outgoing.email,
    ))
    db.commit()

    # Step 7: AI processes the fired contractor's reply
    run_agent("reply_processor", (
        f"Process this inbound email from a terminated contractor:\n"
        f"From: {outgoing.email}\n"
        f"Subject: {fired_subject}\n"
        f"Body:\n{fired_body}\n\n"
        f"This is regarding task ID {task.id} ({task.name}) in project ID {project.id}. "
        f"IMPORTANT: This contractor has been terminated from this task. "
        f"Respond professionally and appropriately to whatever tone they take."
    ))

    # Step 8: Mark flow complete
    _advance(flow_id, "complete")

    # Step 9: Generate executive summary
    summary = run_agent("termination_summarizer", f"Generate an executive summary for termination flow ID {flow_id}.")

    return {
        "flow_id": flow_id,
        "task_name": task.name,
        "outgoing_contractor": outgoing.name,
        "incoming_contractor": incoming.name,
        "fired_reply_preview": fired_body[:120] + "...",
        "summary_preview": summary[:300] + "..." if len(summary) > 300 else summary,
    }
