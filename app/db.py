from __future__ import annotations

import os
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    Base,
    Cycle,
    Goal,
    GoalAchievement,
    GoalSheet,
    GoalSheetStatus,
    GoalStatus,
    ManagerCheckIn,
    Quarter,
    Role,
    SharedGoalGroup,
    UomType,
    User,
)
from app.services.security import hash_password


ROOT_DIR = Path(__file__).resolve().parents[1]


def _database_url() -> str:
    for var in ("NETLIFY_DATABASE_URL", "DATABASE_URL"):
        url = os.getenv(var)
        if url:
            return url.replace("postgres://", "postgresql://", 1) if url.startswith("postgres://") else url
    if os.getenv("VERCEL") is not None:
        data_dir = Path(tempfile.gettempdir()) / "atomquest_goals_portal"
    else:
        data_dir = ROOT_DIR / "data"
    os.makedirs(data_dir, exist_ok=True)
    return f"sqlite:///{(data_dir / 'portal.db').as_posix()}"


_DB_URL = _database_url()
_is_postgres = _DB_URL.startswith("postgresql")

if _is_postgres:
    from sqlalchemy.pool import NullPool
    engine = create_engine(_DB_URL, poolclass=NullPool)
else:
    engine = create_engine(_DB_URL, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    with Session(engine) as db:
        _seed_if_needed(db)
        _ensure_demo_data(db)


def _seed_if_needed(db: Session) -> None:
    manager = db.scalar(select(User).where(User.username == "manager1"))
    if manager is None:
        manager = User(
            username="manager1",
            full_name="Manager One",
            password_hash=hash_password("manager123"),
            role=Role.manager,
        )
        db.add(manager)
        db.flush()

    employee1 = db.scalar(select(User).where(User.username == "employee1"))
    if employee1 is None:
        employee1 = User(
            username="employee1",
            full_name="Employee One",
            password_hash=hash_password("employee123"),
            role=Role.employee,
            manager_id=manager.id,
        )
        db.add(employee1)

    employee2 = db.scalar(select(User).where(User.username == "employee2"))
    if employee2 is None:
        employee2 = User(
            username="employee2",
            full_name="Employee Two",
            password_hash=hash_password("employee123"),
            role=Role.employee,
            manager_id=manager.id,
        )
        db.add(employee2)

    admin = db.scalar(select(User).where(User.username == "admin"))
    if admin is None:
        admin = User(
            username="admin",
            full_name="Admin / HR",
            password_hash=hash_password("admin123"),
            role=Role.admin,
        )
        db.add(admin)

    year = date.today().year
    cycle = db.scalar(select(Cycle).where(Cycle.year == year))
    if cycle is None:
        cycle = Cycle(
            year=year,
            goal_setting_open=date(year, 5, 1),
            q1_open=date(year, 7, 1),
            q2_open=date(year, 10, 1),
            q3_open=date(year, 1, 1),
            q4_open=date(year, 3, 1),
            window_days=45,
            is_active=1,
        )
        db.add(cycle)
    else:
        cycle.is_active = 1
    for other in db.scalars(select(Cycle).where(Cycle.year != year)):
        other.is_active = 0
    db.commit()


def _ensure_demo_data(db: Session) -> None:
    goals_count = db.scalar(select(func.count(Goal.id)))
    if goals_count and goals_count > 0:
        return

    today = date.today()
    year = today.year
    cycle = db.scalar(select(Cycle).where(Cycle.year == year))
    if cycle is None:
        cycle = Cycle(
            year=year,
            goal_setting_open=today - timedelta(days=1),
            q1_open=today - timedelta(days=1),
            q2_open=today - timedelta(days=1),
            q3_open=today - timedelta(days=1),
            q4_open=today - timedelta(days=1),
            window_days=365,
            is_active=1,
        )
        db.add(cycle)
        db.flush()
    else:
        cycle.goal_setting_open = today - timedelta(days=1)
        cycle.q1_open = today - timedelta(days=1)
        cycle.q2_open = today - timedelta(days=1)
        cycle.q3_open = today - timedelta(days=1)
        cycle.q4_open = today - timedelta(days=1)
        cycle.window_days = 365
        cycle.is_active = 1

    manager = db.scalar(select(User).where(User.username == "manager1"))
    employee1 = db.scalar(select(User).where(User.username == "employee1"))
    employee2 = db.scalar(select(User).where(User.username == "employee2"))
    if manager is None or employee1 is None or employee2 is None:
        return

    sheet1 = db.scalar(select(GoalSheet).where(GoalSheet.employee_id == employee1.id, GoalSheet.cycle_id == cycle.id))
    if sheet1 is None:
        sheet1 = GoalSheet(employee_id=employee1.id, cycle_id=cycle.id)
        db.add(sheet1)
        db.flush()
    sheet1.status = GoalSheetStatus.approved
    sheet1.locked = 1
    sheet1.submitted_at = sheet1.submitted_at or datetime.utcnow()
    sheet1.approved_at = datetime.utcnow()
    sheet1.approved_by_id = manager.id

    sheet2 = db.scalar(select(GoalSheet).where(GoalSheet.employee_id == employee2.id, GoalSheet.cycle_id == cycle.id))
    if sheet2 is None:
        sheet2 = GoalSheet(employee_id=employee2.id, cycle_id=cycle.id)
        db.add(sheet2)
        db.flush()
    sheet2.status = GoalSheetStatus.draft
    sheet2.locked = 0

    group = SharedGoalGroup(
        created_by_id=manager.id,
        cycle_id=cycle.id,
        thrust_area="Operations Excellence",
        title="Department KPI: On-time Delivery",
        description="Improve on-time delivery rate across the department",
        uom_type=UomType.min,
        target_value="95",
    )
    db.add(group)
    db.flush()

    primary_goal = Goal(
        sheet_id=sheet1.id,
        thrust_area=group.thrust_area,
        title=group.title,
        description=group.description,
        uom_type=group.uom_type,
        target_value=group.target_value,
        weightage=30,
        shared_group_id=group.id,
        primary_owner_goal_id=None,
    )
    db.add(primary_goal)
    db.flush()

    recipient_goal = Goal(
        sheet_id=sheet2.id,
        thrust_area=group.thrust_area,
        title=group.title,
        description=group.description,
        uom_type=group.uom_type,
        target_value=group.target_value,
        weightage=20,
        shared_group_id=group.id,
        primary_owner_goal_id=primary_goal.id,
    )
    db.add(recipient_goal)

    db.add_all(
        [
            Goal(
                sheet_id=sheet1.id,
                thrust_area="Customer",
                title="Improve CSAT Score",
                description="Increase customer satisfaction through faster resolution and proactive comms",
                uom_type=UomType.min,
                target_value="4.6",
                weightage=30,
            ),
            Goal(
                sheet_id=sheet1.id,
                thrust_area="Process",
                title="Reduce Ticket TAT",
                description="Reduce turnaround time for priority tickets",
                uom_type=UomType.max,
                target_value="2",
                weightage=20,
            ),
            Goal(
                sheet_id=sheet1.id,
                thrust_area="Safety",
                title="Zero Safety Incidents",
                description="Maintain zero reportable incidents",
                uom_type=UomType.zero,
                target_value="0",
                weightage=20,
            ),
        ]
    )

    db.add_all(
        [
            Goal(
                sheet_id=sheet2.id,
                thrust_area="Learning",
                title="Complete Role Upskilling",
                description="Complete an advanced course and apply learnings in the project",
                uom_type=UomType.timeline,
                target_value=(today + timedelta(days=45)).isoformat(),
                weightage=30,
            ),
            Goal(
                sheet_id=sheet2.id,
                thrust_area="Quality",
                title="Improve First-Time-Right",
                description="Increase FTR percentage via checklists and peer reviews",
                uom_type=UomType.min,
                target_value="92",
                weightage=30,
            ),
            Goal(
                sheet_id=sheet2.id,
                thrust_area="Cost",
                title="Reduce Rework Cost",
                description="Lower rework cost by improving upstream validations",
                uom_type=UomType.max,
                target_value="5",
                weightage=20,
            ),
        ]
    )

    sheet2.status = GoalSheetStatus.submitted
    sheet2.submitted_at = datetime.utcnow()

    now = datetime.utcnow()
    db.add(
        GoalAchievement(
            goal_id=primary_goal.id,
            quarter=Quarter.q1,
            status=GoalStatus.on_track,
            actual_value="90",
            progress_score=95,
            updated_at=now,
            updated_by_id=employee1.id,
        )
    )
    db.add(
        ManagerCheckIn(
            employee_id=employee1.id,
            cycle_id=cycle.id,
            quarter=Quarter.q1,
            comment="Good progress. Focus on pushing on-time delivery above 92% and keep CSAT stable.",
            created_at=now,
            created_by_id=manager.id,
        )
    )

    db.commit()
