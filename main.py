"""Superintendent AI — FastAPI app, DB init, routes, scheduler startup."""
from __future__ import annotations
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

from database import Base, engine, get_db
from models import Project, Task, Alert, Email, Contractor, OutreachQueue, TerminationFlow, AgentAction
from seed import seed_contractors
from services.email_service import poll_gmail_inbox

load_dotenv()

# --- Scheduler ---
scheduler = BackgroundScheduler()


def scheduled_poll_emails():
    """Poll DB for inbound emails and process them through the full reply pipeline."""
    import httpx
    replies = poll_gmail_inbox()
    port = int(os.getenv("APP_PORT", 8000))
    for reply in replies:
        msg = (
            f"Process this inbound email:\n"
            f"From: {reply['from_email']}\n"
            f"Subject: {reply['subject']}\n"
            f"Body:\n{reply['body']}\n\n"
        )
        if reply.get("task_id"):
            try:
                httpx.post(
                    f"http://localhost:{port}/api/agent/process-reply",
                    json={
                        "from_email": reply["from_email"],
                        "subject": reply["subject"],
                        "body": reply["body"],
                    },
                    timeout=120.0,
                )
            except Exception as e:
                print(f"[POLL] Error processing reply: {e}")


def scheduled_simulate_replies():
    """Auto-generate contractor replies for any unreplied outbound emails."""
    try:
        from simulate_replies import run_once
        run_once()
    except Exception as e:
        print(f"[SIM] Error in auto-reply: {e}")


def scheduled_daily_status_sweep():
    """Run status_monitor on every active project once a day."""
    from agent.agent import run_agent
    db = next(get_db())
    try:
        active_projects = db.query(Project).filter(Project.status.in_(["active", "behind", "at_risk"])).all()
        for project in active_projects:
            msg = f"Evaluate the current health of project ID {project.id} ({project.name}) and flag any issues. Recommend terminations if warranted."
            run_agent("status_monitor", msg)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    Base.metadata.create_all(bind=engine)
    seed_contractors()

    # Daily status sweep — runs every morning at 8am regardless of Gmail config
    scheduler.add_job(scheduled_daily_status_sweep, "cron", hour=8, minute=0, id="daily_status_sweep")
    scheduler.start()
    print("Scheduler started: daily status sweep at 8am.")

    # Poll DB for inbound emails and process them through the reply pipeline
    scheduler.add_job(scheduled_poll_emails, "interval", seconds=8, id="poll_emails")
    print("Inbound email polling enabled: every 8 seconds.")

    yield

    # Shutdown
    if scheduler.running:
        scheduler.shutdown()


app = FastAPI(title="Superintendent AI", lifespan=lifespan)
templates = Jinja2Templates(directory="templates")


def _extract_flow_id(message: str) -> int | None:
    import re
    m = re.search(r"Flow ID: (\d+)", message)
    return int(m.group(1)) if m else None


templates.env.filters["extract_flow_id"] = _extract_flow_id

# --- Routers ---
from routers import projects, tasks, contractors, agent as agent_router, terminations as terminations_router

app.include_router(projects.router)
app.include_router(tasks.router)
app.include_router(contractors.router)
app.include_router(agent_router.router)
app.include_router(terminations_router.router)


# --- UI Pages ---

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    projects_list = db.query(Project).order_by(Project.created_at.desc()).all()
    # Add task count to each project
    for p in projects_list:
        p.task_count = db.query(Task).filter(Task.project_id == p.id).count()

    alerts = db.query(Alert).filter(Alert.is_read == False, Alert.alert_type != "risk").order_by(Alert.created_at.desc()).limit(10).all()
    return templates.TemplateResponse("index.html", {"request": request, "projects": projects_list, "alerts": alerts})


@app.get("/projects/new", response_class=HTMLResponse)
def new_project_page(request: Request):
    return templates.TemplateResponse("new_project.html", {"request": request})


@app.get("/projects/{project_id}", response_class=HTMLResponse)
def project_detail_page(project_id: int, request: Request, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return HTMLResponse("<h1>Not Found</h1>", status_code=404)

    tasks_list = db.query(Task).filter(Task.project_id == project_id).order_by(Task.sequence_order).all()

    # Attach contractor name to each task
    for t in tasks_list:
        outreach = db.query(OutreachQueue).filter(
            OutreachQueue.task_id == t.id,
            OutreachQueue.priority_order == 1
        ).first()
        if outreach:
            contractor = db.query(Contractor).filter(Contractor.id == outreach.contractor_id).first()
            t.contractor_name = contractor.name if contractor else None
            t.outreach_status = outreach.status  # pending / sent / accepted / declined / no_response
        else:
            t.contractor_name = None
            t.outreach_status = None

    alerts = db.query(Alert).filter(Alert.project_id == project_id, Alert.is_read == False).order_by(Alert.created_at.desc()).all()

    # Build email threads grouped by task → contractor
    task_ids = [t.id for t in tasks_list]
    all_emails = db.query(Email).filter(Email.task_id.in_(task_ids)).order_by(Email.created_at).all()

    threads = {}  # key: (task_id, contractor_id)
    for e in all_emails:
        key = (e.task_id, e.contractor_id)
        if key not in threads:
            task = next((t for t in tasks_list if t.id == e.task_id), None)
            contractor = db.query(Contractor).filter(Contractor.id == e.contractor_id).first() if e.contractor_id else None
            threads[key] = {
                "task_id": e.task_id,
                "task_name": task.name if task else "Unknown Task",
                "task_sequence_order": task.sequence_order if task else 9999,
                "contractor_name": contractor.name if contractor else "Unknown",
                "contractor_email": contractor.email if contractor else "",
                "emails": [],
            }
        threads[key]["emails"].append(e)

    email_threads = sorted(threads.values(), key=lambda t: t["task_sequence_order"])

    # Fetch termination flows for this project
    termination_flows = (
        db.query(TerminationFlow)
        .join(Task, Task.id == TerminationFlow.task_id)
        .filter(Task.project_id == project_id)
        .order_by(TerminationFlow.created_at.desc())
        .all()
    )
    # Enrich with names
    for f in termination_flows:
        t = db.query(Task).get(f.task_id)
        f.task_name = t.name if t else "Unknown"
        outgoing = db.query(Contractor).get(f.outgoing_contractor_id)
        f.outgoing_name = outgoing.name if outgoing else "Unknown"
        incoming = db.query(Contractor).get(f.incoming_contractor_id)
        f.incoming_name = incoming.name if incoming else "Unknown"

    agent_actions = (
        db.query(AgentAction)
        .filter(AgentAction.project_id == project_id)
        .order_by(AgentAction.created_at.desc())
        .limit(200)
        .all()
    )

    return templates.TemplateResponse("project_detail.html", {
        "request": request,
        "project": project,
        "tasks": tasks_list,
        "alerts": alerts,
        "email_threads": email_threads,
        "termination_flows": termination_flows,
        "agent_actions": agent_actions,
    })


@app.get("/projects/{project_id}/inject-email", response_class=HTMLResponse)
def inject_email_page(project_id: int, request: Request, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return HTMLResponse("<h1>Not Found</h1>", status_code=404)

    tasks_list = db.query(Task).filter(Task.project_id == project_id).order_by(Task.sequence_order).all()

    # Attach assigned contractor to each task
    task_contractors = []
    for t in tasks_list:
        outreach = db.query(OutreachQueue).filter(
            OutreachQueue.task_id == t.id,
            OutreachQueue.status.in_(["sent", "accepted"]),
        ).order_by(OutreachQueue.priority_order).first()
        contractor = db.query(Contractor).filter(Contractor.id == outreach.contractor_id).first() if outreach else None
        task_contractors.append({
            "task": t,
            "contractor": contractor,
        })

    return templates.TemplateResponse("inject_email.html", {
        "request": request,
        "project": project,
        "task_contractors": task_contractors,
    })


@app.get("/progress/{project_id}", response_class=HTMLResponse)
def buyer_progress_page(project_id: int, request: Request, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return HTMLResponse("<h1>Not Found</h1>", status_code=404)

    tasks_list = db.query(Task).filter(Task.project_id == project_id).order_by(Task.sequence_order).all()

    return templates.TemplateResponse("buyer_progress.html", {
        "request": request,
        "project": project,
        "tasks": tasks_list,
    })


@app.get("/contractors", response_class=HTMLResponse)
def contractors_page(request: Request, db: Session = Depends(get_db)):
    contractors_list = db.query(Contractor).order_by(Contractor.name).all()
    return templates.TemplateResponse("contractors.html", {"request": request, "contractors": contractors_list})


@app.get("/emails", response_class=HTMLResponse)
def emails_page(request: Request, db: Session = Depends(get_db)):
    all_emails = db.query(Email).order_by(Email.created_at).all()

    # Build threads grouped by task → contractor
    threads = {}
    for e in all_emails:
        key = (e.task_id, e.contractor_id)
        if key not in threads:
            task = db.query(Task).filter(Task.id == e.task_id).first() if e.task_id else None
            contractor = db.query(Contractor).filter(Contractor.id == e.contractor_id).first() if e.contractor_id else None
            project = db.query(Project).filter(Project.id == task.project_id).first() if task else None
            threads[key] = {
                "task_id": e.task_id,
                "task_name": task.name if task else "General",
                "contractor_name": contractor.name if contractor else "Unknown",
                "contractor_email": contractor.email if contractor else "",
                "project_name": project.name if project else "",
                "project_id": project.id if project else None,
                "emails": [],
            }
        threads[key]["emails"].append(e)

    email_threads = sorted(threads.values(), key=lambda t: t["emails"][-1].created_at, reverse=True)

    # Flat list stats
    total = len(all_emails)
    outbound = sum(1 for e in all_emails if e.direction == "outbound")
    inbound = total - outbound

    return templates.TemplateResponse("email_log.html", {
        "request": request,
        "email_threads": email_threads,
        "total": total,
        "outbound": outbound,
        "inbound": inbound,
    })


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("APP_PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
