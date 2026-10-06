# Copyright (C) 2026 Javier Garcia
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Boolean
from sqlalchemy.orm import backref, relationship

from .db import Base

ROLE_OPERATOR = "operator"
ROLE_PATIENT = "patient"
ROLE_TECHNICIAN = "technician"

REQUEST_REQUESTED = "requested"
REQUEST_ACKNOWLEDGED = "acknowledged"
REQUEST_RESOLVED = "resolved"

INVITE_ACTIVE = "active"
INVITE_REDEEMED = "redeemed"

def utcnow():
    return datetime.now(timezone.utc)

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    role = Column(String(20), nullable=False, index=True)
    email = Column(String(255), unique=True, index=True, nullable=True)
    name = Column(String(120), nullable=False)
    password_hash = Column(String(255), nullable=False)
    shift = Column(String(50), nullable=True)
    operator_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    dark_mode = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    operator = relationship(
        "User",
        remote_side=[id],
        foreign_keys=[operator_id],
        backref=backref("patients", lazy="selectin"),
    )
    
    profile = relationship("PatientProfile", uselist=False, back_populates="user", lazy="selectin")

class PatientProfile(Base):
    __tablename__ = "patient_profiles"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)
    age = Column(Integer, nullable=True) # Deprecated
    birth_date = Column(String(10), nullable=True) # YYYY-MM-DD
    blood_type = Column(String(10), nullable=True)
    allergies = Column(String(500), nullable=True)
    chronic_conditions = Column(String(500), nullable=True)
    medications = Column(String(500), nullable=True)
    emergency_contact = Column(String(255), nullable=True)

    user = relationship("User", back_populates="profile")

    @property
    def computed_age(self):
        if not self.birth_date:
            return None
        try:
            from datetime import datetime
            bdate = datetime.strptime(self.birth_date, "%Y-%m-%d")
            today = datetime.now()
            return today.year - bdate.year - ((today.month, today.day) < (bdate.month, bdate.day))
        except:
            return None

class Invitation(Base):
    __tablename__ = "invitations"

    id = Column(Integer, primary_key=True)
    code = Column(String(32), unique=True, index=True, nullable=False)
    operator_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    patient_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(String(20), nullable=False, default=INVITE_ACTIVE)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    redeemed_at = Column(DateTime(timezone=True), nullable=True)

    operator = relationship("User", foreign_keys=[operator_id], backref=backref("invitations", lazy="selectin"))
    patient = relationship("User", foreign_keys=[patient_id])

class HelpRequest(Base):
    __tablename__ = "help_requests"

    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    operator_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    status = Column(String(20), nullable=False, default=REQUEST_REQUESTED, index=True)
    message = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    patient = relationship("User", foreign_keys=[patient_id])
    operator = relationship("User", foreign_keys=[operator_id], backref=backref("help_requests", lazy="selectin"))


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    ip_address = Column(String(50), nullable=True)
    action = Column(String(50), nullable=False, index=True)
    details = Column(String(500), nullable=True)

    user = relationship("User", foreign_keys=[user_id])
