from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import Project, Email, Task, OutreachQueue
from schemas import GeneratePlanRequest, AssignContractorsRequest, RunOutreachRequest, CheckStatusRequest, ProcessReplyRequest
from agent.agent import run_agent
from services.contractor_service import get_contractor_by_email

router = APIRouter(prefix="/api/agent", tags=["agent"])


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

    result = run_agent("reply_processor", user_msg)
    return {"result": result}
