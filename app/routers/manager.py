from __future__ import annotations

from datetime import date, datetime

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
    ManagerCheckIn,
    Quarter,
    Role,
    SharedGoalGroup,
    UomType,
    User,
)
from app.services.goal_validation import validate_goals
from app.services.schedule import is_quarter_open, window_for_cycle
from app.templating import templates


router = APIRouter(prefix="/manager", tags=["manager"])


def _active_cycle(db: Session) -> Cycle:
    cycle = db.scalar(select(Cycle).where(Cycle.is_active == 1).order_by(Cycle.year.desc()))
    if cycle is None:
        raise HTTPException(status_code=500, detail="No active cycle configured.")
    return cycle


def _team_members(db: Session, manager: User) -> list[User]:
    return list(db.scalars(select(User).where(User.manager_id == manager.id).order_by(User.full_name)))


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
    user: User = Depends(require_role(Role.manager)),
) -> HTMLResponse:
    cycle = _active_cycle(db)
    team = _team_members(db, user)
    sheets = {m.id: _get_or_create_sheet(db, employee=m, cycle=cycle) for m in team}
    return templates.TemplateResponse(
        "manager_dashboard.html",
        {"request": request, "user": user, "cycle": cycle, "team": team, "sheets": sheets, "Quarter": Quarter},
    )


@router.get("/sheet/{employee_id}", response_class=HTMLResponse)
def review_sheet(
    employee_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.manager)),
) -> HTMLResponse:
    cycle = _active_cycle(db)
    employee = db.scalar(select(User).where(User.id == employee_id, User.manager_id == user.id))
    if employee is None:
        raise HTTPException(status_code=404)
    sheet = _get_or_create_sheet(db, employee=employee, cycle=cycle)
    goals = list(sheet.goals)
    weight_total = sum(g.weightage for g in goals)
    return templates.TemplateResponse(
        "manager_sheet.html",
        {
            "request": request,
            "user": user,
            "cycle": cycle,
            "employee": employee,
            "sheet": sheet,
            "goals": goals,
            "weight_total": weight_total,
            "UomType": UomType,
        },
    )


@router.post("/sheet/{sheet_id}/goal/{goal_id}")
def manager_update_goal(
    sheet_id: int,
    goal_id: int,
    target_value: str = Form(""),
    weightage: int = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.manager)),
) -> RedirectResponse:
    cycle = _active_cycle(db)
    sheet = db.scalar(select(GoalSheet).where(GoalSheet.id == sheet_id, GoalSheet.cycle_id == cycle.id))
    if sheet is None:
        raise HTTPException(status_code=404)
    employee = db.scalar(select(User).where(User.id == sheet.employee_id, User.manager_id == user.id))
    if employee is None:
        raise HTTPException(status_code=403)
    if sheet.status != GoalSheetStatus.submitted or sheet.locked:
        raise HTTPException(status_code=400, detail="Sheet is not in submitted state.")
    goal = db.scalar(select(Goal).where(Goal.id == goal_id, Goal.sheet_id == sheet.id))
    if goal is None:
        raise HTTPException(status_code=404)
    if weightage < 10:
        raise HTTPException(status_code=400, detail="Min weightage is 10.")
    goal.weightage = weightage
    if not (goal.shared_group_id and goal.primary_owner_goal_id):
        goal.target_value = target_value.strip()
    db.commit()
    return RedirectResponse(url=f"/manager/sheet/{employee.id}", status_code=303)


@router.post("/sheet/{sheet_id}/return")
def return_for_rework(
    sheet_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.manager)),
) -> RedirectResponse:
    cycle = _active_cycle(db)
    sheet = db.scalar(select(GoalSheet).where(GoalSheet.id == sheet_id, GoalSheet.cycle_id == cycle.id))
    if sheet is None:
        raise HTTPException(status_code=404)
    employee = db.scalar(select(User).where(User.id == sheet.employee_id, User.manager_id == user.id))
    if employee is None:
        raise HTTPException(status_code=403)
    if sheet.status != GoalSheetStatus.submitted:
        raise HTTPException(status_code=400)
    sheet.status = GoalSheetStatus.draft
    sheet.locked = 0
    db.commit()
    return RedirectResponse(url=f"/manager/sheet/{employee.id}", status_code=303)


@router.post("/sheet/{sheet_id}/approve")
def approve_sheet(
    sheet_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.manager)),
) -> RedirectResponse:
    cycle = _active_cycle(db)
    sheet = db.scalar(select(GoalSheet).where(GoalSheet.id == sheet_id, GoalSheet.cycle_id == cycle.id))
    if sheet is None:
        raise HTTPException(status_code=404)
    employee = db.scalar(select(User).where(User.id == sheet.employee_id, User.manager_id == user.id))
    if employee is None:
        raise HTTPException(status_code=403)
    if sheet.status != GoalSheetStatus.submitted or sheet.locked:
        raise HTTPException(status_code=400)
    result = validate_goals(list(sheet.goals))
    if not result.ok:
        raise HTTPException(status_code=400, detail=result.message)
    sheet.status = GoalSheetStatus.approved
    sheet.locked = 1
    sheet.approved_by_id = user.id
    sheet.approved_at = datetime.utcnow()
    db.commit()
    return RedirectResponse(url=f"/manager/sheet/{employee.id}", status_code=303)


@router.get("/shared-goals", response_class=HTMLResponse)
def shared_goals_form(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.manager)),
) -> HTMLResponse:
    cycle = _active_cycle(db)
    team = _team_members(db, user)
    return templates.TemplateResponse(
        "manager_shared_goals.html",
        {"request": request, "user": user, "cycle": cycle, "team": team, "UomType": UomType},
    )


@router.post("/shared-goals/push")
def push_shared_goal(
    thrust_area: str = Form(...),
    title: str = Form(...),
    description: str = Form(""),
    uom_type: UomType = Form(...),
    target_value: str = Form(...),
    primary_owner_id: int = Form(...),
    recipient_ids: str = Form(...),
    default_weightage: int = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.manager)),
) -> RedirectResponse:
    cycle = _active_cycle(db)
    team_ids = {m.id for m in _team_members(db, user)}
    if primary_owner_id not in team_ids:
        raise HTTPException(status_code=400)
    try:
        selected = {int(x.strip()) for x in recipient_ids.split(",") if x.strip()}
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid recipient list.")
    if not selected.issubset(team_ids):
        raise HTTPException(status_code=400, detail="Recipients must be in your team.")
    if primary_owner_id not in selected:
        selected.add(primary_owner_id)
    if default_weightage < 10:
        raise HTTPException(status_code=400, detail="Min weightage is 10.")

    group = SharedGoalGroup(
        created_by_id=user.id,
        cycle_id=cycle.id,
        thrust_area=thrust_area.strip(),
        title=title.strip(),
        description=description.strip(),
        uom_type=uom_type,
        target_value=target_value.strip(),
    )
    db.add(group)
    db.flush()

    primary_employee = db.scalar(select(User).where(User.id == primary_owner_id))
    primary_sheet = _get_or_create_sheet(db, employee=primary_employee, cycle=cycle)
    if primary_sheet.status != GoalSheetStatus.draft or primary_sheet.locked:
        raise HTTPException(status_code=400, detail="Primary owner must be in draft state.")

    primary_goal = Goal(
        sheet_id=primary_sheet.id,
        thrust_area=group.thrust_area,
        title=group.title,
        description=group.description,
        uom_type=group.uom_type,
        target_value=group.target_value,
        weightage=default_weightage,
        shared_group_id=group.id,
        primary_owner_goal_id=None,
    )
    db.add(primary_goal)
    db.flush()

    for rid in sorted(selected):
        if rid == primary_owner_id:
            continue
        emp = db.scalar(select(User).where(User.id == rid))
        sheet = _get_or_create_sheet(db, employee=emp, cycle=cycle)
        if sheet.status != GoalSheetStatus.draft or sheet.locked:
            continue
        db.add(
            Goal(
                sheet_id=sheet.id,
                thrust_area=group.thrust_area,
                title=group.title,
                description=group.description,
                uom_type=group.uom_type,
                target_value=group.target_value,
                weightage=default_weightage,
                shared_group_id=group.id,
                primary_owner_goal_id=primary_goal.id,
            )
        )
    db.commit()
    return RedirectResponse(url="/manager/shared-goals", status_code=303)


@router.get("/checkin/{quarter}/{employee_id}", response_class=HTMLResponse)
def checkin_view(
    quarter: Quarter,
    employee_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.manager)),
) -> HTMLResponse:
    cycle = _active_cycle(db)
    employee = db.scalar(select(User).where(User.id == employee_id, User.manager_id == user.id))
    if employee is None:
        raise HTTPException(status_code=404)
    sheet = _get_or_create_sheet(db, employee=employee, cycle=cycle)
    goals = list(sheet.goals)
    rows: list[dict] = []
    for g in goals:
        source_goal = g.primary_owner_goal if g.primary_owner_goal_id else g
        ach = db.scalar(select(GoalAchievement).where(GoalAchievement.goal_id == source_goal.id, GoalAchievement.quarter == quarter))
        rows.append({"goal": g, "source_goal": source_goal, "achievement": ach})
    checkin = db.scalar(
        select(ManagerCheckIn).where(
            ManagerCheckIn.employee_id == employee.id,
            ManagerCheckIn.cycle_id == cycle.id,
            ManagerCheckIn.quarter == quarter,
        )
    )
    return templates.TemplateResponse(
        "manager_checkin.html",
        {
            "request": request,
            "user": user,
            "cycle": cycle,
            "employee": employee,
            "sheet": sheet,
            "quarter": quarter,
            "is_open": is_quarter_open(cycle, quarter, date.today()),
            "window": window_for_cycle(cycle, quarter),
            "rows": rows,
            "checkin": checkin,
        },
    )


@router.post("/checkin/{quarter}/{employee_id}")
def save_checkin(
    quarter: Quarter,
    employee_id: int,
    comment: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.manager)),
) -> RedirectResponse:
    cycle = _active_cycle(db)
    employee = db.scalar(select(User).where(User.id == employee_id, User.manager_id == user.id))
    if employee is None:
        raise HTTPException(status_code=404)
    if not is_quarter_open(cycle, quarter, date.today()):
        raise HTTPException(status_code=403, detail="Quarterly window is closed.")
    checkin = db.scalar(
        select(ManagerCheckIn).where(
            ManagerCheckIn.employee_id == employee.id,
            ManagerCheckIn.cycle_id == cycle.id,
            ManagerCheckIn.quarter == quarter,
        )
    )
    if checkin is None:
        checkin = ManagerCheckIn(
            employee_id=employee.id,
            cycle_id=cycle.id,
            quarter=quarter,
            comment=comment.strip(),
            created_at=datetime.utcnow(),
            created_by_id=user.id,
        )
        db.add(checkin)
    else:
        checkin.comment = comment.strip()
        checkin.created_at = datetime.utcnow()
        checkin.created_by_id = user.id
    db.commit()
    return RedirectResponse(url=f"/manager/checkin/{quarter.value}/{employee.id}", status_code=303)
