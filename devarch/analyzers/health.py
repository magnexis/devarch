from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class HealthMetrics:
    score: int
    status: str
    warnings: list[str]
    debt_estimate: float


def calculate_health(
    *,
    total_files: int,
    dead_code_count: int,
    duplicate_count: int,
    ancient_count: int,
    todo_count: int,
    monster_count: int,
    ruin_count: int,
    suspicious_count: int,
) -> HealthMetrics:
    debt = (
        dead_code_count * 2.0
        + duplicate_count * 1.5
        + ancient_count * 1.2
        + todo_count * 0.35
        + monster_count * 2.5
        + ruin_count * 0.8
        + suspicious_count * 0.6
    )
    if total_files:
        debt += min(total_files / 250.0, 10.0)
    score = max(0, min(100, int(round(100 - debt))))
    if score >= 85:
        status = "Healthy"
    elif score >= 65:
        status = "Moderate debt"
    elif score >= 45:
        status = "Debt detected"
    else:
        status = "Critical"

    warnings: list[str] = []
    if dead_code_count:
        warnings.append("Dead code candidates detected")
    if duplicate_count:
        warnings.append("Duplicate implementations found")
    if ancient_count:
        warnings.append("Ancient files appear abandoned")
    if monster_count:
        warnings.append("Monster files need review")
    if ruin_count:
        warnings.append("Empty structures or unused assets found")
    if suspicious_count:
        warnings.append("Suspicious filenames found")
    return HealthMetrics(score=score, status=status, warnings=warnings, debt_estimate=debt)

