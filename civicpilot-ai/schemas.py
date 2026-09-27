"""
Shared schema for a "case" — a person's situation used to match them against
funding/support programs. This mirrors the JSON structure provided by the
frontend exactly, so the API, the AI extractor, and the rules engine all
speak the same shape.
"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class Personal(BaseModel):
    age: Optional[int] = None
    country: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    language: Optional[str] = None  # "ar" | "fr" | "en" — detected from the user's message


class Employment(BaseModel):
    status: Optional[str] = None
    occupation: Optional[str] = None


class Goal(BaseModel):
    type: Optional[str] = None
    sector: Optional[str] = None
    description: Optional[str] = None
    stage: Optional[str] = None


class FinancialNeed(BaseModel):
    amount: Optional[float] = None
    currency: Optional[str] = None
    purpose: Optional[str] = None


class Business(BaseModel):
    existing: Optional[bool] = None
    has_business_plan: Optional[bool] = None
    has_business_registration: Optional[bool] = None


class Experience(BaseModel):
    relevant_experience: Optional[bool] = None
    skills: List[str] = Field(default_factory=list)


class Eligibility(BaseModel):
    student: Optional[bool] = None
    low_income: Optional[bool] = None
    disability: Optional[bool] = None
    refugee: Optional[bool] = None
    rural_resident: Optional[bool] = None


class Constraints(BaseModel):
    cannot_take_debt: Optional[bool] = None
    other: List[str] = Field(default_factory=list)


class Case(BaseModel):
    personal: Personal = Field(default_factory=Personal)
    employment: Employment = Field(default_factory=Employment)
    goal: Goal = Field(default_factory=Goal)
    financial_need: FinancialNeed = Field(default_factory=FinancialNeed)
    business: Business = Field(default_factory=Business)
    experience: Experience = Field(default_factory=Experience)
    eligibility: Eligibility = Field(default_factory=Eligibility)
    constraints: Constraints = Field(default_factory=Constraints)
    missing_information: List[str] = Field(default_factory=list)

    def compute_missing(self) -> List[str]:
        """Dotted-path list of every field that is still null/empty."""
        missing: List[str] = []
        data = self.model_dump()

        def walk(prefix: str, obj: Dict[str, Any]):
            for k, v in obj.items():
                if k == "missing_information":
                    continue
                path = f"{prefix}.{k}" if prefix else k
                if isinstance(v, dict):
                    walk(path, v)
                elif v is None or v == [] or v == "":
                    missing.append(path)

        walk("", data)
        return missing


def _deep_merge(base: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    """Merge two nested dicts. Values already present in `base` win;
    `incoming` (e.g. AI-extracted values) only fills genuine gaps."""
    result: Dict[str, Any] = {}
    keys = set(base.keys()) | set(incoming.keys())
    for k in keys:
        bv = base.get(k)
        iv = incoming.get(k)
        if isinstance(bv, dict) or isinstance(iv, dict):
            result[k] = _deep_merge(bv or {}, iv or {})
        else:
            if bv not in (None, [], ""):
                result[k] = bv
            else:
                result[k] = iv
    return result


def merge_case(base: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    return _deep_merge(base or {}, incoming or {})
