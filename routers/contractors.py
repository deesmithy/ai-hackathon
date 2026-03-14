from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import Contractor
from schemas import ContractorCreate, ContractorOut

router = APIRouter(prefix="/api/contractors", tags=["contractors"])


@router.get("/", response_model=list[ContractorOut])
def list_contractors(db: Session = Depends(get_db)):
    return db.query(Contractor).order_by(Contractor.name).all()


@router.post("/", response_model=ContractorOut)
def create_contractor(data: ContractorCreate, db: Session = Depends(get_db)):
    contractor = Contractor(**data.model_dump())
    db.add(contractor)
    db.commit()
    db.refresh(contractor)
    return contractor


@router.get("/{contractor_id}", response_model=ContractorOut)
def get_contractor(contractor_id: int, db: Session = Depends(get_db)):
    contractor = db.query(Contractor).filter(Contractor.id == contractor_id).first()
    if not contractor:
        raise HTTPException(status_code=404, detail="Contractor not found")
    return contractor


@router.delete("/{contractor_id}")
def deactivate_contractor(contractor_id: int, db: Session = Depends(get_db)):
    contractor = db.query(Contractor).filter(Contractor.id == contractor_id).first()
    if not contractor:
        raise HTTPException(status_code=404, detail="Contractor not found")
    contractor.active = False
    db.commit()
    return {"deactivated": True}
