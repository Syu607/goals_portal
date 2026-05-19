from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base, Cycle, Role, User
from app.services.security import hash_password


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "portal.db"


def _database_url() -> str:
    return f"sqlite:///{DB_PATH.as_posix()}"


engine = create_engine(_database_url(), connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    with Session(engine) as db:
        _seed_if_needed(db)


def _seed_if_needed(db: Session) -> None:
    admin = db.scalar(select(User).where(User.username == "admin"))
    if admin is not None:
        return

    manager = User(
        username="manager1",
        full_name="Manager One",
        password_hash=hash_password("manager123"),
        role=Role.manager,
    )
    employee1 = User(
        username="employee1",
        full_name="Employee One",
        password_hash=hash_password("employee123"),
        role=Role.employee,
        manager=manager,
    )
    employee2 = User(
        username="employee2",
        full_name="Employee Two",
        password_hash=hash_password("employee123"),
        role=Role.employee,
        manager=manager,
    )
    admin = User(
        username="admin",
        full_name="Admin / HR",
        password_hash=hash_password("admin123"),
        role=Role.admin,
    )
    db.add_all([manager, employee1, employee2, admin])

    year = date.today().year
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
    db.commit()
