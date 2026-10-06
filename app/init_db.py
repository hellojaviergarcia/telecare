# Copyright (C) 2026 Javier Garcia
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from sqlalchemy.orm import Session
from .db import Base, engine, get_db
from . import models
from .auth import hash_password
from .config import TECHNICIAN_EMAIL, TECHNICIAN_PASSWORD

def main() -> None:
    Base.metadata.create_all(bind=engine)
    
    with Session(engine) as db:
        try:
            from sqlalchemy import text
            db.execute(text("ALTER TABLE patient_profiles ADD COLUMN birth_date VARCHAR(10)"))
            db.commit()
        except:
            pass

        technician = db.query(models.User).filter_by(role=models.ROLE_TECHNICIAN, email=TECHNICIAN_EMAIL).first()
        if not technician:
            technician = models.User(
                role=models.ROLE_TECHNICIAN,
                name="System Technician",
                email=TECHNICIAN_EMAIL,
                password_hash=hash_password(TECHNICIAN_PASSWORD)
            )
            db.add(technician)
            db.commit()

if __name__ == "__main__":
    main()
