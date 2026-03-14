from fastapi import APIRouter, Depends, HTTPException, Form, UploadFile, File
from sqlalchemy.orm import Session
from typing import Optional
from datetime import date
from database import get_db
from models import Project, Task, Alert, OutreachQueue, Contractor
from schemas import ProjectOut

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("/", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    return db.query(Project).order_by(Project.created_at.desc()).all()


@router.post("/", response_model=ProjectOut)
async def create_project(
    name: str = Form(...),
    description: str = Form(...),
    start_date: Optional[str] = Form(None),
    target_end_date: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
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
        start_date=date.fromisoformat(start_date) if start_date else None,
        target_end_date=date.fromisoformat(target_end_date) if target_end_date else None,
        uploaded_file_content=uploaded_file_content,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.put("/{project_id}/status")
def update_project_status(project_id: int, status: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    project.status = status
    db.commit()
    return {"status": status}


@router.get("/{project_id}/live-status")
def project_live_status(project_id: int, db: Session = Depends(get_db)):
    """Live-polling endpoint: returns current task list with all display data."""
    tasks = db.query(Task).filter(Task.project_id == project_id).order_by(Task.sequence_order).all()
    result = []
    for t in tasks:
        outreach = db.query(OutreachQueue).filter(
            OutreachQueue.task_id == t.id,
            OutreachQueue.priority_order == 1,
        ).first()
        contractor = db.query(Contractor).filter(Contractor.id == outreach.contractor_id).first() if outreach else None
        result.append({
            "id": t.id,
            "sequence_order": t.sequence_order,
            "name": t.name,
            "description": t.description,
            "specialty_needed": t.specialty_needed,
            "status": t.status,
            "dates_confirmed": t.dates_confirmed,
            "estimated_days": t.estimated_days,
            "scheduled_start": t.scheduled_start.isoformat() if t.scheduled_start else None,
            "scheduled_end": t.scheduled_end.isoformat() if t.scheduled_end else None,
            "contractor_name": contractor.name if contractor else None,
        })
    return {"tasks": result}


@router.delete("/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    db.delete(project)
    db.commit()
    return {"deleted": True}
