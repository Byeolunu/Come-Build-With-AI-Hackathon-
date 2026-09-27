"""Normalized catalog models for CivicPilot opportunities.

Keep these records separate from the vector chunks: catalog fields are used for
exact filtering and eligibility checks, while chunks are used for explanation.
"""

from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class OpportunityRecord(BaseModel):
    program_id: str
    name: str
    organization: str
    country: str = "MA"
    regions: list[str] = Field(default_factory=list)
    support_types: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)
    amount: float | None = None
    currency: str | None = None
    deadline: date | None = None
    status: str = "UNKNOWN"
    requirements: list[dict[str, Any]] = Field(default_factory=list)
    required_documents: list[str] = Field(default_factory=list)
    repayment: dict[str, Any] = Field(default_factory=dict)
    official_url: str
    source_title: str
    source_language: str | None = None
    source_document_key: str | None = None
    last_verified: date | None = None

