from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_role
from app.db import get_db
from app.models import (
    Cycle,
    Goal,
    GoalAchievement,
    GoalSheet,
    GoalSheetStatus,
    GoalStatus,
    Quarter,
    Role,
    UomType,
    User,
)
from app.services.goal_validation import validate_goals
from app.services.progress import compute_progress_score
from app.services.schedule import is_goal_setting_open, is_quarter_open, window_for_cycle
from app.templating import templates


router = APIRouter(prefix="/employee", tags=["employee"])


def _active_cycle(db: Session) -> Cycle:
    cycle = db.scalar(select(Cycle).where(Cycle.is_active == 1).order_by(Cycle.year.desc()))
    if cycle is None:
        raise HTTPException(status_code=500, detail="No active cycle configured.")
    return cycle


def _get_or_create_sheet(db: Session, *, employee: User, cycle: Cycle) -> GoalSheet:
    sheet = db.scalar(select(GoalSheet).where(GoalSheet.employee_id == employee.id, GoalSheet.cycle_id == cycle.id))
    if sheet is None:
        sheet = GoalSheet(employee_id=employee.id, cycle_id=cycle.id, status=GoalSheetStatus.draft, locked=0)
        db.add(sheet)
        db.commit()
        db.refresh(sheet)
    return sheet


@router.get("", response_class=HTMLResponse)
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.employee)),
) -> HTMLResponse:
    cycle = _active_cycle(db)
    sheet = _get_or_create_sheet(db, employee=user, cycle=cycle)
    goals = list(sheet.goals)
    weight_total = sum(g.weightage for g in goals)
    goal_setting_window = window_for_cycle(cycle, None)
    can_edit_goals = is_goal_setting_open(cycle, date.today()) and sheet.status == GoalSheetStatus.draft and sheet.locked == 0
    return templates.TemplateResponse(
        request,
        "employee_dashboard.html",
        {
            "request": request,
            "user": user,
            "cycle": cycle,
            "sheet": sheet,
            "goals": goals,
            "weight_total": weight_total,
            "can_edit_goals": can_edit_goals,
            "goal_setting_window": goal_setting_window,
            "Quarter": Quarter,
        },
    )


@router.post("/goals/add")
def add_goal(
    request: Request,
    thrust_area: str = Form(...),
    title: str = Form(...),
    description: str = Form(""),
    uom_type: UomType = Form(...),
    target_value: str = Form(...),
    weightage: int = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.employee)),
) -> RedirectResponse:
    cycle = _active_cycle(db)
    sheet = _get_or_create_sheet(db, employee=user, cycle=cycle)
    if sheet.locked or sheet.status != GoalSheetStatus.draft or not is_goal_setting_open(cycle, date.today()):
        raise HTTPException(status_code=403)
    if len(sheet.goals) >= 8:
        raise HTTPException(status_code=400, detail="Max 8 goals allowed.")
    if weightage < 10:
        raise HTTPException(status_code=400, detail="Min weightage is 10.")
    goal = Goal(
        sheet_id=sheet.id,
        thrust_area=thrust_area.strip(),
        title=title.strip(),
        description=description.strip(),
        uom_type=uom_type,
        target_value=target_value.strip(),
        weightage=weightage,
    )
    db.add(goal)
    db.commit()
    return RedirectResponse(url="/employee", status_code=303)


@router.post("/goals/{goal_id}/update")
def update_goal(
    goal_id: int,
    thrust_area: str = Form(""),
    title: str = Form(""),
    description: str = Form(""),
    uom_type: Optional[UomType] = Form(None),
    target_value: str = Form(""),
    weightage: int = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.employee)),
) -> RedirectResponse:
    cycle = _active_cycle(db)
    sheet = _get_or_create_sheet(db, employee=user, cycle=cycle)
    goal = db.scalar(select(Goal).where(Goal.id == goal_id, Goal.sheet_id == sheet.id))
    if goal is None:
        raise HTTPException(status_code=404)
    if sheet.locked or sheet.status != GoalSheetStatus.draft or not is_goal_setting_open(cycle, date.today()):
        raise HTTPException(status_code=403)
    if weightage < 10:
        raise HTTPException(status_code=400, detail="Min weightage is 10.")

    goal.weightage = weightage
    if goal.shared_group_id and goal.primary_owner_goal_id:
        db.commit()
        return RedirectResponse(url="/employee", status_code=303)

    goal.thrust_area = thrust_area.strip()
    goal.title = title.strip()
    goal.description = description.strip()
    if uom_type is not None:
        goal.uom_type = uom_type
    goal.target_value = target_value.strip()
    db.commit()
    return RedirectResponse(url="/employee", status_code=303)


@router.post("/goals/{goal_id}/delete")
def delete_goal(
    goal_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.employee)),
) -> RedirectResponse:
    cycle = _active_cycle(db)
    sheet = _get_or_create_sheet(db, employee=user, cycle=cycle)
    goal = db.scalar(select(Goal).where(Goal.id == goal_id, Goal.sheet_id == sheet.id))
    if goal is None:
        raise HTTPException(status_code=404)
    if sheet.locked or sheet.status != GoalSheetStatus.draft or not is_goal_setting_open(cycle, date.today()):
        raise HTTPException(status_code=403)
    if goal.shared_group_id and goal.primary_owner_goal_id:
        raise HTTPException(status_code=400, detail="Cannot delete a shared goal assigned to you.")
    db.delete(goal)
    db.commit()
    return RedirectResponse(url="/employee", status_code=303)


@router.post("/submit")
def submit_goals(
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.employee)),
) -> RedirectResponse:
    cycle = _active_cycle(db)
    sheet = _get_or_create_sheet(db, employee=user, cycle=cycle)
    if sheet.locked or sheet.status != GoalSheetStatus.draft or not is_goal_setting_open(cycle, date.today()):
        raise HTTPException(status_code=403)
    result = validate_goals(list(sheet.goals))
    if not result.ok:
        raise HTTPException(status_code=400, detail=result.message)
    sheet.status = GoalSheetStatus.submitted
    sheet.submitted_at = datetime.utcnow()
    db.commit()
    return RedirectResponse(url="/employee", status_code=303)


@router.get("/checkin/{quarter}", response_class=HTMLResponse)
def quarter_form(
    quarter: Quarter,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.employee)),
) -> HTMLResponse:
    cycle = _active_cycle(db)
    sheet = _get_or_create_sheet(db, employee=user, cycle=cycle)
    if sheet.status == GoalSheetStatus.draft:
        return RedirectResponse(url="/employee", status_code=303)
    is_open = is_quarter_open(cycle, quarter, date.today())
    goals = list(sheet.goals)
    goal_rows: list[dict] = []
    for g in goals:
        source_goal = g.primary_owner_goal if g.primary_owner_goal_id else g
        ach = db.scalar(select(GoalAchievement).where(GoalAchievement.goal_id == source_goal.id, GoalAchievement.quarter == quarter))
        goal_rows.append({"goal": g, "source_goal": source_goal, "achievement": ach})
    return templates.TemplateResponse(
        request,
        "employee_quarter.html",
        {
            "request": request,
            "user": user,
            "cycle": cycle,
            "sheet": sheet,
            "quarter": quarter,
            "is_open": is_open,
            "window": window_for_cycle(cycle, quarter),
            "goal_rows": goal_rows,
            "GoalStatus": GoalStatus,
        },
    )


@router.post("/checkin/{quarter}/goal/{goal_id}")
def update_achievement(
    quarter: Quarter,
    goal_id: int,
    status: GoalStatus = Form(...),
    actual_value: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.employee)),
) -> RedirectResponse:
    cycle = _active_cycle(db)
    sheet = _get_or_create_sheet(db, employee=user, cycle=cycle)
    if sheet.status == GoalSheetStatus.draft:
        raise HTTPException(status_code=403)
    if not is_quarter_open(cycle, quarter, date.today()):
        raise HTTPException(status_code=403, detail="Quarterly window is closed.")
    goal = db.scalar(select(Goal).where(Goal.id == goal_id, Goal.sheet_id == sheet.id))
    if goal is None:
        raise HTTPException(status_code=404)
    source_goal = goal.primary_owner_goal if goal.primary_owner_goal_id else goal
    ach = db.scalar(select(GoalAchievement).where(GoalAchievement.goal_id == source_goal.id, GoalAchievement.quarter == quarter))
    if ach is None:
        ach = GoalAchievement(
            goal_id=source_goal.id,
            quarter=quarter,
            status=status,
            actual_value=actual_value.strip(),
            progress_score=0,
            updated_at=datetime.utcnow(),
            updated_by_id=user.id,
        )
        db.add(ach)
    else:
        ach.status = status
        ach.actual_value = actual_value.strip()
        ach.updated_at = datetime.utcnow()
        ach.updated_by_id = user.id
    ach.progress_score = compute_progress_score(source_goal.uom_type, source_goal.target_value, ach.actual_value)
    db.commit()
    return RedirectResponse(url=f"/employee/checkin/{quarter.value}", status_code=303)
