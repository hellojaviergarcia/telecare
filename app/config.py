# Copyright (C) 2026 Javier Garcia
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

import os

# ==============================================================================
# SYSTEM CONFIGURATION
# General system settings that usually do not need to be changed.
# ==============================================================================
APP_NAME = os.getenv("APP_NAME", "Telecare")
SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "teleassist_session")


# ==============================================================================
# ⚠️ PRODUCTION CONFIGURATION ⚠️
# Variables that MUST be reviewed and modified before deploying to production.
# ==============================================================================

# SECURITY WARNING: Keep the secret key used in production secret!
# Used for encrypting session cookies. Change this to a long, random string.
SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")

# DATABASE CONNECTION:
# To migrate to PostgreSQL, change this URL.
# Example: "postgresql://username:password@localhost:5432/telecare_db"
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./teleassist.db")

# SECURITY WARNING: Change these default technician (admin) credentials before deploying!
# These are used to log into the Technician Dashboard for the first time.
TECHNICIAN_EMAIL = os.getenv("TECHNICIAN_EMAIL", "admin@telecare.com")
TECHNICIAN_PASSWORD = os.getenv("TECHNICIAN_PASSWORD", "admin")

# SECURITY WARNING: Set this to True when deploying to a production environment with HTTPS.
# This ensures that session cookies are only sent over secure HTTPS connections.
USE_HTTPS = False
