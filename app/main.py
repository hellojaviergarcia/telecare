# Copyright (C) 2026 Javier Garcia
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

import asyncio
import secrets
import json
import csv
import io
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import Depends, FastAPI, Form, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, asc, select, func, cast, String
from sqlalchemy.orm import Session, selectinload
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from .auth import current_user, hash_password, is_operator, is_patient, is_technician, login_user, logout_user, verify_password, get_csrf_token, validate_csrf
from .config import APP_NAME, SECRET_KEY, SESSION_COOKIE_NAME, USE_HTTPS
from .db import Base, engine, get_db
from .models import (
    INVITE_ACTIVE,
    INVITE_REDEEMED,
    ROLE_OPERATOR,
    ROLE_PATIENT,
    ROLE_TECHNICIAN,
    REQUEST_ACKNOWLEDGED,
    REQUEST_REQUESTED,
    REQUEST_RESOLVED,
    HelpRequest,
    Invitation,
    User,
    PatientProfile,
    AuditLog,
    utcnow,
)
from .realtime import manager, refresh_payload

app = FastAPI(title=APP_NAME)
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self' ws: wss:;"
        )
        response.headers["Content-Security-Policy"] = csp
        
        if USE_HTTPS:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            
        return response

app.add_middleware(SecurityHeadersMiddleware)


app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie=SESSION_COOKIE_NAME,
    same_site="lax",
    https_only=USE_HTTPS,
)

templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.on_event("startup")
def startup() -> None:
    app.state.loop = asyncio.get_running_loop()
    from .init_db import main as init_db_main
    init_db_main()

@app.post("/toggle-dark-mode", dependencies=[Depends(validate_csrf)])
def toggle_dark_mode(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Not logged in"}, status_code=401)
    user.dark_mode = not user.dark_mode
    db.commit()
    return {"dark_mode": user.dark_mode}

def ctx(request: Request, user=None, **kwargs):
    return {"request": request, "user": user, "csrf_token": get_csrf_token(request), **kwargs}

def log_audit(db: Session, request: Request, user_id: int, action: str, details: str = None):
    try:
        ip = get_remote_address(request)
    except Exception:
        ip = request.client.host if request.client else None
    audit = AuditLog(user_id=user_id, ip_address=ip, action=action, details=details)
    db.add(audit)
    db.commit()
    db.refresh(audit)
    
    tech_ids = db.scalars(select(User.id).where(User.role == ROLE_TECHNICIAN)).all()
    
    # query user name for broadcast
    user_name = "System"
    if user_id:
        user = db.scalar(select(User).where(User.id == user_id))
        if user: user_name = user.name

    payload = {
        "event": "new_audit_log",
        "log": {
            "timestamp": audit.timestamp.isoformat(),
            "user": user_name,
            "ip": ip or "Unknown",
            "action": action,
            "details": details or ""
        }
    }
    if hasattr(request.app.state, "loop"):
        asyncio.run_coroutine_threadsafe(manager.send_many(tech_ids, payload), request.app.state.loop)


@app.exception_handler(RateLimitExceeded)
def custom_rate_limit_handler(request: Request, exc: RateLimitExceeded):
    path = request.url.path
    if "operator" in path:
        template = "operator_login.html"
    elif "technician" in path:
        template = "technician_login.html"
    else:
        template = "patient_login.html"
    return templates.TemplateResponse(
        request=request, 
        name=template, 
        context=ctx(request, error="You have exceeded the maximum number of attempts. Please wait 1 minute."), 
        status_code=429
    )


def normalize_email(email: str) -> str:
    return email.strip().lower()

def unresolved_request_query(patient_id: int):
    return (
        select(HelpRequest)
        .where(HelpRequest.patient_id == patient_id, HelpRequest.status != REQUEST_RESOLVED)
        .order_by(desc(HelpRequest.created_at))
    )

def redirect_to_dashboard(user):
    if user.role == ROLE_OPERATOR:
        return RedirectResponse("/operator/dashboard", status_code=303)
    elif user.role == ROLE_TECHNICIAN:
        return RedirectResponse("/technician/dashboard", status_code=303)
    elif user.role == ROLE_PATIENT:
        return RedirectResponse("/patient/dashboard", status_code=303)
    return RedirectResponse("/", status_code=303)

@app.get("/", response_class=HTMLResponse, name="landing")
def landing(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user:
        return redirect_to_dashboard(user)
    return templates.TemplateResponse(request=request, name="landing.html", context=ctx(request, user=user))

@app.get("/operator/login", response_class=HTMLResponse, name="operator_login_form")
def operator_login_form(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user:
        return redirect_to_dashboard(user)
    return templates.TemplateResponse(request=request, name="operator_login.html", context=ctx(request, user=user, error=None))

@app.post("/operator/login", dependencies=[Depends(validate_csrf)])
@limiter.limit("5/minute")
def operator_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.scalar(select(User).where(User.role == ROLE_OPERATOR, User.email == normalize_email(email)))
    if not user or not verify_password(password, user.password_hash):
        log_audit(db, request, None, "LOGIN_FAILED", f"Failed operator login for {email}")
        return templates.TemplateResponse(request=request, name="operator_login.html", context=ctx(request, user=None, error="Invalid credentials."), status_code=400)
    log_audit(db, request, user.id, "LOGIN_SUCCESS", "Operator logged in")
    login_user(request, user)
    return RedirectResponse("/operator/dashboard", status_code=303)

@app.get("/technician/login", response_class=HTMLResponse, name="technician_login_form")
def technician_login_form(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user:
        return redirect_to_dashboard(user)
    return templates.TemplateResponse(request=request, name="technician_login.html", context=ctx(request, user=user, error=None))

@app.post("/technician/login", dependencies=[Depends(validate_csrf)])
@limiter.limit("5/minute")
def technician_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.scalar(select(User).where(User.role == ROLE_TECHNICIAN, User.email == normalize_email(email)))
    if not user or not verify_password(password, user.password_hash):
        log_audit(db, request, None, "LOGIN_FAILED", f"Failed tech login for {email}")
        return templates.TemplateResponse(request=request, name="technician_login.html", context=ctx(request, user=None, error="Invalid credentials."), status_code=400)
    log_audit(db, request, user.id, "LOGIN_SUCCESS", "Technician logged in")
    login_user(request, user)
    return RedirectResponse("/technician/dashboard", status_code=303)

@app.get("/technician/dashboard", response_class=HTMLResponse, name="technician_dashboard")
def technician_dashboard(request: Request, page: int = 1, op_page: int = 1, pat_page: int = 1, search_op: str = "", search_pat: str = "", search_req: str = "", db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not is_technician(user):
        return RedirectResponse("/technician/login", status_code=303)
        
    limit = 10
    
    # Operators Pagination
    op_offset = (op_page - 1) * limit
    op_query = select(User).where(User.role == ROLE_OPERATOR)
    if search_op:
        op_query = op_query.where(User.name.icontains(search_op) | User.email.icontains(search_op) | User.shift.icontains(search_op))
    total_operators = db.scalar(select(func.count()).select_from(op_query.subquery()))
    total_op_pages = (total_operators + limit - 1) // limit if total_operators and total_operators > 0 else 1
    operators = db.scalars(op_query.order_by(desc(User.created_at)).offset(op_offset).limit(limit)).all()
    
    # Patients Pagination
    pat_offset = (pat_page - 1) * limit
    pat_query = select(User).where(User.role == ROLE_PATIENT)
    if search_pat:
        pat_query = pat_query.where(User.name.icontains(search_pat))
    total_patients = db.scalar(select(func.count()).select_from(pat_query.subquery()))
    total_pat_pages = (total_patients + limit - 1) // limit if total_patients and total_patients > 0 else 1
    patients = db.scalars(pat_query.options(selectinload(User.operator)).order_by(desc(User.created_at)).offset(pat_offset).limit(limit)).all()
    
    # Requests Pagination
    offset = (page - 1) * limit
    req_query = select(HelpRequest)
    if search_req:
        search_req_id = search_req.lstrip('#')
        req_query = req_query.outerjoin(User, HelpRequest.patient_id == User.id).where(HelpRequest.status.icontains(search_req) | User.name.icontains(search_req) | cast(HelpRequest.id, String).icontains(search_req_id))
    total_requests = db.scalar(select(func.count()).select_from(req_query.subquery()))
    total_pages = (total_requests + limit - 1) // limit if total_requests and total_requests > 0 else 1
    
    requests_list = db.scalars(
        req_query
        .options(selectinload(HelpRequest.patient), selectinload(HelpRequest.operator))
        .order_by(desc(HelpRequest.created_at))
        .offset(offset)
        .limit(limit)
    ).all()
    
    # Analytics Calculations
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    total_today = db.scalar(select(func.count(HelpRequest.id)).where(HelpRequest.created_at >= today_start)) or 0
    pending_requests = db.scalar(select(func.count(HelpRequest.id)).where(HelpRequest.status.in_([REQUEST_REQUESTED, REQUEST_ACKNOWLEDGED]))) or 0
    
    reqs_with_ack = db.scalars(select(HelpRequest).where(HelpRequest.acknowledged_at.isnot(None))).all()
    if reqs_with_ack:
        avg_resp_seconds = sum((r.acknowledged_at - r.created_at).total_seconds() for r in reqs_with_ack) / len(reqs_with_ack)
    else:
        avg_resp_seconds = 0
    avg_response_sec = int(round(avg_resp_seconds))

    shift_counts = {"Morning": 0, "Afternoon": 0, "Night": 0}
    all_req_times = db.scalars(select(HelpRequest.created_at)).all()
    for created_at in all_req_times:
        hour = created_at.hour
        if 6 <= hour < 14:
            shift_counts["Morning"] += 1
        elif 14 <= hour < 22:
            shift_counts["Afternoon"] += 1
        else:
            shift_counts["Night"] += 1

    seven_days_ago = today_start - timedelta(days=6)
    recent_reqs = db.scalars(select(HelpRequest).where(HelpRequest.created_at >= seven_days_ago)).all()
    weekly_dict = {}
    for i in range(7):
        day = (seven_days_ago + timedelta(days=i)).strftime("%Y-%m-%d")
        weekly_dict[day] = 0
    for r in recent_reqs:
        day = r.created_at.strftime("%Y-%m-%d")
        if day in weekly_dict:
            weekly_dict[day] += 1
            
    analytics = {
        "total_today": total_today,
        "pending_requests": pending_requests,
        "avg_response_sec": avg_response_sec,
        "shift_data": json.dumps(shift_counts),
        "weekly_data_labels": json.dumps(list(weekly_dict.keys())),
        "weekly_data_values": json.dumps(list(weekly_dict.values()))
    }
    
    audit_logs_db = db.scalars(select(AuditLog).order_by(desc(AuditLog.timestamp)).limit(100)).all()
    audit_logs = []
    for log in audit_logs_db:
        audit_logs.append({
        "timestamp": log.timestamp.isoformat(),
        "ip": log.ip_address or "Unknown",
        "user": log.user.name if log.user else "System",
        "action": log.action,
        "details": log.details or ""
        })
    audit_logs_json = json.dumps(audit_logs)
    return templates.TemplateResponse(request=request, name="technician_dashboard.html", context=ctx(request, user=user, audit_logs_json=audit_logs_json, operators=operators, patients=patients, requests=requests_list, page=page, total_pages=total_pages, op_page=op_page, total_op_pages=total_op_pages, pat_page=pat_page, total_pat_pages=total_pat_pages, search_op=search_op, search_pat=search_pat, search_req=search_req, analytics=analytics, error=None))

@app.post("/technician/create_operator", dependencies=[Depends(validate_csrf)])
def create_operator(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    shift: str = Form(...),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if not is_technician(user):
        return RedirectResponse("/technician/login", status_code=303)
    
    email = normalize_email(email)
    name = name.strip()
    if db.scalar(select(User.id).where(User.email == email)):
        operators = db.scalars(select(User).where(User.role == ROLE_OPERATOR).order_by(desc(User.created_at))).all()
        patients = db.scalars(select(User).where(User.role == ROLE_PATIENT).options(selectinload(User.operator)).order_by(desc(User.created_at))).all()
        
        limit = 10
        total_requests = db.scalar(select(func.count(HelpRequest.id)))
        total_pages = (total_requests + limit - 1) // limit if total_requests and total_requests > 0 else 1
        requests_list = db.scalars(select(HelpRequest).options(selectinload(HelpRequest.patient), selectinload(HelpRequest.operator)).order_by(desc(HelpRequest.created_at)).offset(0).limit(limit)).all()
        
        audit_logs_db = db.scalars(select(AuditLog).order_by(desc(AuditLog.timestamp)).limit(100)).all()
        audit_logs = []
        for log in audit_logs_db:
            audit_logs.append({
            "timestamp": log.timestamp.isoformat(),
            "ip": log.ip_address or "Unknown",
            "user": log.user.name if log.user else "System",
            "action": log.action,
            "details": log.details or ""
            })
        import json
        audit_logs_json = json.dumps(audit_logs)
        return templates.TemplateResponse(request=request, name="technician_dashboard.html", context=ctx(request, user=user, audit_logs_json=audit_logs_json, operators=operators, patients=patients, requests=requests_list, page=1, total_pages=total_pages, error="Email already exists."), status_code=400)
    
    new_op = User(role=ROLE_OPERATOR, name=name, email=email, password_hash=hash_password(password), shift=shift)
    db.add(new_op)
    db.commit()
    log_audit(db, request, user.id, "OPERATOR_CREATED", f"Created operator {email}")
    return RedirectResponse("/technician/dashboard", status_code=303)

@app.post("/technician/patient/{patient_id}/profile", dependencies=[Depends(validate_csrf)])
async def update_patient_profile(
    patient_id: int,
    request: Request,
    db: Session = Depends(get_db),
    birth_date: Optional[str] = Form(None),
    blood_type: Optional[str] = Form(None),
    allergies: Optional[str] = Form(None),
    chronic_conditions: Optional[str] = Form(None),
    medications: Optional[str] = Form(None),
    emergency_contact: Optional[str] = Form(None),
):
    user = current_user(request, db)
    if not is_technician(user):
        return RedirectResponse("/", status_code=303)
        
    patient = db.get(User, patient_id)
    if not patient or patient.role != ROLE_PATIENT:
        return RedirectResponse("/technician/dashboard", status_code=303)
        
    if not patient.profile:
        patient.profile = PatientProfile(user_id=patient.id)
        db.add(patient.profile)
        
    patient.profile.birth_date = birth_date
    patient.profile.blood_type = blood_type
    patient.profile.allergies = allergies
    patient.profile.chronic_conditions = chronic_conditions
    patient.profile.medications = medications
    patient.profile.emergency_contact = emergency_contact
    
    db.commit()
    
    return RedirectResponse("/technician/dashboard", status_code=303)

@app.post("/technician/create_patient", dependencies=[Depends(validate_csrf)])
def create_patient(
    request: Request,
    name: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if not is_technician(user):
        return RedirectResponse("/technician/login", status_code=303)
    
    name = name.strip()
    if db.scalar(select(User.id).where(User.role == ROLE_PATIENT, User.name == name)):
        operators = db.scalars(select(User).where(User.role == ROLE_OPERATOR).order_by(desc(User.created_at))).all()
        patients = db.scalars(select(User).where(User.role == ROLE_PATIENT).options(selectinload(User.operator)).order_by(desc(User.created_at))).all()
        
        limit = 10
        total_requests = db.scalar(select(func.count(HelpRequest.id)))
        total_pages = (total_requests + limit - 1) // limit if total_requests and total_requests > 0 else 1
        requests_list = db.scalars(select(HelpRequest).options(selectinload(HelpRequest.patient), selectinload(HelpRequest.operator)).order_by(desc(HelpRequest.created_at)).offset(0).limit(limit)).all()
        
        audit_logs_db = db.scalars(select(AuditLog).order_by(desc(AuditLog.timestamp)).limit(100)).all()
        audit_logs = []
        for log in audit_logs_db:
            audit_logs.append({
            "timestamp": log.timestamp.isoformat(),
            "ip": log.ip_address or "Unknown",
            "user": log.user.name if log.user else "System",
            "action": log.action,
            "details": log.details or ""
            })
        import json
        audit_logs_json = json.dumps(audit_logs)
        return templates.TemplateResponse(request=request, name="technician_dashboard.html", context=ctx(request, user=user, audit_logs_json=audit_logs_json, operators=operators, patients=patients, requests=requests_list, page=1, total_pages=total_pages, error="Patient name is already registered."), status_code=400)
    
    new_patient = User(role=ROLE_PATIENT, name=name, password_hash=hash_password(password), operator_id=None)
    db.add(new_patient)
    db.commit()
    log_audit(db, request, user.id, "PATIENT_CREATED", f"Created patient {name}")
    return RedirectResponse("/technician/dashboard", status_code=303)

@app.get("/technician/edit_user/{user_id}")
def edit_user_form(request: Request, user_id: int, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not is_technician(user):
        return RedirectResponse("/technician/login", status_code=303)
        
    target_user = db.get(User, user_id)
    if not target_user or target_user.role not in [ROLE_OPERATOR, ROLE_PATIENT]:
        return RedirectResponse("/technician/dashboard", status_code=303)
        
    return templates.TemplateResponse(request=request, name="edit_user.html", context=ctx(request, user=user, target=target_user))

@app.post("/technician/edit_user/{user_id}", dependencies=[Depends(validate_csrf)])
def process_edit_user(
    request: Request,
    user_id: int,
    name: str = Form(...),
    email: Optional[str] = Form(None),
    shift: Optional[str] = Form(None),
    password: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    user = current_user(request, db)
    if not is_technician(user):
        return RedirectResponse("/technician/login", status_code=303)
        
    target_user = db.get(User, user_id)
    if not target_user or target_user.role not in [ROLE_OPERATOR, ROLE_PATIENT]:
        return RedirectResponse("/technician/dashboard", status_code=303)
        
    changes = []
    name = name.strip()
    if target_user.role == ROLE_PATIENT:
        dup = db.scalar(select(User.id).where(User.role == ROLE_PATIENT, User.name == name, User.id != target_user.id))
        if dup:
            return templates.TemplateResponse(request=request, name="edit_user.html", context=ctx(request, user=user, target=target_user, error="Patient name is already registered."), status_code=400)
            
    if target_user.role == ROLE_OPERATOR and email:
        email = email.strip()
        dup = db.scalar(select(User.id).where(User.email == email, User.id != target_user.id))
        if dup:
            return templates.TemplateResponse(request=request, name="edit_user.html", context=ctx(request, user=user, target=target_user, error="Email is already in use."), status_code=400)
        if target_user.email != email:
            changes.append("email")
        target_user.email = email
        if shift and target_user.shift != shift:
            changes.append("shift")
            target_user.shift = shift
            
    if target_user.name != name:
        changes.append("name")
    target_user.name = name
    
    if password and password.strip():
        changes.append("password")
        target_user.password_hash = hash_password(password)
        
    db.commit()
    change_str = "Changed fields: " + ", ".join(changes) if changes else "No fields changed"
    log_audit(db, request, user.id, "OPERATOR_EDITED" if target_user.role == ROLE_OPERATOR else "PATIENT_EDITED", f"Edited {target_user.role} ID {user_id}. {change_str}")
    return RedirectResponse("/technician/dashboard", status_code=303)

@app.post("/technician/delete_user/{user_id}", dependencies=[Depends(validate_csrf)])
def delete_user(request: Request, user_id: int, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not is_technician(user):
        return RedirectResponse("/technician/login", status_code=303)
        
    target_user = db.get(User, user_id)
    if not target_user or target_user.role not in [ROLE_OPERATOR, ROLE_PATIENT]:
        return RedirectResponse("/technician/dashboard", status_code=303)
        
    db.delete(target_user)
    db.commit()
    log_audit(db, request, user.id, "OPERATOR_DELETED" if target_user.role == ROLE_OPERATOR else "PATIENT_DELETED", f"Deleted {target_user.role} ID {target_user.id}")
    return RedirectResponse("/technician/dashboard", status_code=303)

@app.get("/technician/edit_request/{request_id}")
def edit_request_form(request: Request, request_id: int, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not is_technician(user):
        return RedirectResponse("/technician/login", status_code=303)
        
    target_req = db.get(HelpRequest, request_id)
    if not target_req:
        return RedirectResponse("/technician/dashboard", status_code=303)
        
    return templates.TemplateResponse(request=request, name="edit_request.html", context=ctx(request, user=user, target=target_req))

@app.post("/technician/edit_request/{request_id}", dependencies=[Depends(validate_csrf)])
def process_edit_request(
    request: Request,
    request_id: int,
    status: str = Form(...),
    message: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    user = current_user(request, db)
    if not is_technician(user):
        return RedirectResponse("/technician/login", status_code=303)
        
    target_req = db.get(HelpRequest, request_id)
    if not target_req:
        return RedirectResponse("/technician/dashboard", status_code=303)
        
    changes = []
    if target_req.status != status:
        changes.append(f"status to '{status}'")
    target_req.status = status
    
    new_message = message.strip() if message else None
    if target_req.message != new_message:
        changes.append("observations")
    target_req.message = new_message
        
    db.commit()
    change_str = "Changed: " + ", ".join(changes) if changes else "No fields changed"
    log_audit(db, request, user.id, "REQUEST_EDITED", f"Edited request ID {request_id}. {change_str}")
    return RedirectResponse("/technician/dashboard", status_code=303)

@app.post("/technician/delete_request/{request_id}", dependencies=[Depends(validate_csrf)])
def delete_request(request: Request, request_id: int, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not is_technician(user):
        return RedirectResponse("/technician/login", status_code=303)
        
    target_req = db.get(HelpRequest, request_id)
    if not target_req:
        return RedirectResponse("/technician/dashboard", status_code=303)
        
    db.delete(target_req)
    db.commit()
    log_audit(db, request, user.id, "REQUEST_DELETED", f"Deleted request ID {target_req.id}")
    return RedirectResponse("/technician/dashboard", status_code=303)

@app.post("/logout", dependencies=[Depends(validate_csrf)])
def logout(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user:
        log_audit(db, request, user.id, "LOGOUT", "User logged out")
    logout_user(request)
    return RedirectResponse("/", status_code=303)

@app.get("/operator/dashboard", response_class=HTMLResponse, name="operator_dashboard")
def operator_dashboard(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not is_operator(user):
        return RedirectResponse("/operator/login", status_code=303)

    db_requests = db.scalars(
        select(HelpRequest)
        .where(HelpRequest.status != REQUEST_RESOLVED)
        .options(selectinload(HelpRequest.patient), selectinload(HelpRequest.operator))
        .order_by(desc(HelpRequest.created_at))
    ).all()
    
    requests = sorted(db_requests, key=lambda r: 0 if r.operator_id == user.id else (1 if r.operator_id is None else 2))

    now = utcnow()
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    resolved_today = db.scalar(
        select(func.count())
        .select_from(HelpRequest)
        .where(
            HelpRequest.operator_id == user.id,
            HelpRequest.status == REQUEST_RESOLVED,
            HelpRequest.resolved_at >= start_of_today
        )
    ) or 0

    unassigned = [r for r in requests if r.status == REQUEST_REQUESTED]
    if unassigned:
        oldest = min(unassigned, key=lambda x: x.created_at)
        oldest_dt = oldest.created_at
        if oldest_dt.tzinfo is None:
            from datetime import timezone
            oldest_dt = oldest_dt.replace(tzinfo=timezone.utc)
        wait_time = now - oldest_dt
        seconds = int(wait_time.total_seconds())
        longest_wait = f"{seconds} s"
        longest_wait_timestamp = oldest_dt.timestamp()
    else:
        longest_wait = "0 s"
        longest_wait_timestamp = 0

    return templates.TemplateResponse(
        request=request,
        name="operator_dashboard.html",
        context=ctx(
            request,
            user=user,
            requests=requests,
            resolved_today=resolved_today,
            longest_wait=longest_wait,
            longest_wait_timestamp=longest_wait_timestamp,
            REQUEST_REQUESTED=REQUEST_REQUESTED,
            REQUEST_ACKNOWLEDGED=REQUEST_ACKNOWLEDGED,
            REQUEST_RESOLVED=REQUEST_RESOLVED,
        ),
    )

@app.post("/operator/requests/{request_id}/acknowledge", dependencies=[Depends(validate_csrf)])
async def acknowledge_request(request: Request, request_id: int, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not is_operator(user):
        return RedirectResponse("/operator/login", status_code=303)

    item = db.get(HelpRequest, request_id)
    if not item:
        return RedirectResponse("/operator/dashboard", status_code=303)

    if item.status == REQUEST_REQUESTED:
        item.status = REQUEST_ACKNOWLEDGED
        item.operator_id = user.id
        item.acknowledged_at = utcnow()
        item.updated_at = utcnow()
        db.commit()
        log_audit(db, request, user.id, "REQUEST_ACKNOWLEDGED", f"Acknowledged request ID {request_id}")
        
        operator_ids = db.scalars(select(User.id).where(User.role == ROLE_OPERATOR)).all()
        tech_ids = db.scalars(select(User.id).where(User.role == ROLE_TECHNICIAN)).all()
        await manager.send_many([*operator_ids, *tech_ids, item.patient_id], refresh_payload("request_acknowledged"))
    return RedirectResponse(f"/operator/dashboard?open_modal={request_id}", status_code=303)

@app.post("/operator/requests/{request_id}/resolve", dependencies=[Depends(validate_csrf)])
async def resolve_request(request: Request, request_id: int, message: Optional[str] = Form(None), db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not is_operator(user):
        return RedirectResponse("/operator/login", status_code=303)

    item = db.get(HelpRequest, request_id)
    if not item or item.operator_id != user.id:
        return RedirectResponse("/operator/dashboard", status_code=303)

    item.status = REQUEST_RESOLVED
    item.resolved_at = utcnow()
    item.updated_at = utcnow()
    if message:
        item.message = message.strip()
    db.commit()
    log_audit(db, request, user.id, "REQUEST_RESOLVED", f"Resolved request ID {request_id}")
    operator_ids = db.scalars(select(User.id).where(User.role == ROLE_OPERATOR)).all()
    tech_ids = db.scalars(select(User.id).where(User.role == ROLE_TECHNICIAN)).all()
    await manager.send_many([*operator_ids, *tech_ids, item.patient_id], refresh_payload("request_resolved"))
    return RedirectResponse("/operator/dashboard", status_code=303)

@app.get("/patient/login", response_class=HTMLResponse, name="patient_login_form")
def patient_login_form(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user:
        return redirect_to_dashboard(user)
    return templates.TemplateResponse(request=request, name="patient_login.html", context=ctx(request, user=user, error=None))

@app.post("/patient/login", dependencies=[Depends(validate_csrf)])
@limiter.limit("5/minute")
def patient_login(
    request: Request,
    name: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    name = name.strip()
    user = db.scalar(select(User).where(User.role == ROLE_PATIENT, User.name == name.strip()))
    if not user or not verify_password(password, user.password_hash):
        log_audit(db, request, None, "LOGIN_FAILED", f"Failed patient login for {name}")
        return templates.TemplateResponse(request=request, name="patient_login.html", context=ctx(request, user=None, error="Invalid credentials."), status_code=400)
    log_audit(db, request, user.id, "LOGIN_SUCCESS", "Patient logged in")
    login_user(request, user)
    return RedirectResponse("/patient/dashboard", status_code=303)


@app.get("/patient/dashboard", response_class=HTMLResponse, name="patient_dashboard")
def patient_dashboard(request: Request, page: int = 1, sort: str = '', order: str = '', search: str = '', db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not is_patient(user):
        return RedirectResponse("/", status_code=303)

    limit = 5
    offset = (page - 1) * limit

    req_query = select(HelpRequest).where(HelpRequest.patient_id == user.id)
    if search:
        search_id = search.lstrip('#')
        req_query = req_query.where(HelpRequest.status.icontains(search) | cast(HelpRequest.id, String).icontains(search_id))
        
    total_requests = db.scalar(select(func.count()).select_from(req_query.subquery()))
    total_pages = (total_requests + limit - 1) // limit if total_requests and total_requests > 0 else 1

    if sort:
        col = None
        if sort == 'id': col = HelpRequest.id
        elif sort == 'status': col = HelpRequest.status
        elif sort == 'created': col = HelpRequest.created_at
        elif sort == 'updated': col = HelpRequest.updated_at
        
        if col is not None:
            if order == 'asc':
                req_query = req_query.order_by(asc(col))
            else:
                req_query = req_query.order_by(desc(col))
    else:
        req_query = req_query.order_by(desc(HelpRequest.created_at))

    requests_list = db.scalars(
        req_query
        .options(selectinload(HelpRequest.operator))
        .order_by(desc(HelpRequest.created_at))
        .offset(offset)
        .limit(limit)
    ).all()
    
    current_request = db.scalar(select(HelpRequest).where(HelpRequest.patient_id == user.id, HelpRequest.status != REQUEST_RESOLVED).order_by(desc(HelpRequest.created_at)))
    operator = db.get(User, user.operator_id) if user.operator_id else None

    return templates.TemplateResponse(
        request=request,
        name="patient_dashboard.html",
        context=ctx(
            request,
            user=user,
            operator=operator,
            requests=requests_list,
            current_request=current_request,
            page=page,
            total_pages=total_pages,
            search=search,
            sort=sort,
            order=order,
            REQUEST_REQUESTED=REQUEST_REQUESTED,
            REQUEST_ACKNOWLEDGED=REQUEST_ACKNOWLEDGED,
            REQUEST_RESOLVED=REQUEST_RESOLVED,
        ),
    )

@app.post("/patient/request-help", dependencies=[Depends(validate_csrf)])
async def request_help(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not is_patient(user):
        return RedirectResponse("/", status_code=303)

    current = db.scalar(unresolved_request_query(user.id))
    if not current:
        current = HelpRequest(
            patient_id=user.id,
            operator_id=None,
            status=REQUEST_REQUESTED,
            updated_at=utcnow(),
        )
        db.add(current)
        db.commit()
        log_audit(db, request, user.id, "REQUEST_CREATED", "Patient requested help")
        db.refresh(current)
        
        operator_ids = db.scalars(select(User.id).where(User.role == ROLE_OPERATOR)).all()
        tech_ids = db.scalars(select(User.id).where(User.role == ROLE_TECHNICIAN)).all()
        
        payload = refresh_payload("help_requested")
        payload["patient_name"] = user.name
        payload["time"] = current.created_at.strftime("%H:%M") if current.created_at else utcnow().strftime("%H:%M")
        
        await manager.send_many([*operator_ids, *tech_ids, user.id], payload)
    return RedirectResponse("/patient/dashboard", status_code=303)
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, db: Session = Depends(get_db)):
    session = websocket.scope.get("session") or {}
    user_id = session.get("user_id")
    if not user_id:
        await websocket.close(code=1008)
        return

    user = db.get(User, user_id)
    if not user:
        await websocket.close(code=1008)
        return

    await manager.connect(user.id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(user.id, websocket)
    except Exception:
        manager.disconnect(user.id, websocket)
        await websocket.close()

@app.get("/technician/export/operators")
def export_operators(request: Request, search_op: str = "", db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not is_technician(user):
        return RedirectResponse("/technician/login", status_code=303)
        
    op_query = select(User).where(User.role == ROLE_OPERATOR)
    if search_op:
        op_query = op_query.where(User.name.icontains(search_op) | User.email.icontains(search_op) | User.shift.icontains(search_op))
    operators = db.scalars(op_query.order_by(desc(User.created_at))).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Name", "Email", "Shift", "Created At"])
    for op in operators:
        writer.writerow([op.id, op.name, op.email, op.shift, op.created_at.strftime("%Y-%m-%d %H:%M:%S")])
        
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=operators.csv"}
    )

@app.get("/technician/export/patients")
def export_patients(request: Request, search_pat: str = "", db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not is_technician(user):
        return RedirectResponse("/technician/login", status_code=303)
        
    pat_query = select(User).where(User.role == ROLE_PATIENT)
    if search_pat:
        pat_query = pat_query.where(User.name.icontains(search_pat))
    patients = db.scalars(pat_query.order_by(desc(User.created_at))).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Name", "Created At"])
    for p in patients:
        writer.writerow([p.id, p.name, p.created_at.strftime("%Y-%m-%d %H:%M:%S")])
        
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=patients.csv"}
    )

@app.get("/technician/export/history")
def export_history(request: Request, search_req: str = "", db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not is_technician(user):
        return RedirectResponse("/technician/login", status_code=303)
        
    req_query = select(HelpRequest)
    if search_req:
        req_query = req_query.outerjoin(User, HelpRequest.patient_id == User.id).where(HelpRequest.status.icontains(search_req) | User.name.icontains(search_req))
        
    requests_list = db.scalars(
        req_query
        .options(selectinload(HelpRequest.patient), selectinload(HelpRequest.operator))
        .order_by(desc(HelpRequest.created_at))
    ).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Patient", "Operator", "Status", "Observations", "Created At", "Acknowledged At", "Resolved At"])
    for r in requests_list:
        op_name = r.operator.name if r.operator else ""
        ack_time = r.acknowledged_at.strftime("%Y-%m-%d %H:%M:%S") if r.acknowledged_at else ""
        res_time = r.resolved_at.strftime("%Y-%m-%d %H:%M:%S") if r.resolved_at else ""
        writer.writerow([
            r.id, 
            r.patient.name if r.patient else "", 
            op_name, 
            r.status, 
            r.message or "", 
            r.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            ack_time,
            res_time
        ])
        
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=assistance_history.csv"}
    )

@app.get("/technician/export/audit_logs")
def export_audit_logs(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not is_technician(user):
        return RedirectResponse("/technician/login", status_code=303)
        
    audit_logs_list = db.scalars(select(AuditLog).order_by(desc(AuditLog.timestamp))).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Time", "IP", "User", "Action", "Details"])
    for log in audit_logs_list:
        writer.writerow([
            log.timestamp.isoformat(),
            log.ip_address or "Unknown",
            log.user.name if log.user else "System",
            log.action,
            log.details or ""
        ])
        
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=security_audit_logs.csv"}
    )
