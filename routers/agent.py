from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from database import get_db
from models import Project, Email, Task, OutreachQueue, TerminationFlow, Contractor
from schemas import GeneratePlanRequest, AssignContractorsRequest, RunOutreachRequest, CheckStatusRequest, ProcessReplyRequest, EvaluateTerminationRequest, ApproveTerminationRequest, CancelTerminationRequest, TerminationFlowOut, DemoTerminationRequest, RegenerateTasksRequest, ReassignContractorsRequest
from agent.agent import run_agent, generate_tasks_direct
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


@router.post("/generate-plan")
def generate_plan(data: GeneratePlanRequest, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == data.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    user_msg = _build_plan_user_msg(project)
    task_dicts = generate_tasks_direct(user_msg)
    task_list = _save_tasks_from_dicts(db, project.id, task_dicts)
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
    task_dicts = generate_tasks_direct(user_msg)
    task_list = _save_tasks_from_dicts(db, project.id, task_dicts)
    return {"project_id": project.id, "tasks": task_list}


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

    user_msg = (
        f"Assign contractors to all unassigned tasks for project ID {project.id} ({project.name})."
        f"\nUser feedback: {data.feedback}\nPlease revise accordingly."
    )
    run_agent("contractor_assigner", user_msg)

    return {"project_id": project.id, "assignments": _build_assignment_list(db, project.id)}


@router.post("/confirm-assignments")
def confirm_assignments(data: AssignContractorsRequest, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == data.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    project.status = "active"
    db.commit()

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

            # Log the inbound email
            contractor = get_contractor_by_email(db, data.from_email)
            inbound = Email(
                task_id=task_id,
                contractor_id=contractor.id if contractor else None,
                direction="inbound",
                subject=data.subject,
                body=data.body,
                from_email=data.from_email,
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

    result = run_agent("reply_processor", user_msg)

    # After reply processing, check if a flow was just confirmed → run executor stage 2
    if task_match:
        task_id = int(task_match.group(1))
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
