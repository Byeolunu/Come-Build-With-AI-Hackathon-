from src.application.rag.eligibility import evaluate_requirement
from src.application.rag.models import RequirementStatus, UserProfile


def test_requirement_status_preserves_unknown_values():
    profile = UserProfile(personal={"age": None})

    result = evaluate_requirement(
        profile,
        path="personal.age",
        requirement="Applicants must be 18 to 35 years old.",
        expected=(18, 35),
        evidence_source="https://official.example/eligibility",
    )

    assert result.status == RequirementStatus.MISSING
    assert result.evidence_source == "https://official.example/eligibility"


def test_requirement_status_matches_explicit_age_range():
    profile = UserProfile(personal={"age": 24})

    result = evaluate_requirement(profile, path="personal.age", requirement="Applicants must be 18 to 35 years old.", expected=(18, 35))

    assert result.status == RequirementStatus.MATCHED


def test_requirement_status_rejects_explicit_incompatible_value():
    profile = UserProfile(employment={"status": "employed"})

    result = evaluate_requirement(profile, path="employment.status", requirement="Applicants must be unemployed.", expected="unemployed")

    assert result.status == RequirementStatus.NOT_MATCHED


def test_sensitive_values_are_not_inferred():
    profile = UserProfile(eligibility={"low_income": None, "refugee": None})

    low_income = evaluate_requirement(profile, path="eligibility.low_income", requirement="Applicant must have low income.", expected=True)
    refugee = evaluate_requirement(profile, path="eligibility.refugee", requirement="Applicant must be a refugee.", expected=True)

    assert low_income.status == RequirementStatus.MISSING
    assert refugee.status == RequirementStatus.MISSING