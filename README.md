# 🏥 Telecare System

![Docker](https://img.shields.io/badge/Docker-Chainguard-blue.svg)
![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-00a393.svg)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0+-red.svg)
![Vanilla JS](https://img.shields.io/badge/JavaScript-Vanilla-F7DF1E.svg)

A real-time telecare system designed to connect patients with medical operators through an agile workflow and an intuitive, modern interface. Built with performance and security in mind.

<div align="center">
  <a href="#visual-overview">
    <img src="assets/screenshots/telecare_landing_page.png" alt="Telecare Landing Page" width="100%">
  </a>
  <br><br>
  <a href="#visual-overview">
    <img src="https://img.shields.io/badge/📸_Explore_Visual_Overview-00a393?style=for-the-badge" alt="Explore Visual Overview" />
  </a>
  <br><br>
</div>

## ✨ Core Features
- **Real-Time Communication:** Instant assistance requests and status updates powered by WebSockets. No page reloads required.
- **Secure Role Management:** Three deeply segregated authorization levels with dedicated dashboards: Technicians (Admin), Operators, and Patients.
- **Comprehensive Audit Trail:** All critical actions (creation, editing, deletion of users and requests) are logged in real-time for security auditing.
- **Modern UI/UX:** Responsive design with glassmorphism aesthetics, dark mode support, and smooth micro-animations.

## 🛠️ Tech Stack
- **Backend:** FastAPI (Python)
- **Database:** PostgreSQL
- **ORM:** SQLAlchemy 2.0
- **Frontend:** Jinja2 Templates, Vanilla JavaScript, CSS3 variables
- **Security:** CSRF Protection, Bcrypt Password Hashing, SlowAPI (Rate Limiting)

## 📂 Project Structure
```text
telecare/
├── app/
│   ├── main.py          # FastAPI application, routing, and WebSockets
│   ├── models.py        # SQLAlchemy database schemas
│   ├── config.py        # Environment variables and secrets
│   ├── auth.py          # Hashing, CSRF generation, and session validation
│   ├── db.py            # Database engine and sessionmaker
│   ├── init_db.py       # Script to initialize tables
│   ├── templates/       # Jinja2 HTML views
│   └── static/          # CSS stylesheets and SVG assets
├── docker-compose.yml   # Multi-container orchestration
├── Dockerfile           # Multi-stage image build (Chainguard)
├── .env.example         # Environment variables template
├── run.py               # Uvicorn server launcher
└── requirements.txt     # Python dependencies
```

## ⚙️ Configuration & Initialization
**STOP: Do not skip this section.** You must configure your application secrets before initializing the database or starting the server.

### Step 1: Configure Secrets & Database
Copy the example environment file and fill in your values:
```bash
cp .env.example .env
```

Open `.env` and set the following:

**Security & Sessions:**
- `SECRET_KEY`: Generate a strong one with `python -c "import secrets; print(secrets.token_hex(32))"`
- `USE_HTTPS`: Set to `true` if deploying with an SSL certificate (HTTPS).

**Database:**
- `DATABASE_URL`: PostgreSQL connection string (e.g., `postgresql+psycopg2://username:password@localhost:5432/telecare_db`). *Note: The PostgreSQL driver (`psycopg2-binary`) is already included.*

**First-Time Admin:**
- `TECHNICIAN_EMAIL`: Your admin email to log into the Technician Dashboard.
- `TECHNICIAN_PASSWORD`: A strong password for the Technician Dashboard.

> **CRITICAL:** Never commit your `.env` file. It is already listed in `.gitignore`.

### Step 2: Initialize Database
Once you have configured your `.env`, initialize the database schemas by running:
```bash
python -m app.init_db
```

## 💻 Usage

### Docker (recommended)
```bash
cp .env.example .env
# Edit .env with your values
docker compose up --build -d
```
Access the app at `http://localhost:8000`.

## 📸 Visual Overview
<a id="visual-overview"></a>

### Telecare: Landing Page
Landing page of the Telecare platform. Navbar with logo and three role-based login entries (Technician, Operator, Patient). Hero section featuring the headline "Operational assistance, delivered in real time," supporting subtext, "Get Started"/"Explore Features" CTAs, and a dashboard preview mockup.

![Telecare: Landing Page](assets/screenshots/telecare_landing_page.png)

### Telecare: Technician Login
Technician Login screen for the Telecare admin role. Centered card with gear icon, email and password fields, and a "Login" call-to-action button, keeping the same navbar with role-based access shortcuts.

![Telecare: Technician Login](assets/screenshots/telecare_technician_login.png)

### Telecare: Technician Dashboard
Technician Dashboard with key metrics (requests today, pending requests, avg. response time), a 7-day requests trend chart, a requests-by-shift donut chart, and operator management tools: create new operator form, searchable operators table with edit/delete actions, and CSV export.

![Telecare: Technician Dashboard](assets/screenshots/telecare_technician_dashboard.png)

### Telecare: Operator & Patient Management
User management section of the Technician Dashboard. Includes a "Create New Operator" form with shift assignment, a paginated, searchable Registered Operators table, plus a "Create New Patient" form and a Registered Patients table with Edit, Profile, and Delete actions.

![Telecare: Operator & Patient Management](assets/screenshots/telecare_operator__patient_management.png)

### Telecare: Assistance History
Assistance History table logging every patient request: ID, patient, operator, status, observations, and timestamp, with searchable/paginated records, "View" detail links, Edit/Delete actions, and CSV export. Bottom preview of the Security Audit Logs section.

![Telecare: Assistance History](assets/screenshots/telecare_assistance_history.png)

### Telecare: Security Audit Logs
Security Audit Logs panel tracking system activity in real time: timestamp, IP address, user, action type (login/logout), and event details. Filterable by action, searchable, paginated, and exportable to CSV for full traceability.

![Telecare: Security Audit Logs](assets/screenshots/telecare_security_audit_logs.png)

### Telecare: Operator Dashboard
Operator Dashboard showing real-time shift status: unassigned emergencies, longest unassigned wait time, and requests handled today. Live "Incoming Help Requests" table with patient, status, assignment, and action columns, plus a notification volume control for instant alert awareness.

![Telecare: Operator Dashboard](assets/screenshots/telecare_operator_dashboard.png)

### Telecare: Patient Dashboard
Patient Dashboard with a one-click "Request Assistance Now" emergency button, live status indicator ("Safe / Idle"), and a searchable, paginated Request History table showing each request's ID, status, creation, and last-updated timestamps.

![Telecare: Patient Dashboard](assets/screenshots/telecare_patient_dashboard.png)

### Telecare: Active Emergency Request
Patient Dashboard right after submitting an emergency request. Current Status updates instantly to "REQUESTED" with a timestamp, while Request History logs the new entry (#123) alongside prior resolved requests, demonstrating the platform's real-time responsiveness.

![Telecare: Active Emergency Request](assets/screenshots/telecare_active_emergency_request.png)

### Telecare: Live Emergency Alert
Operator Dashboard receiving the patient's request in real time via WebSockets: a warning icon and updated "Unassigned Emergencies" counter appear instantly, with wait time tracking and a one-click "Acknowledge" action to claim the incoming request.

![Telecare: Live Emergency Alert](assets/screenshots/telecare_live_emergency_alert.png)

### Telecare: Resolve Request Modal
"Resolve Request" modal giving operators full patient context at a glance: name, age/blood type, allergies, conditions, medications, emergency contact, and a live elapsed-time counter. Operators select patient condition (Stable/Observation/Critical), choose an action taken, add optional notes, and save to close the case.

![Telecare: Resolve Request Modal](assets/screenshots/telecare_resolve_request_modal.png)

## License
GPL v3 — see [LICENSE](LICENSE)
