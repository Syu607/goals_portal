from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from app.models import Cycle, Quarter


@dataclass(frozen=True)
class Window:
    opens: date
    closes: date

    def is_open(self, on: date) -> bool:
        return self.opens <= on <= self.closes


def window_for_cycle(cycle: Cycle, quarter: Optional[Quarter]) -> Window:
    if quarter is None:
        opens = cycle.goal_setting_open
    elif quarter == Quarter.q1:
        opens = cycle.q1_open
    elif quarter == Quarter.q2:
        opens = cycle.q2_open
    elif quarter == Quarter.q3:
        opens = cycle.q3_open
    else:
        opens = cycle.q4_open
    closes = opens + timedelta(days=cycle.window_days)
    return Window(opens=opens, closes=closes)


def is_goal_setting_open(cycle: Cycle, on: date) -> bool:
    return window_for_cycle(cycle, None).is_open(on)


def is_quarter_open(cycle: Cycle, quarter: Quarter, on: date) -> bool:
    return window_for_cycle(cycle, quarter).is_open(on)
