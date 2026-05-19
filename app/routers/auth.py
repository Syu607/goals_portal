from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Role, User
from app.services.security import verify_password
from app.templating import templates


router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def root(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    user_id = request.session.get("user_id")
    if user_id:
        user = db.scalar(select(User).where(User.id == user_id))
        if user:
            if user.role == Role.employee:
                return RedirectResponse(url="/employee", status_code=303)
            if user.role == Role.manager:
                return RedirectResponse(url="/manager", status_code=303)
            return RedirectResponse(url="/admin", status_code=303)
    return RedirectResponse(url="/login", status_code=303)


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "login.html",
        {"request": request, "error": "", "prefill_user": "", "prefill_pass": ""},
    )


@router.post("/login", response_class=HTMLResponse)
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    user = db.scalar(select(User).where(User.username == username.strip()))
    if user is None or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"request": request, "error": "Invalid username or password.", "prefill_user": username, "prefill_pass": ""},
            status_code=401,
        )
    request.session["user_id"] = user.id
    return RedirectResponse(url="/", status_code=303)


@router.post("/logout")
def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
