from pydantic import BaseModel
from datetime import date, datetime
from typing import Optional


# --- Contractor ---
class ContractorCreate(BaseModel):
    name: str
    email: str
    phone: Optional[str] = None
    specialty: str
    rating_reliability: int = 3
    rating_price: int = 3
    rating_quality: int = 3

class ContractorOut(BaseModel):
    id: int
    name: str
    email: str
    phone: Optional[str]
    specialty: str
    rating_reliability: int
    rating_price: int
    rating_quality: int
    active: bool
    created_at: datetime
    class Config:
        from_attributes = True


# --- Project ---
class ProjectCreate(BaseModel):
    name: str
    description: str
    start_date: Optional[date] = None
    target_end_date: Optional[date] = None

class ProjectOut(BaseModel):
    id: int
    name: str
    description: str
    status: str
    ai_plan: Optional[str]
    start_date: Optional[date]
    target_end_date: Optional[date]
    created_at: datetime
    updated_at: datetime
    class Config:
        from_attributes = True


# --- Task ---
class TaskCreate(BaseModel):
    project_id: int
    name: str
    description: Optional[str] = None
    specialty_needed: Optional[str] = None
    estimated_days: Optional[int] = None
    sequence_order: int = 0
    depends_on_task: Optional[int] = None

class TaskUpdate(BaseModel):
    status: Optional[str] = None
    scheduled_start: Optional[date] = None
    scheduled_end: Optional[date] = None
    actual_start: Optional[date] = None
    actual_end: Optional[date] = None

class TaskOut(BaseModel):
    id: int
    project_id: int
    name: str
    description: Optional[str]
    specialty_needed: Optional[str]
    status: str
    sequence_order: int
    depends_on_task: Optional[int]
    estimated_days: Optional[int]
    scheduled_start: Optional[date]
    scheduled_end: Optional[date]
    actual_start: Optional[date]
    actual_end: Optional[date]
    created_at: datetime
    updated_at: datetime
    class Config:
        from_attributes = True


# --- Email ---
class EmailOut(BaseModel):
    id: int
    task_id: Optional[int]
    contractor_id: Optional[int]
    direction: str
    subject: Optional[str]
    body: Optional[str]
    from_email: Optional[str]
    to_email: Optional[str]
    created_at: datetime
    class Config:
        from_attributes = True


# --- Alert ---
class AlertOut(BaseModel):
    id: int
    project_id: int
    task_id: Optional[int]
    alert_type: str
    message: str
    is_read: bool
    created_at: datetime
    class Config:
        from_attributes = True


# --- Agent Requests ---
class GeneratePlanRequest(BaseModel):
    project_id: int

class AssignContractorsRequest(BaseModel):
    project_id: int

class RunOutreachRequest(BaseModel):
    project_id: int

class CheckStatusRequest(BaseModel):
    project_id: int

class ProcessReplyRequest(BaseModel):
    from_email: str
    subject: str
    body: str


# --- Termination ---
class EvaluateTerminationRequest(BaseModel):
    task_id: int
    contractor_id: int
    reason: Optional[str] = None

class ApproveTerminationRequest(BaseModel):
    flow_id: int

class CancelTerminationRequest(BaseModel):
    flow_id: int

class TerminationFlowOut(BaseModel):
    id: int
    task_id: int
    outgoing_contractor_id: int
    incoming_contractor_id: int
    reason: str
    status: str
    superintendent_approved_at: Optional[datetime]
    replacement_confirmed_at: Optional[datetime]
    termination_sent_at: Optional[datetime]
    created_at: datetime
    class Config:
        from_attributes = True
