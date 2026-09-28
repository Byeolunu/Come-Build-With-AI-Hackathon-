from collections.abc import Mapping
from typing import Any

from src.application.rag.models import RequirementEvaluation, RequirementStatus, UserProfile


def _lookup(profile: UserProfile, path: str) -> Any:
    value: Any = profile.model_dump()
    for part in path.split("."):
        if not isinstance(value, Mapping):
            return None
        value = value.get(part)
    return value


def evaluate_requirement(
    profile: UserProfile,
    *,
    path: str,
    requirement: str,
    expected: Any,
    evidence_source: str | None = None,
) -> RequirementEvaluation:
    """Compare explicit profile data with one source-backed requirement.

    Unknown profile values remain unknown and are never treated as false.
    """
    actual = _lookup(profile, path)
    if actual is None:
        status = RequirementStatus.MISSING
    elif isinstance(expected, tuple) and len(expected) == 2:  # noqa: PLR2004
        status = RequirementStatus.MATCHED if expected[0] <= actual <= expected[1] else RequirementStatus.NOT_MATCHED
    elif isinstance(expected, (list, set)):
        status = RequirementStatus.MATCHED if actual in expected else RequirementStatus.NOT_MATCHED
    else:
        status = RequirementStatus.MATCHED if actual == expected else RequirementStatus.NOT_MATCHED
    return RequirementEvaluation(requirement=requirement, status=status, evidence_source=evidence_source)


def evaluate_requirements(profile: UserProfile, requirements: list[dict[str, Any]]) -> list[RequirementEvaluation]:
    return [
        evaluate_requirement(
            profile,
            path=requirement["path"],
            requirement=requirement["requirement"],
            expected=requirement["expected"],
            evidence_source=requirement.get("evidence_source"),
        )
        for requirement in requirements
    ]
