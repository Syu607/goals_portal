from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Role(str, enum.Enum):
    employee = "employee"
    manager = "manager"
    admin = "admin"


class GoalSheetStatus(str, enum.Enum):
    draft = "draft"
    submitted = "submitted"
    approved = "approved"


class UomType(str, enum.Enum):
    min = "min"
    max = "max"
    timeline = "timeline"
    zero = "zero"


class GoalStatus(str, enum.Enum):
    not_started = "not_started"
    on_track = "on_track"
    completed = "completed"


class Quarter(str, enum.Enum):
    q1 = "q1"
    q2 = "q2"
    q3 = "q3"
    q4 = "q4"
    annual = "annual"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role), index=True)

    manager_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    manager: Mapped[User | None] = relationship(remote_side=[id], back_populates="direct_reports")
    direct_reports: Mapped[list[User]] = relationship(back_populates="manager")

    goal_sheets: Mapped[list["GoalSheet"]] = relationship(back_populates="employee", foreign_keys="GoalSheet.employee_id")


class Cycle(Base):
    __tablename__ = "cycles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    year: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    goal_setting_open: Mapped[date] = mapped_column(Date)
    q1_open: Mapped[date] = mapped_column(Date)
    q2_open: Mapped[date] = mapped_column(Date)
    q3_open: Mapped[date] = mapped_column(Date)
    q4_open: Mapped[date] = mapped_column(Date)
    window_days: Mapped[int] = mapped_column(Integer, default=31)
    is_active: Mapped[int] = mapped_column(Integer, default=1, index=True)

    goal_sheets: Mapped[list[GoalSheet]] = relationship(back_populates="cycle")


class GoalSheet(Base):
    __tablename__ = "goal_sheets"
    __table_args__ = (UniqueConstraint("employee_id", "cycle_id", name="uq_sheet_employee_cycle"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("cycles.id"), index=True)
    status: Mapped[GoalSheetStatus] = mapped_column(Enum(GoalSheetStatus), default=GoalSheetStatus.draft)
    locked: Mapped[int] = mapped_column(Integer, default=0, index=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    employee: Mapped[User] = relationship(back_populates="goal_sheets", foreign_keys=[employee_id])
    cycle: Mapped[Cycle] = relationship(back_populates="goal_sheets")
    goals: Mapped[list[Goal]] = relationship(back_populates="sheet", cascade="all, delete-orphan")
    approved_by: Mapped[User | None] = relationship(foreign_keys=[approved_by_id])


class SharedGoalGroup(Base):
    __tablename__ = "shared_goal_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("cycles.id"), index=True)
    thrust_area: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    uom_type: Mapped[UomType] = mapped_column(Enum(UomType))
    target_value: Mapped[str] = mapped_column(String(120))

    created_by: Mapped[User] = relationship(foreign_keys=[created_by_id])
    goals: Mapped[list[Goal]] = relationship(back_populates="shared_group")


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sheet_id: Mapped[int] = mapped_column(ForeignKey("goal_sheets.id"), index=True)
    thrust_area: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    uom_type: Mapped[UomType] = mapped_column(Enum(UomType))
    target_value: Mapped[str] = mapped_column(String(120))
    weightage: Mapped[int] = mapped_column(Integer)

    shared_group_id: Mapped[int | None] = mapped_column(ForeignKey("shared_goal_groups.id"), nullable=True, index=True)
    primary_owner_goal_id: Mapped[int | None] = mapped_column(ForeignKey("goals.id"), nullable=True, index=True)

    sheet: Mapped[GoalSheet] = relationship(back_populates="goals", foreign_keys=[sheet_id])
    shared_group: Mapped[SharedGoalGroup | None] = relationship(back_populates="goals", foreign_keys=[shared_group_id])
    primary_owner_goal: Mapped[Goal | None] = relationship(remote_side=[id], foreign_keys=[primary_owner_goal_id])

    achievements: Mapped[list[GoalAchievement]] = relationship(back_populates="goal", cascade="all, delete-orphan")


class GoalAchievement(Base):
    __tablename__ = "goal_achievements"
    __table_args__ = (UniqueConstraint("goal_id", "quarter", name="uq_goal_quarter"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("goals.id"), index=True)
    quarter: Mapped[Quarter] = mapped_column(Enum(Quarter), index=True)
    status: Mapped[GoalStatus] = mapped_column(Enum(GoalStatus), default=GoalStatus.not_started)
    actual_value: Mapped[str] = mapped_column(String(120), default="")
    progress_score: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    updated_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    goal: Mapped[Goal] = relationship(back_populates="achievements")
    updated_by: Mapped[User] = relationship(foreign_keys=[updated_by_id])


class ManagerCheckIn(Base):
    __tablename__ = "manager_checkins"
    __table_args__ = (UniqueConstraint("employee_id", "cycle_id", "quarter", name="uq_checkin_employee_cycle_quarter"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("cycles.id"), index=True)
    quarter: Mapped[Quarter] = mapped_column(Enum(Quarter), index=True)
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    employee: Mapped[User] = relationship(foreign_keys=[employee_id])
    created_by: Mapped[User] = relationship(foreign_keys=[created_by_id])
    cycle: Mapped[Cycle] = relationship(foreign_keys=[cycle_id])


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String(50), index=True)
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(50), index=True)
    field_name: Mapped[str] = mapped_column(String(80), default="")
    old_value: Mapped[str] = mapped_column(Text, default="")
    new_value: Mapped[str] = mapped_column(Text, default="")

    actor: Mapped[User] = relationship(foreign_keys=[actor_id])
