"""Seed the database with contractors for demo purposes."""
from database import SessionLocal
from models import Contractor

SEED_CONTRACTORS = [
    # --- Framing (3) ---
    {"name": "Mike Rodriguez", "email": "subcontractorpodiumhackathon+mikerodriguez@gmail.com", "phone": "555-0101", "specialty": "framing", "rating_reliability": 5, "rating_price": 3, "rating_quality": 5},
    {"name": "Jake Holloway", "email": "subcontractorpodiumhackathon+jakeholloway@gmail.com", "phone": "555-0201", "specialty": "framing", "rating_reliability": 4, "rating_price": 5, "rating_quality": 3},
    {"name": "Derek Nguyen", "email": "subcontractorpodiumhackathon+dereknguyen@gmail.com", "phone": "555-0301", "specialty": "framing", "rating_reliability": 3, "rating_price": 4, "rating_quality": 4},

    # --- Electrical (3) ---
    {"name": "Sarah Chen", "email": "subcontractorpodiumhackathon+sarahchen@gmail.com", "phone": "555-0102", "specialty": "electrical", "rating_reliability": 5, "rating_price": 2, "rating_quality": 5},
    {"name": "Ray Castillo", "email": "subcontractorpodiumhackathon+raycastillo@gmail.com", "phone": "555-0202", "specialty": "electrical", "rating_reliability": 4, "rating_price": 4, "rating_quality": 4},
    {"name": "Tanya Brooks", "email": "subcontractorpodiumhackathon+tanyabrooks@gmail.com", "phone": "555-0302", "specialty": "electrical", "rating_reliability": 3, "rating_price": 5, "rating_quality": 3},

    # --- Plumbing (3) ---
    {"name": "James Wilson", "email": "subcontractorpodiumhackathon+jameswilson@gmail.com", "phone": "555-0103", "specialty": "plumbing", "rating_reliability": 4, "rating_price": 3, "rating_quality": 5},
    {"name": "Angela Rivera", "email": "subcontractorpodiumhackathon+angelarivera@gmail.com", "phone": "555-0203", "specialty": "plumbing", "rating_reliability": 5, "rating_price": 4, "rating_quality": 4},
    {"name": "Pete Kowalski", "email": "subcontractorpodiumhackathon+petekowalski@gmail.com", "phone": "555-0303", "specialty": "plumbing", "rating_reliability": 3, "rating_price": 5, "rating_quality": 3},

    # --- Roofing (3) ---
    {"name": "Maria Garcia", "email": "subcontractorpodiumhackathon+mariagarcia@gmail.com", "phone": "555-0104", "specialty": "roofing", "rating_reliability": 5, "rating_price": 3, "rating_quality": 5},
    {"name": "Sam Okonkwo", "email": "subcontractorpodiumhackathon+samokonkwo@gmail.com", "phone": "555-0204", "specialty": "roofing", "rating_reliability": 4, "rating_price": 4, "rating_quality": 4},
    {"name": "Travis Lee", "email": "subcontractorpodiumhackathon+travislee@gmail.com", "phone": "555-0304", "specialty": "roofing", "rating_reliability": 3, "rating_price": 5, "rating_quality": 3},

    # --- HVAC (3) ---
    {"name": "Tom Baker", "email": "subcontractorpodiumhackathon+tombaker@gmail.com", "phone": "555-0105", "specialty": "hvac", "rating_reliability": 4, "rating_price": 3, "rating_quality": 5},
    {"name": "Diana Frost", "email": "subcontractorpodiumhackathon+dianafrost@gmail.com", "phone": "555-0205", "specialty": "hvac", "rating_reliability": 5, "rating_price": 4, "rating_quality": 4},
    {"name": "Marcus Young", "email": "subcontractorpodiumhackathon+marcusyoung@gmail.com", "phone": "555-0305", "specialty": "hvac", "rating_reliability": 3, "rating_price": 5, "rating_quality": 3},

    # --- Painting (3) ---
    {"name": "Lisa Park", "email": "subcontractorpodiumhackathon+lisapark@gmail.com", "phone": "555-0106", "specialty": "painting", "rating_reliability": 5, "rating_price": 3, "rating_quality": 5},
    {"name": "Chris Delgado", "email": "subcontractorpodiumhackathon+chrisdelgado@gmail.com", "phone": "555-0206", "specialty": "painting", "rating_reliability": 4, "rating_price": 5, "rating_quality": 3},
    {"name": "Jasmine Watts", "email": "subcontractorpodiumhackathon+jasminewatts@gmail.com", "phone": "555-0306", "specialty": "painting", "rating_reliability": 4, "rating_price": 4, "rating_quality": 4},

    # --- Concrete (3) ---
    {"name": "Dave Thompson", "email": "subcontractorpodiumhackathon+davethompson@gmail.com", "phone": "555-0107", "specialty": "concrete", "rating_reliability": 4, "rating_price": 3, "rating_quality": 5},
    {"name": "Omar Hassan", "email": "subcontractorpodiumhackathon+omarhassan@gmail.com", "phone": "555-0207", "specialty": "concrete", "rating_reliability": 5, "rating_price": 4, "rating_quality": 4},
    {"name": "Kelly Byrne", "email": "subcontractorpodiumhackathon+kellybyrne@gmail.com", "phone": "555-0307", "specialty": "concrete", "rating_reliability": 3, "rating_price": 5, "rating_quality": 3},

    # --- Drywall (3) ---
    {"name": "Nina Patel", "email": "subcontractorpodiumhackathon+ninapatel@gmail.com", "phone": "555-0108", "specialty": "drywall", "rating_reliability": 5, "rating_price": 3, "rating_quality": 5},
    {"name": "Ricky Tran", "email": "subcontractorpodiumhackathon+rickytran@gmail.com", "phone": "555-0208", "specialty": "drywall", "rating_reliability": 4, "rating_price": 5, "rating_quality": 3},
    {"name": "Heather Quinn", "email": "subcontractorpodiumhackathon+heatherquinn@gmail.com", "phone": "555-0308", "specialty": "drywall", "rating_reliability": 4, "rating_price": 4, "rating_quality": 4},

    # --- Flooring (3) ---
    {"name": "Carlos Mendez", "email": "subcontractorpodiumhackathon+carlosmendez@gmail.com", "phone": "555-0109", "specialty": "flooring", "rating_reliability": 4, "rating_price": 3, "rating_quality": 5},
    {"name": "Anna Johansson", "email": "subcontractorpodiumhackathon+annajohansson@gmail.com", "phone": "555-0209", "specialty": "flooring", "rating_reliability": 5, "rating_price": 4, "rating_quality": 4},
    {"name": "Leo Santana", "email": "subcontractorpodiumhackathon+leosantana@gmail.com", "phone": "555-0309", "specialty": "flooring", "rating_reliability": 3, "rating_price": 5, "rating_quality": 3},

    # --- Landscaping (3) ---
    {"name": "Amy Foster", "email": "subcontractorpodiumhackathon+amyfoster@gmail.com", "phone": "555-0110", "specialty": "landscaping", "rating_reliability": 5, "rating_price": 3, "rating_quality": 5},
    {"name": "Brandon Cho", "email": "subcontractorpodiumhackathon+brandoncho@gmail.com", "phone": "555-0210", "specialty": "landscaping", "rating_reliability": 4, "rating_price": 5, "rating_quality": 3},
    {"name": "Monica Reeves", "email": "subcontractorpodiumhackathon+monicareeves@gmail.com", "phone": "555-0310", "specialty": "landscaping", "rating_reliability": 4, "rating_price": 4, "rating_quality": 4},
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
