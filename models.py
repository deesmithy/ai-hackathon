from datetime import datetime, date
from sqlalchemy import Column, Integer, String, Text, Date, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from database import Base


class Contractor(Base):
    __tablename__ = "contractors"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    phone = Column(String, nullable=True)
    specialty = Column(String, nullable=False)
    rating_reliability = Column(Integer, default=3)  # 1-5
    rating_price = Column(Integer, default=3)        # 1-5 (5 = most affordable)
    rating_quality = Column(Integer, default=3)      # 1-5
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    outreach_entries = relationship("OutreachQueue", back_populates="contractor")
    emails = relationship("Email", back_populates="contractor")


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    status = Column(String, default="planning")  # planning / active / behind / at_risk / complete
    ai_plan = Column(Text, nullable=True)
    uploaded_file_content = Column(Text, nullable=True)
    start_date = Column(Date, nullable=True)
    target_end_date = Column(Date, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tasks = relationship("Task", back_populates="project", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="project", cascade="all, delete-orphan")


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    specialty_needed = Column(String, nullable=True)
    status = Column(String, default="pending")  # pending / assigned / outreach_sent / committed / in_progress / complete / blocked
    sequence_order = Column(Integer, default=0)
    depends_on_task = Column(Integer, ForeignKey("tasks.id"), nullable=True)
    estimated_days = Column(Integer, nullable=True)
    scheduled_start = Column(Date, nullable=True)
    scheduled_end = Column(Date, nullable=True)
    actual_start = Column(Date, nullable=True)
    actual_end = Column(Date, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="tasks")
    outreach_entries = relationship("OutreachQueue", back_populates="task", cascade="all, delete-orphan")
    emails = relationship("Email", back_populates="task")
    dependency = relationship("Task", remote_side=[id])


class Email(Base):
    __tablename__ = "emails"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)
    contractor_id = Column(Integer, ForeignKey("contractors.id"), nullable=True)
    direction = Column(String, nullable=False)  # outbound / inbound
    subject = Column(String, nullable=True)
    body = Column(Text, nullable=True)
    resend_id = Column(String, nullable=True)
    from_email = Column(String, nullable=True)
    to_email = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    task = relationship("Task", back_populates="emails")
    contractor = relationship("Contractor", back_populates="emails")


class OutreachQueue(Base):
    __tablename__ = "outreach_queue"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    contractor_id = Column(Integer, ForeignKey("contractors.id"), nullable=False)
    priority_order = Column(Integer, default=1)
    status = Column(String, default="pending")  # pending / sent / accepted / declined / no_response
    sent_at = Column(DateTime, nullable=True)
    responded_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    task = relationship("Task", back_populates="outreach_entries")
    contractor = relationship("Contractor", back_populates="outreach_entries")


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)
    alert_type = Column(String, nullable=False)  # behind_schedule / no_response / task_blocked / risk / termination_recommendation
    message = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="alerts")


class TerminationFlow(Base):
    __tablename__ = "termination_flows"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    outgoing_contractor_id = Column(Integer, ForeignKey("contractors.id"), nullable=False)
    incoming_contractor_id = Column(Integer, ForeignKey("contractors.id"), nullable=False)
    reason = Column(Text, nullable=False)
    status = Column(String, default="pending_approval")
    # pending_approval → replacement_outreach_sent → replacement_confirmed
    # → termination_sent → complete | cancelled
    superintendent_approved_at = Column(DateTime, nullable=True)
    replacement_confirmed_at = Column(DateTime, nullable=True)
    termination_sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
