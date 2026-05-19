from __future__ import annotations

from datetime import date

from app.models import UomType


def compute_progress_score(uom_type: UomType, target_value: str, actual_value: str) -> int:
    if uom_type in (UomType.min, UomType.max):
        target = _to_float(target_value)
        actual = _to_float(actual_value)
        if target is None or actual is None or target <= 0 or actual <= 0:
            return 0
        ratio = (actual / target) if uom_type == UomType.min else (target / actual)
        return _clamp_int(ratio * 100)

    if uom_type == UomType.timeline:
        deadline = _to_date(target_value)
        completion = _to_date(actual_value)
        if deadline is None or completion is None:
            return 0
        return 100 if completion <= deadline else 0

    if uom_type == UomType.zero:
        actual = _to_float(actual_value)
        if actual is None:
            return 0
        return 100 if actual == 0 else 0

    return 0


def _to_float(value: str) -> float | None:
    try:
        cleaned = value.strip().replace("%", "")
        if cleaned == "":
            return None
        return float(cleaned)
    except Exception:
        return None


def _to_date(value: str) -> date | None:
    try:
        v = value.strip()
        if v == "":
            return None
        return date.fromisoformat(v)
    except Exception:
        return None


def _clamp_int(v: float) -> int:
    if v != v:
        return 0
    if v < 0:
        return 0
    if v > 100:
        return 100
    return int(round(v))
