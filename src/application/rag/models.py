from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SupportType(StrEnum):
    GRANT = "grant"
    LOAN = "loan"
    TRAINING = "training"
    MENTORSHIP = "mentorship"
    EMPLOYMENT_SUPPORT = "employment_support"


class DocumentType(StrEnum):
    OPPORTUNITY = "OPPORTUNITY"
    PROGRAM = "PROGRAM"
    TRAINING = "TRAINING"
    GUIDANCE = "GUIDANCE"
    POLICY = "POLICY"
    RESEARCH = "RESEARCH"
    GENERAL_INFORMATION = "GENERAL_INFORMATION"


class ProgramStatus(StrEnum):
    ACTIVE_CONFIRMED = "ACTIVE_CONFIRMED"
    ACTIVE_UNCONFIRMED = "ACTIVE_UNCONFIRMED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


class UserProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    personal: dict[str, Any] = Field(default_factory=lambda: {"age": None, "gender": None, "country": None, "region": None, "city": None})
    employment: dict[str, Any] = Field(default_factory=lambda: {"status": None, "occupation": None})
    goal: dict[str, Any] = Field(default_factory=lambda: {"type": None, "sector": None, "description": None, "stage": None})
    financial_need: dict[str, Any] = Field(default_factory=lambda: {"amount": None, "currency": None, "purpose": None})
    business: dict[str, Any] = Field(default_factory=lambda: {"existing": None, "has_business_plan": None, "has_business_registration": None})
    experience: dict[str, Any] = Field(default_factory=lambda: {"relevant_experience": None, "skills": []})
    eligibility: dict[str, Any] = Field(
        default_factory=lambda: {"student": None, "low_income": None, "disability": None, "refugee": None, "rural_resident": None}
    )
    constraints: dict[str, Any] = Field(default_factory=lambda: {"cannot_take_debt": None, "other": []})
    missing_information: list[str] = Field(default_factory=list)


class SourceMetadata(BaseModel):
    source_url: str
    source_title: str
    organization: str
    source_type: str
    publication_date: date | None = None
    last_updated: date | None = None
    retrieved_at: date | None = None
    last_verified: date | None = None
    language: str | None = None
    country: str | None = None
    program_id: str
    document_type: DocumentType


class ProgramRecord(BaseModel):
    program_id: str
    name: str
    organization: str
    source: SourceMetadata
    geographic_scope: dict[str, list[str]] = Field(default_factory=lambda: {"countries": [], "regions": []})
    target_groups: list[str] = Field(default_factory=list)
    support_type: list[SupportType] = Field(default_factory=list)
    sector: list[str] = Field(default_factory=list)
    eligibility: dict[str, Any] = Field(default_factory=dict)
    funding: dict[str, Any] = Field(default_factory=dict)
    application: dict[str, Any] = Field(default_factory=dict)
    status: ProgramStatus = ProgramStatus.UNKNOWN


class RequirementStatus(StrEnum):
    MATCHED = "MATCHED"
    MISSING = "MISSING"
    NOT_MATCHED = "NOT_MATCHED"


class RequirementEvaluation(BaseModel):
    requirement: str
    status: RequirementStatus
    evidence_source: str | None = None


class EvidenceClaim(BaseModel):
    claim: str
    claim_type: str
    source_url: str
    source_title: str
    source_type: str
    page: int | None = None
    section: str | None = None


class EvidenceChunk(BaseModel):
    chunk_id: str
    program_id: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
