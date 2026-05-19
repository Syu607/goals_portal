# AtomQuest Hackathon 1.0 — In‑House Goal Setting & Tracking Portal

## Working link

- Hosted URL (Vercel): (paste deployed link here)
- Demo URL (local): http://127.0.0.1:8000/

Run locally:

```bash
cd C:\Users\msiza\Desktop\atomquest-goals-portal
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --port 8000
```

## Source code repository

- Repository URL: (paste GitHub/GitLab/Bitbucket link here)

Suggested push commands:

```bash
cd C:\Users\msiza\Desktop\atomquest-goals-portal
git remote add origin <YOUR_REPO_URL>
git push -u origin master
```

## Deploy (Vercel — free)

This repo includes `api/index.py` and `vercel.json` for Vercel deployment.

Recommended Vercel env var:

- `SESSION_SECRET` = any long random string (keeps sessions stable across restarts)

Note: SQLite runs from ephemeral storage on Vercel (`/tmp`). This is fine for demo, but data may reset on cold starts.

```bash
cd C:\Users\msiza\Desktop\atomquest-goals-portal
npm i -g vercel
vercel login
vercel --prod
```

## Login credentials (demo)

- Admin / HR: `admin` / `admin123`
- Manager (L1): `manager1` / `manager123`
- Employee: `employee1` / `employee123`
- Employee: `employee2` / `employee123`

## Architecture diagram

```mermaid
flowchart LR

U["Browser<br>Employee / Manager / Admin"]
--> |HTTP|
W["FastAPI Web App<br>Server-rendered UI (Jinja2)<br>Role-based Routes"]

W --> A["Auth<br>Session Cookie"]

W --> G["Goal Management<br>Draft → Submit → Approve/Lock<br>Shared Goals (Synced Achievements)"]

W --> C["Check-ins<br>Quarterly Updates + Manager Comments<br>Progress Score Formulas"]

W --> R["Reporting<br>CSV Export + Completion Dashboard"]

W --> L["Audit Trail<br>Field-level Change Logs After Unlock"]

W --> D[("SQLite Database")]
```


## Requirement coverage (Phase 1 + Phase 2)

- Roles: Employee / Manager / Admin (separate dashboards + access control).
- Goal creation: thrust area, title/description, UoM (min/max/timeline/zero), targets, weightage.
- Validations at submission/approval: max 8 goals, min 10% per goal, total weightage = 100%.
- Manager approval workflow: review submitted sheets, inline target/weight edits, approve (locks) or return for rework.
- Shared goals: manager pushes a shared KPI to multiple employees; recipients can adjust weightage only; achievement updates are synced via the primary owner.
- Quarterly updates: employees enter actuals and status; system computes progress score per UoM formula.
- Manager check-ins: view planned vs actual, save structured comment per quarter.
- Reporting: CSV export of planned vs actual (quarter parameter).
- Governance: admin unlock/lock + audit trail for post-lock edits; completion dashboard (E/M completion per quarter).
