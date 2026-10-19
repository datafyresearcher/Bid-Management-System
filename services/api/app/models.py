from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.db import Base


def now():
    return datetime.utcnow()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String(200), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    role = Column(String(50), nullable=False, default="viewer")
    password_hash = Column(String(400), nullable=False)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now)


class Source(Base):
    __tablename__ = "sources"
    id = Column(Integer, primary_key=True)
    code = Column(String(80), unique=True, nullable=False)
    name = Column(String(250), nullable=False)
    country = Column(String(10), default="PK")
    area = Column(String(80), default="")
    type = Column(String(40), default="portal")
    adapter = Column(String(80), nullable=False)
    url = Column(String(500), default="")
    schedule_hours = Column(Integer, default=24)
    enabled = Column(Boolean, default=True)
    approved = Column(Boolean, default=True)
    health = Column(String(30), default="ok")
    last_scan_at = Column(DateTime)
    last_scan_stats = Column(JSON)
    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now, onupdate=now)


class CategoryMapping(Base):
    __tablename__ = "category_mappings"
    id = Column(Integer, primary_key=True)
    source_code = Column(String(80), nullable=False)
    source_category = Column(String(200), nullable=False)
    internal_category = Column(String(120), nullable=False)
    __table_args__ = (UniqueConstraint("source_code", "source_category", name="uq_cat_map"),)


class RawSnapshot(Base):
    __tablename__ = "raw_snapshots"
    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False)
    native_id = Column(String(200), index=True)
    url = Column(String(800))
    kind = Column(String(40), default="listing")
    content_hash = Column(String(64))
    content = Column(Text)
    meta = Column(JSON)
    fetched_at = Column(DateTime, default=now)
    parser_version = Column(String(20), default="v1")
    processed = Column(Boolean, default=False)
    opportunity_id = Column(Integer, ForeignKey("opportunities.id"))


class Opportunity(Base):
    __tablename__ = "opportunities"
    id = Column(Integer, primary_key=True)
    dedup_key = Column(String(400), index=True)
    country = Column(String(10), default="PK")
    area = Column(String(80), default="")
    city = Column(String(120), default="")
    category_internal = Column(String(120), default="General")
    category_source = Column(String(200), default="")
    tender_type = Column(String(60), default="Works")
    procurement_regime = Column(String(120), default="")
    contract_family = Column(String(120), default="")
    source_kind = Column(String(40), default="portal")
    buyer_name = Column(String(300), default="")
    buyer_ref = Column(String(200), default="")
    title = Column(String(600), nullable=False)
    description = Column(Text, default="")
    estimated_value = Column(Float)
    currency = Column(String(10), default="PKR")
    value_band = Column(String(40), default="unknown")
    published_at = Column(DateTime)
    clarification_deadline = Column(DateTime)
    submission_deadline = Column(DateTime)
    opening_at = Column(DateTime)
    pec_category_required = Column(String(40), default="")
    specialization = Column(String(200), default="")
    prequal_required = Column(Boolean, default=False)
    qualification_thresholds = Column(JSON)
    bid_security_amount = Column(Float)
    bid_security_form = Column(String(200), default="")
    tender_fee = Column(Float)
    notice_status = Column(String(40), default="Published")
    state = Column(String(40), default="NEW", index=True)
    source_refs = Column(JSON, default=list)
    lead_id = Column(Integer, ForeignKey("leads.id"))
    score_total = Column(Float)
    hard_gate_result = Column(JSON)
    ai_rationale = Column(Text, default="")
    documents_status = Column(String(40), default="none")
    submission_mode = Column(String(40), default="assisted")
    abandoned_reason = Column(String(200), default="")
    checklist = Column(JSON)
    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now, onupdate=now)

    documents = relationship("Document", backref="opportunity", cascade="all, delete-orphan")
    requirements = relationship("ExtractedRequirement", backref="opportunity", cascade="all, delete-orphan")
    risk_flags = relationship("RiskFlag", backref="opportunity", cascade="all, delete-orphan")
    gate_tasks = relationship("GateTask", backref="opportunity", cascade="all, delete-orphan")
    compliance_items = relationship("ComplianceItem", backref="opportunity", cascade="all, delete-orphan")
    workflow_events = relationship("WorkflowEvent", backref="opportunity", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True)
    opportunity_id = Column(Integer, ForeignKey("opportunities.id"), nullable=False)
    filename = Column(String(400), nullable=False)
    doc_type = Column(String(60), default="unknown")
    file_path = Column(String(600), default="")
    size = Column(Integer, default=0)
    pages = Column(Integer)
    parsed = Column(Boolean, default=False)
    parse_status = Column(String(200), default="")
    content_text = Column(Text)
    created_at = Column(DateTime, default=now)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    opportunity_id = Column(Integer, ForeignKey("opportunities.id"), index=True)
    chunk_index = Column(Integer, default=0)
    text = Column(Text, nullable=False)
    anchor = Column(String(120), default="")
    created_at = Column(DateTime, default=now)


class ExtractedRequirement(Base):
    __tablename__ = "extracted_requirements"
    id = Column(Integer, primary_key=True)
    opportunity_id = Column(Integer, ForeignKey("opportunities.id"), nullable=False)
    category = Column(String(60), default="compliance")
    text = Column(Text, nullable=False)
    anchor = Column(String(160), default="")
    mandatory = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now)


class RiskFlag(Base):
    __tablename__ = "risk_flags"
    id = Column(Integer, primary_key=True)
    opportunity_id = Column(Integer, ForeignKey("opportunities.id"), nullable=False)
    severity = Column(String(20), default="Medium")
    category = Column(String(80), default="")
    title = Column(String(300), nullable=False)
    detail = Column(Text, default="")
    anchor = Column(String(160), default="")
    suggested_action = Column(String(300), default="")
    created_at = Column(DateTime, default=now)


class Score(Base):
    __tablename__ = "scores"
    id = Column(Integer, primary_key=True)
    opportunity_id = Column(Integer, ForeignKey("opportunities.id"), nullable=False)
    total = Column(Float, default=0)
    subscores = Column(JSON)
    hard_gates = Column(JSON)
    rationale = Column(Text, default="")
    provider = Column(String(40), default="mock")
    prompt_version = Column(String(40), default="score-v1")
    created_at = Column(DateTime, default=now)


class ComplianceItem(Base):
    __tablename__ = "compliance_items"
    id = Column(Integer, primary_key=True)
    opportunity_id = Column(Integer, ForeignKey("opportunities.id"), nullable=False)
    requirement = Column(Text, nullable=False)
    category = Column(String(60), default="compliance")
    anchor = Column(String(160), default="")
    evidence_type = Column(String(30), default="none")
    evidence_ref = Column(String(300), default="")
    status = Column(String(20), default="TBD", index=True)
    owner = Column(String(120), default="")
    notes = Column(Text, default="")
    mandatory = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now, onupdate=now)


class GateTask(Base):
    __tablename__ = "gate_tasks"
    id = Column(Integer, primary_key=True)
    opportunity_id = Column(Integer, ForeignKey("opportunities.id"), nullable=False)
    gate = Column(Integer, nullable=False)
    title = Column(String(300), nullable=False)
    owner_role = Column(String(50), default="bid_manager")
    owner_user_id = Column(Integer, ForeignKey("users.id"))
    status = Column(String(20), default="PENDING", index=True)
    sla_hours = Column(Integer, default=24)
    due_at = Column(DateTime)
    decision = Column(String(40), default="")
    reason_code = Column(String(80), default="")
    comment = Column(Text, default="")
    decided_by = Column(Integer, ForeignKey("users.id"))
    decided_at = Column(DateTime)
    inputs_snapshot = Column(JSON)
    created_at = Column(DateTime, default=now)


class WorkflowEvent(Base):
    __tablename__ = "workflow_events"
    id = Column(Integer, primary_key=True)
    opportunity_id = Column(Integer, ForeignKey("opportunities.id"), nullable=False)
    from_state = Column(String(40), default="")
    to_state = Column(String(40), nullable=False)
    trigger = Column(String(120), default="")
    actor = Column(String(120), default="system")
    detail = Column(Text, default="")
    created_at = Column(DateTime, default=now)


class DecisionAudit(Base):
    __tablename__ = "decision_audits"
    id = Column(Integer, primary_key=True)
    opportunity_id = Column(Integer, ForeignKey("opportunities.id"))
    gate_task_id = Column(Integer, ForeignKey("gate_tasks.id"))
    actor = Column(String(200), default="system")
    action = Column(String(120), nullable=False)
    detail = Column(JSON)
    created_at = Column(DateTime, default=now)


class NotificationEvent(Base):
    __tablename__ = "notification_events"
    id = Column(Integer, primary_key=True)
    type = Column(String(60), nullable=False)
    severity = Column(String(20), default="info")
    title = Column(String(300), nullable=False)
    body = Column(Text, default="")
    opportunity_id = Column(Integer, ForeignKey("opportunities.id"))
    read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=now)


class AIMetric(Base):
    __tablename__ = "ai_metrics"
    id = Column(Integer, primary_key=True)
    opportunity_id = Column(Integer, ForeignKey("opportunities.id"))
    task = Column(String(40), nullable=False)
    provider = Column(String(40), default="mock")
    model = Column(String(120), default="")
    tokens_estimate = Column(Integer, default=0)
    latency_ms = Column(Integer, default=0)
    output_valid = Column(Boolean, default=True)
    human_override = Column(Boolean, default=False)
    correction_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=now)


class Lead(Base):
    __tablename__ = "leads"
    id = Column(Integer, primary_key=True)
    source_code = Column(String(40), default="L1")
    source_label = Column(String(200), default="")
    buyer = Column(String(300), default="")
    title = Column(String(500), nullable=False)
    description = Column(Text, default="")
    category_internal = Column(String(120), default="General")
    area = Column(String(80), default="")
    expected_window = Column(String(60), default="")
    estimated_value = Column(Float)
    currency = Column(String(10), default="PKR")
    confidence_tier = Column(String(20), default="Medium")
    confidence_note = Column(String(300), default="")
    status = Column(String(30), default="Signal", index=True)
    evidence = Column(JSON)
    converted_opportunity_id = Column(Integer, ForeignKey("opportunities.id"))
    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now, onupdate=now)


class CompanyProfile(Base):
    __tablename__ = "company_profile"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    legal_name = Column(String(300), default="")
    secp = Column(String(120), default="")
    ntn = Column(String(120), default="")
    tax_status = Column(String(80), default="Active")
    address = Column(String(400), default="")
    country = Column(String(10), default="PK")
    website = Column(String(300), default="")
    summary = Column(Text, default="")
    blacklisted = Column(Boolean, default=False)
    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now, onupdate=now)


class License(Base):
    __tablename__ = "licenses"
    id = Column(Integer, primary_key=True)
    authority = Column(String(80), default="PEC")
    number = Column(String(120), default="")
    category = Column(String(40), default="C-A")
    fields = Column(JSON)
    issued_at = Column(DateTime)
    expires_at = Column(DateTime)
    file_path = Column(String(600), default="")
    approved = Column(Boolean, default=True)


class FinancialYear(Base):
    __tablename__ = "financial_years"
    id = Column(Integer, primary_key=True)
    fiscal_year = Column(String(20), nullable=False)
    turnover = Column(Float, default=0)
    net_worth = Column(Float, default=0)
    profit = Column(Float, default=0)
    currency = Column(String(10), default="PKR")
    auditor = Column(String(200), default="")
    bank_lines = Column(JSON)
    bonding_capacity = Column(Float)
    file_path = Column(String(600), default="")
    approved = Column(Boolean, default=False)


class ProjectExperience(Base):
    __tablename__ = "project_experiences"
    id = Column(Integer, primary_key=True)
    contract_no = Column(String(200), default="")
    client = Column(String(300), default="")
    scope = Column(Text, default="")
    category = Column(String(120), default="")
    value = Column(Float)
    currency = Column(String(10), default="PKR")
    country = Column(String(10), default="PK")
    area = Column(String(80), default="")
    start_date = Column(String(40), default="")
    end_date = Column(String(40), default="")
    role = Column(String(60), default="Sole")
    funding_source = Column(String(120), default="")
    certificate_ref = Column(String(200), default="")
    keywords = Column(String(400), default="")
    performance_note = Column(String(400), default="")
    approved = Column(Boolean, default=False)
    file_path = Column(String(600), default="")


class Personnel(Base):
    __tablename__ = "personnel"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    position = Column(String(200), default="")
    pec_reg_no = Column(String(120), default="")
    years_experience = Column(Integer, default=0)
    education = Column(String(300), default="")
    key_projects = Column(Text, default="")
    certifications = Column(JSON)
    availability = Column(String(100), default="")
    approved = Column(Boolean, default=False)
    cv_path = Column(String(600), default="")


class EquipmentItem(Base):
    __tablename__ = "equipment_items"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    category = Column(String(120), default="")
    spec = Column(String(300), default="")
    quantity = Column(Integer, default=1)
    ownership = Column(String(40), default="Owned")
    year = Column(Integer)
    condition = Column(String(60), default="Good")
    location = Column(String(200), default="")
    available_from = Column(String(40), default="")
    approved = Column(Boolean, default=False)


class CompanyCertificate(Base):
    __tablename__ = "company_certificates"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    issuer = Column(String(200), default="")
    number = Column(String(120), default="")
    valid_from = Column(String(40), default="")
    expires_at = Column(DateTime)
    file_path = Column(String(600), default="")
    approved = Column(Boolean, default=False)


class LibraryDocument(Base):
    __tablename__ = "library_documents"
    id = Column(Integer, primary_key=True)
    title = Column(String(300), nullable=False)
    type = Column(String(60), default="policy")
    tags = Column(String(300), default="")
    file_path = Column(String(600), default="")
    content_text = Column(Text, default="")
    approved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=now)


class Proposal(Base):
    __tablename__ = "proposals"
    id = Column(Integer, primary_key=True)
    opportunity_id = Column(Integer, ForeignKey("opportunities.id"), nullable=False, unique=True)
    status = Column(String(30), default="DRAFT")
    version = Column(Integer, default=1)
    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now, onupdate=now)
    sections = relationship("ProposalSection", backref="proposal", cascade="all, delete-orphan")


class ProposalSection(Base):
    __tablename__ = "proposal_sections"
    id = Column(Integer, primary_key=True)
    proposal_id = Column(Integer, ForeignKey("proposals.id"), nullable=False)
    key = Column(String(80), nullable=False)
    title = Column(String(300), nullable=False)
    content = Column(Text, default="")
    status = Column(String(20), default="DRAFTED")
    citations = Column(JSON, default=list)
    order_index = Column(Integer, default=0)
    updated_at = Column(DateTime, default=now, onupdate=now)


class SubmissionRecord(Base):
    __tablename__ = "submission_records"
    id = Column(Integer, primary_key=True)
    opportunity_id = Column(Integer, ForeignKey("opportunities.id"), nullable=False)
    status = Column(String(30), default="DRAFT")
    checklist = Column(JSON)
    pack_files = Column(JSON)
    portal_note = Column(Text, default="")
    submitted_at = Column(DateTime)
    proof_path = Column(String(600), default="")
    blocked_reason = Column(String(300), default="")
    created_at = Column(DateTime, default=now)


class Outcome(Base):
    __tablename__ = "outcomes"
    id = Column(Integer, primary_key=True)
    opportunity_id = Column(Integer, ForeignKey("opportunities.id"), nullable=False, unique=True)
    result = Column(String(30), nullable=False)
    reason_code = Column(String(80), default="")
    comment = Column(Text, default="")
    competitor_note = Column(Text, default="")
    award_value = Column(Float)
    recorded_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=now)
