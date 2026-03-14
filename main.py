"""Superintendent AI — FastAPI app, DB init, routes, scheduler startup."""
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

from database import Base, engine, get_db
from models import Project, Task, Alert, Email, Contractor, OutreachQueue
from seed import seed_contractors
from services.email_service import poll_gmail_inbox

load_dotenv()

# --- Scheduler ---
scheduler = BackgroundScheduler()


def scheduled_poll_emails():
    """Poll Gmail inbox for replies."""
    from agent.agent import run_agent
    replies = poll_gmail_inbox()
    for reply in replies:
        if reply.get("task_id"):
            msg = (
                f"Process this inbound email reply:\n"
                f"From: {reply['from_email']}\n"
                f"Subject: {reply['subject']}\n"
                f"Body:\n{reply['body']}\n\n"
                f"This is regarding task ID {reply['task_id']}."
            )
            run_agent("reply_processor", msg)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    Base.metadata.create_all(bind=engine)
    seed_contractors()

    # Start scheduler for Gmail polling
    gmail_user = os.getenv("GMAIL_USER")
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD")
    if gmail_user and gmail_pass and not gmail_pass.startswith("xxxx"):
        scheduler.add_job(scheduled_poll_emails, "interval", minutes=5, id="poll_emails")
        scheduler.start()
        print("Scheduler started: polling Gmail every 5 minutes.")
    else:
        print("Gmail not configured — email polling disabled.")

    yield

    # Shutdown
    if scheduler.running:
        scheduler.shutdown()


app = FastAPI(title="Superintendent AI", lifespan=lifespan)
templates = Jinja2Templates(directory="templates")

# --- Routers ---
from routers import projects, tasks, contractors, agent as agent_router

app.include_router(projects.router)
app.include_router(tasks.router)
app.include_router(contractors.router)
app.include_router(agent_router.router)


# --- UI Pages ---

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    projects_list = db.query(Project).order_by(Project.created_at.desc()).all()
    # Add task count to each project
    for p in projects_list:
        p.task_count = db.query(Task).filter(Task.project_id == p.id).count()

    alerts = db.query(Alert).filter(Alert.is_read == False).order_by(Alert.created_at.desc()).limit(10).all()
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
        else:
            t.contractor_name = None

    alerts = db.query(Alert).filter(Alert.project_id == project_id, Alert.is_read == False).order_by(Alert.created_at.desc()).all()
    emails_list = db.query(Email).filter(Email.task_id.in_([t.id for t in tasks_list])).order_by(Email.created_at.desc()).all()

    return templates.TemplateResponse("project_detail.html", {
        "request": request,
        "project": project,
        "tasks": tasks_list,
        "alerts": alerts,
        "emails": emails_list,
    })


@app.get("/contractors", response_class=HTMLResponse)
def contractors_page(request: Request, db: Session = Depends(get_db)):
    contractors_list = db.query(Contractor).order_by(Contractor.name).all()
    return templates.TemplateResponse("contractors.html", {"request": request, "contractors": contractors_list})


@app.get("/emails", response_class=HTMLResponse)
def emails_page(request: Request, db: Session = Depends(get_db)):
    emails_list = db.query(Email).order_by(Email.created_at.desc()).all()
    return templates.TemplateResponse("email_log.html", {"request": request, "emails": emails_list})


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("APP_PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
