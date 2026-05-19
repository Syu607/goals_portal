from __future__ import annotations

from dataclasses import dataclass

from app.models import Goal


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    message: str = ""


def validate_goals(goals: list[Goal]) -> ValidationResult:
    if len(goals) == 0:
        return ValidationResult(ok=False, message="Add at least 1 goal before submitting.")
    if len(goals) > 8:
        return ValidationResult(ok=False, message="Maximum number of goals per employee is 8.")
    for g in goals:
        if g.weightage < 10:
            return ValidationResult(ok=False, message="Minimum weightage per individual goal is 10%.")
    total = sum(g.weightage for g in goals)
    if total != 100:
        return ValidationResult(ok=False, message=f"Total weightage across all goals must equal 100%. Current total is {total}%.")
    return ValidationResult(ok=True)
