# Copyright (C) 2026 Javier Garcia
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

import secrets
from fastapi import Request, HTTPException, Form
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .models import ROLE_OPERATOR, ROLE_PATIENT, ROLE_TECHNICIAN, User

def get_csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token

def validate_csrf(request: Request, csrf_token: str = Form(...)):
    session_token = request.session.get("csrf_token")
    if not session_token or not secrets.compare_digest(session_token, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)

def login_user(request: Request, user: User) -> None:
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["role"] = user.role
    request.session["name"] = user.name

def logout_user(request: Request) -> None:
    request.session.clear()

def current_user(request: Request, db: Session):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.get(User, user_id)

def is_operator(user: User | None) -> bool:
    return bool(user and user.role == ROLE_OPERATOR)

def is_patient(user: User | None) -> bool:
    return bool(user and user.role == ROLE_PATIENT)

def is_technician(user: User | None) -> bool:
    return bool(user and user.role == ROLE_TECHNICIAN)
