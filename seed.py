"""Seed the database with fake contractors for demo purposes."""
from database import SessionLocal
from models import Contractor

SEED_CONTRACTORS = [
    {"name": "Mike Rodriguez", "email": "mike@example.com", "phone": "555-0101", "specialty": "framing", "rating": 5},
    {"name": "Sarah Chen", "email": "sarah@example.com", "phone": "555-0102", "specialty": "electrical", "rating": 5},
    {"name": "James Wilson", "email": "james@example.com", "phone": "555-0103", "specialty": "plumbing", "rating": 4},
    {"name": "Maria Garcia", "email": "maria@example.com", "phone": "555-0104", "specialty": "roofing", "rating": 5},
    {"name": "Tom Baker", "email": "tom@example.com", "phone": "555-0105", "specialty": "hvac", "rating": 4},
    {"name": "Lisa Park", "email": "lisa@example.com", "phone": "555-0106", "specialty": "painting", "rating": 5},
    {"name": "Dave Thompson", "email": "dave@example.com", "phone": "555-0107", "specialty": "concrete", "rating": 4},
    {"name": "Nina Patel", "email": "nina@example.com", "phone": "555-0108", "specialty": "drywall", "rating": 5},
    {"name": "Carlos Mendez", "email": "carlos@example.com", "phone": "555-0109", "specialty": "flooring", "rating": 4},
    {"name": "Amy Foster", "email": "amy@example.com", "phone": "555-0110", "specialty": "landscaping", "rating": 5},
]


def seed_contractors():
    db = SessionLocal()
    try:
        existing = db.query(Contractor).count()
        if existing > 0:
            print(f"Database already has {existing} contractors, skipping seed.")
            return
        for data in SEED_CONTRACTORS:
            db.add(Contractor(**data))
        db.commit()
        print(f"Seeded {len(SEED_CONTRACTORS)} contractors.")
    finally:
        db.close()


if __name__ == "__main__":
    from database import Base, engine
    Base.metadata.create_all(bind=engine)
    seed_contractors()
