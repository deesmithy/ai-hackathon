from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from database import get_db
from models import Project, Email, Task, OutreachQueue, TerminationFlow
from schemas import GeneratePlanRequest, AssignContractorsRequest, RunOutreachRequest, CheckStatusRequest, ProcessReplyRequest, EvaluateTerminationRequest, ApproveTerminationRequest, CancelTerminationRequest, TerminationFlowOut
from agent.agent import run_agent
from services.contractor_service import get_contractor_by_email

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/poll-inbox")
def poll_inbox():
    """Manually trigger a Gmail inbox poll and process any replies."""
    from main import scheduled_poll_emails
    scheduled_poll_emails()
    return {"status": "done"}


@router.post("/generate-plan")
def generate_plan(data: GeneratePlanRequest, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == data.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    user_msg = (
        f"Create a construction task plan for project ID {project.id}.\n"
        f"Project name: {project.name}\n"
        f"Description: {project.description}\n"
    )
    if project.start_date:
        user_msg += f"Start date: {project.start_date}\n"
    if project.target_end_date:
        user_msg += f"Target end date: {project.target_end_date}\n"

    result = run_agent("plan_generator", user_msg)

    # Save the plan text to the project
    project.ai_plan = result
    db.commit()

    return {"project_id": project.id, "plan": result}


@router.post("/assign-contractors")
def assign_contractors(data: AssignContractorsRequest, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == data.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    user_msg = f"Assign contractors to all unassigned tasks for project ID {project.id} ({project.name})."
    result = run_agent("contractor_assigner", user_msg)

    # Move project to active
    if project.status == "planning":
        project.status = "active"
        db.commit()

    return {"project_id": project.id, "result": result}


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
