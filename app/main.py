from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.db import init_db
from app.routers import admin, auth, employee, manager


def create_app() -> FastAPI:
    app = FastAPI(title="AtomQuest Goal Setting & Tracking Portal")

    secret_key = secrets.token_urlsafe(32)
    app.add_middleware(SessionMiddleware, secret_key=secret_key, same_site="lax")

    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.include_router(auth.router)
    app.include_router(employee.router)
    app.include_router(manager.router)
    app.include_router(admin.router)

    @app.on_event("startup")
    def _startup() -> None:
        init_db()

    return app


app = create_app()
