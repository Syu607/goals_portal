from __future__ import annotations

import csv
import io
from datetime import date, datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.auth import require_role
from app.db import get_db
from app.models import (
    AuditLog,
    Cycle,
    Goal,
    GoalAchievement,
    GoalSheet,
    GoalSheetStatus,
    ManagerCheckIn,
    Quarter,
    Role,
    UomType,
    User,
)
from app.services.audit import log_event
from app.services.schedule import window_for_cycle
from app.templating import templates


router = APIRouter(prefix="/admin", tags=["admin"])


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
    user: User = Depends(require_role(Role.admin)),
) -> HTMLResponse:
    cycle = _active_cycle(db)
    employees = list(db.scalars(select(User).where(User.role == Role.employee).order_by(User.full_name)))

    sheets = list(db.scalars(select(GoalSheet).where(GoalSheet.cycle_id == cycle.id)))
    by_employee = {s.employee_id: s for s in sheets}

    submitted = sum(1 for s in sheets if s.status == GoalSheetStatus.submitted)
    approved = sum(1 for s in sheets if s.status == GoalSheetStatus.approved)

    checkin_counts = {
        q.value: db.scalar(select(func.count(ManagerCheckIn.id)).where(ManagerCheckIn.cycle_id == cycle.id, ManagerCheckIn.quarter == q))
        for q in (Quarter.q1, Quarter.q2, Quarter.q3, Quarter.q4)
    }
    completion: dict[int, dict[str, dict[str, bool]]] = {}
    for emp in employees:
        sheet = by_employee.get(emp.id) or _get_or_create_sheet(db, employee=emp, cycle=cycle)
        completion[emp.id] = {}
        for q in (Quarter.q1, Quarter.q2, Quarter.q3, Quarter.q4):
            goals = list(sheet.goals)
            source_ids = {g.primary_owner_goal_id or g.id for g in goals}
            achieved_ids = set(
                db.scalars(
                    select(GoalAchievement.goal_id).where(
                        GoalAchievement.quarter == q,
                        GoalAchievement.goal_id.in_(source_ids),
                    )
                )
            )
            emp_done = bool(goals) and all((g.primary_owner_goal_id or g.id) in achieved_ids for g in goals)
            mgr_done = (
                db.scalar(
                    select(func.count(ManagerCheckIn.id)).where(
                        ManagerCheckIn.employee_id == emp.id,
                        ManagerCheckIn.cycle_id == cycle.id,
                        ManagerCheckIn.quarter == q,
                    )
                )
                > 0
            )
            completion[emp.id][q.value] = {"employee": emp_done, "manager": mgr_done}
    return templates.TemplateResponse(
        request,
        "admin_dashboard.html",
        {
            "request": request,
            "user": user,
            "cycle": cycle,
            "employees": employees,
            "by_employee": by_employee,
            "submitted": submitted,
            "approved": approved,
            "checkin_counts": checkin_counts,
            "completion": completion,
            "Quarter": Quarter,
            "window_goal_setting": window_for_cycle(cycle, None),
            "window_q1": window_for_cycle(cycle, Quarter.q1),
            "window_q2": window_for_cycle(cycle, Quarter.q2),
            "window_q3": window_for_cycle(cycle, Quarter.q3),
            "window_q4": window_for_cycle(cycle, Quarter.q4),
        },
    )


@router.get("/sheet/{employee_id}", response_class=HTMLResponse)
def admin_sheet(
    employee_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.admin)),
) -> HTMLResponse:
    cycle = _active_cycle(db)
    employee = db.scalar(select(User).where(User.id == employee_id, User.role == Role.employee))
    if employee is None:
        raise HTTPException(status_code=404)
    sheet = _get_or_create_sheet(db, employee=employee, cycle=cycle)
    goals = list(sheet.goals)
    return templates.TemplateResponse(
        request,
        "admin_sheet.html",
        {"request": request, "user": user, "cycle": cycle, "employee": employee, "sheet": sheet, "goals": goals, "UomType": UomType},
    )


@router.post("/sheet/{sheet_id}/unlock")
def unlock_sheet(
    sheet_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.admin)),
) -> RedirectResponse:
    cycle = _active_cycle(db)
    sheet = db.scalar(select(GoalSheet).where(GoalSheet.id == sheet_id, GoalSheet.cycle_id == cycle.id))
    if sheet is None:
        raise HTTPException(status_code=404)
    sheet.locked = 0
    log_event(db, actor=user, entity_type="GoalSheet", entity_id=sheet.id, action="unlock")
    db.commit()
    return RedirectResponse(url=f"/admin/sheet/{sheet.employee_id}", status_code=303)


@router.post("/sheet/{sheet_id}/lock")
def lock_sheet(
    sheet_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.admin)),
) -> RedirectResponse:
    cycle = _active_cycle(db)
    sheet = db.scalar(select(GoalSheet).where(GoalSheet.id == sheet_id, GoalSheet.cycle_id == cycle.id))
    if sheet is None:
        raise HTTPException(status_code=404)
    sheet.locked = 1
    log_event(db, actor=user, entity_type="GoalSheet", entity_id=sheet.id, action="lock")
    db.commit()
    return RedirectResponse(url=f"/admin/sheet/{sheet.employee_id}", status_code=303)


@router.post("/sheet/{sheet_id}/goal/{goal_id}")
def admin_edit_goal(
    sheet_id: int,
    goal_id: int,
    thrust_area: str = Form(...),
    title: str = Form(...),
    description: str = Form(""),
    uom_type: UomType = Form(...),
    target_value: str = Form(...),
    weightage: int = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.admin)),
) -> RedirectResponse:
    cycle = _active_cycle(db)
    sheet = db.scalar(select(GoalSheet).where(GoalSheet.id == sheet_id, GoalSheet.cycle_id == cycle.id))
    if sheet is None:
        raise HTTPException(status_code=404)
    goal = db.scalar(select(Goal).where(Goal.id == goal_id, Goal.sheet_id == sheet.id))
    if goal is None:
        raise HTTPException(status_code=404)
    if sheet.locked:
        raise HTTPException(status_code=403, detail="Unlock sheet before editing.")

    _audit_goal_field(db, user, goal, "thrust_area", goal.thrust_area, thrust_area.strip())
    _audit_goal_field(db, user, goal, "title", goal.title, title.strip())
    _audit_goal_field(db, user, goal, "description", goal.description, description.strip())
    _audit_goal_field(db, user, goal, "uom_type", goal.uom_type.value, uom_type.value)
    _audit_goal_field(db, user, goal, "target_value", goal.target_value, target_value.strip())
    _audit_goal_field(db, user, goal, "weightage", str(goal.weightage), str(weightage))

    goal.thrust_area = thrust_area.strip()
    goal.title = title.strip()
    goal.description = description.strip()
    goal.uom_type = uom_type
    goal.target_value = target_value.strip()
    goal.weightage = weightage
    db.commit()
    return RedirectResponse(url=f"/admin/sheet/{sheet.employee_id}", status_code=303)


def _audit_goal_field(db: Session, actor: User, goal: Goal, field: str, old: str, new: str) -> None:
    if old != new:
        log_event(db, actor=actor, entity_type="Goal", entity_id=goal.id, action="edit", field_name=field, old_value=old, new_value=new)


@router.get("/audit", response_class=HTMLResponse)
def audit_view(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.admin)),
) -> HTMLResponse:
    logs = list(db.scalars(select(AuditLog).order_by(desc(AuditLog.created_at)).limit(200)))
    actors = {u.id: u for u in db.scalars(select(User).where(User.id.in_({l.actor_id for l in logs})))}
    return templates.TemplateResponse(
        request,
        "admin_audit.html",
        {"request": request, "user": user, "logs": logs, "actors": actors},
    )


@router.get("/reports/achievement.csv")
def achievement_report(
    quarter: Quarter = Quarter.q1,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.admin)),
) -> StreamingResponse:
    cycle = _active_cycle(db)
    employees = list(db.scalars(select(User).where(User.role == Role.employee)))
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["employee_username", "employee_name", "goal_title", "thrust_area", "uom_type", "target", "actual", "status", "progress_score", "quarter"])
    for emp in employees:
        sheet = _get_or_create_sheet(db, employee=emp, cycle=cycle)
        for g in sheet.goals:
            source_goal = g.primary_owner_goal if g.primary_owner_goal_id else g
            ach = db.scalar(select(GoalAchievement).where(GoalAchievement.goal_id == source_goal.id, GoalAchievement.quarter == quarter))
            writer.writerow(
                [
                    emp.username,
                    emp.full_name,
                    g.title,
                    g.thrust_area,
                    g.uom_type.value,
                    g.target_value,
                    (ach.actual_value if ach else ""),
                    (ach.status.value if ach else ""),
                    (ach.progress_score if ach else 0),
                    quarter.value,
                ]
            )
    out.seek(0)
    filename = f"achievement_{cycle.year}_{quarter.value}.csv"
    return StreamingResponse(
        iter([out.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/cycle/update")
def update_cycle(
    year: int = Form(...),
    goal_setting_open: date = Form(...),
    q1_open: date = Form(...),
    q2_open: date = Form(...),
    q3_open: date = Form(...),
    q4_open: date = Form(...),
    window_days: int = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.admin)),
) -> RedirectResponse:
    cycle = db.scalar(select(Cycle).where(Cycle.year == year))
    if cycle is None:
        cycle = Cycle(
            year=year,
            goal_setting_open=goal_setting_open,
            q1_open=q1_open,
            q2_open=q2_open,
            q3_open=q3_open,
            q4_open=q4_open,
            window_days=window_days,
            is_active=1,
        )
        db.add(cycle)
    else:
        cycle.goal_setting_open = goal_setting_open
        cycle.q1_open = q1_open
        cycle.q2_open = q2_open
        cycle.q3_open = q3_open
        cycle.q4_open = q4_open
        cycle.window_days = window_days
        cycle.is_active = 1
    db.flush()
    for other in db.scalars(select(Cycle).where(Cycle.id != cycle.id)):
        other.is_active = 0
    log_event(db, actor=user, entity_type="Cycle", entity_id=cycle.id, action="update")
    db.commit()
    return RedirectResponse(url="/admin", status_code=303)
