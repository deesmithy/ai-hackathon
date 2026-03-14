"""Contractor query helpers."""
from sqlalchemy.orm import Session
from models import Contractor


def get_all_contractors(db: Session, active_only: bool = True):
    query = db.query(Contractor)
    if active_only:
        query = query.filter(Contractor.active == True)
    return query.order_by(Contractor.name).all()


def get_contractors_by_specialty(db: Session, specialty: str):
    return (
        db.query(Contractor)
        .filter(Contractor.active == True, Contractor.specialty == specialty)
        .order_by(
            (Contractor.rating_reliability + Contractor.rating_quality).desc()
        )
        .all()
    )


def get_contractor_by_id(db: Session, contractor_id: int):
    return db.query(Contractor).filter(Contractor.id == contractor_id).first()


def get_contractor_by_email(db: Session, email: str):
    return db.query(Contractor).filter(Contractor.email == email).first()
