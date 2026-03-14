from fastapi import APIRouter, Depends, HTTPException, Form, UploadFile, File
from sqlalchemy.orm import Session
from typing import Optional
from datetime import date
from database import get_db
from models import Project, Task, Alert
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


@router.delete("/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    db.delete(project)
    db.commit()
    return {"deleted": True}
