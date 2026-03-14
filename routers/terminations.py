from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import TerminationFlow
from schemas import TerminationFlowOut

router = APIRouter(prefix="/api/terminations", tags=["terminations"])


@router.get("/{flow_id}", response_model=TerminationFlowOut)
def get_termination_flow(flow_id: int, db: Session = Depends(get_db)):
    flow = db.query(TerminationFlow).filter(TerminationFlow.id == flow_id).first()
    if not flow:
        raise HTTPException(status_code=404, detail="Termination flow not found")
    return flow
