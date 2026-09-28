from typing import Any, Literal

from pydantic import BaseModel, Field


class GenerateEmbeddingsInputSchema(BaseModel):
    url: str
    filterPath: str | None = None
    # Optional CivicPilot metadata copied to every embedded chunk.
    country: str | None = None
    language: str | None = None
    source_type: str = "official_web"
    support_types: list[str] = Field(default_factory=list)
    section: str | None = None
    source_title: str | None = None
    organization: str | None = None
    program_id: str | None = None
    last_verified: str | None = None


class GenerateEmbeddingsOutputSchema(BaseModel):
    state: str
    metadata: dict[str, Any]


class GenerateStatusOutputSchema(BaseModel):
    status: Literal["running", "idle"]
