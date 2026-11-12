# VITALIS — Quarantine & Patient Recovery Management System

*Precision in Care. Efficiency in Recovery.*

A Streamlit application for a 74-bed quarantine facility. It replaces handwritten temperature
journals with one enforced workflow:

**Nurse records temperature → patient is Ready for Doctor → doctor completes visit → doctor approves
discharge when eligible → admin completes checkout → room is cleaned → room is Available.**

## Demo accounts

| Portal | Username | Password | Signed-in user |
|--------|----------|-----------|----------------|
| Nurse  | `nurse`  | `nurse123`  | Charge Nurse |
| Doctor | `doctor` | `doctor123` | Head Doctor (patient records + facility analytics) |
| Admin  | `admin`  | `admin123`  | Administration Officer |

Passwords are stored as salted PBKDF2-SHA256 hashes. These accounts are for demonstration only.

## Run locally

Requires Python 3.10 or newer.

```bash
pip install -r requirements.txt
streamlit run app.py
```

The database (`data/vitalis.db`) and the sample dataset are created automatically on first launch.

## Project structure

| File | Purpose |
|------|---------|
| `app.py` | Streamlit screens, navigation and role-based routing |
| `services.py` | All business rules (the UI cannot bypass them) |
| `db.py` | SQLite connection, transactions and schema |
| `seed.py` | Sample dataset, generated relative to today's date |
| `ui.py` | Theme CSS and reusable components |
| `tests/test_workflow.py` | Automated check of the 13 acceptance scenarios |
| `.streamlit/config.toml` | Theme colours |

## Database schema (SQLite)

| Table | Key columns |
|-------|-------------|
| `users` | `username` PK, `password_hash`, `role`, `full_name`, `title` |
| `patients` | `patient_id` PK, demographics, `admission_date`, `room_id` → rooms, `status` |
| `rooms` | `room_id` PK, `room_number`, `floor`, `status`, `current_patient_id` → patients |
| `temperature_records` | `record_id` PK, `patient_id` → patients, `record_date`, `temperature_c`, `is_fever`, `threshold_c`, `record_type`, `is_active`, `supersedes_id`, `correction_reason`, `recorded_by` → users |
| `doctor_visits` | `visit_id` PK, `patient_id`, `visit_date`, `doctor` → users, `temperature_record_id`, notes; UNIQUE (`patient_id`, `visit_date`) |
| `treatment_records` | `treatment_id` PK, `visit_id` → doctor_visits, `treatment`, `medication`, `dosage` |
| `discharge_approvals` | `approval_id` PK, `patient_id` UNIQUE, `approved_by`, `approved_at`, `qualifying_dates`, `checkout_at`, `checkout_by` |
| `patient_outcomes` | `outcome_id` PK, `patient_id` UNIQUE, `outcome` (Recovered / Deceased), `outcome_at`, `recorded_by`, `notes` |
| `audit_logs` | `log_id` PK, `logged_at`, `actor`, `role`, `action`, `entity_type`, `entity_id`, `details` |
| `settings` | fever threshold, patient ID sequence, demo clock |

Rules enforced by the database itself: one active temperature reading per patient per day (partial
unique index), one doctor visit per patient per day, one discharge approval and one outcome per patient.

## How the rules are applied

- **Fever threshold:** 38.0 °C by default; readings at or above it are fever. The Head Doctor can change it
  under *Facility Analytics → Clinical settings*. Each reading stores the threshold in force when it was taken.
- **Fever-free streak:** counts complete calendar days only, working back from yesterday. Today's reading
  never counts until the day has ended. A fever reading today resets the streak to 0 at once. A day with no
  reading breaks the streak. The admission day is a partial day and is not counted.
- **Discharge eligibility:** streak of 3 or more. The approval button exists only for eligible patients and
  the service re-checks the rule when it is pressed.
- **Admission temperature:** the initial temperature taken at admission is that day's reading, so a patient
  admitted today goes straight to *Ready for Doctor* and is not measured twice.
- **Corrections:** a nurse or doctor can correct today's reading with a mandatory reason. The original
  reading is kept, marked superseded and linked to the correction; the change is written to the audit log.
- **Deaths:** recorded by a doctor with notes and an explicit confirmation. The room moves to
  *Pending Cleaning* immediately and the patient leaves the occupied count.
- **Statistics:** Mortality = deaths ÷ total admissions; Recovery = recoveries ÷ total admissions. Patients
  in the admission queue (registered, no room yet) are not admissions. The 85% figure is shown as the
  complement of the 15% mortality benchmark, not as a guaranteed recovery rate.
- **Timezone:** Asia/Kolkata for every date and timestamp.

## Demonstration tools (Admin → System Settings)

- **Advance to next day:** moves the application date forward one day, so you can show a patient's third
  fever-free day completing, or a missed check breaking a streak, without waiting overnight.
- **Reset demo data:** reloads the sample dataset.
- **Audit log:** the latest 200 recorded actions.

## Testing

```bash
python tests/test_workflow.py
```

The script runs on a temporary database and checks each scenario:

| # | Scenario | How to show it in the app |
|---|----------|---------------------------|
| 1 | Normal temperature → Ready for Doctor | Nurse → Temperature Entry → submit 36.9 |
| 2 | Duplicate same-day reading blocked | Same patient: the form is replaced by today's reading |
| 3 | Fever resets the streak | Nurse → record 38.6 for a patient with a streak |
| 4 | Visit blocked before temperature | Doctor → Visit & Treatment → pick an *Awaiting Nurse* patient |
| 5 | Visit → Doctor Visit Completed | Doctor → Rounds Queue → Start visit → complete the form |
| 6 | Three complete fever-free days → eligible | Doctor → Discharge & Outcomes (or use *Advance to next day*) |
| 7 | Approval → Admin discharge queue | Doctor → Approve Discharge, then Admin → Discharge Queue |
| 8 | Checkout → Recovered, room Pending Cleaning | Admin → Complete Patient Checkout |
| 9 | Room cleaned → Available | Admin → Room Management → Mark Room Cleaned |
| 10 | New patient into the freed room | Admin → Patient Registration |
| 11 | Death recorded, statistics update | Doctor → Discharge & Outcomes → Record patient death |
| 12 | Mortality above 15% → red warning | The sample data sits at 13.6%; one recorded death takes it to 15.2% |
| 13 | Data persists after refresh | Refresh the browser and sign in again |

## Deploy to Streamlit Community Cloud

### 1. Put the project on GitHub

1. Create a new repository at <https://github.com/new> (for example `vitalis`). Public is simplest.
2. Upload the files, keeping the folder layout: on the repository page choose **Add file → Upload files**,
   drag in everything from this folder (including `.streamlit` and `tests`), and commit. Or from a terminal:

```bash
git init
git add .
git commit -m "VITALIS patient recovery management system"
git branch -M main
git remote add origin https://github.com/<your-username>/vitalis.git
git push -u origin main
```

`app.py` and `requirements.txt` must be at the top level of the repository.

### 2. Deploy

1. Go to <https://share.streamlit.io> and sign in with GitHub.
2. Click **Create app**, then choose to deploy from GitHub.
3. Select the repository, branch `main` and main file path `app.py`.
4. Optionally choose a custom subdomain under **App URL**.
5. Click **Deploy**. The first build takes a few minutes.

### 3. Get the public URL

When the build finishes the app opens at `https://<your-subdomain>.streamlit.app`. That address in the
browser bar is the public URL; you can also copy it from **Share** at the top right of the app, or from
your app list at share.streamlit.io. This project has not been deployed for you, so no URL exists until
you complete these steps.

### Data persistence on Community Cloud

Data is stored in SQLite and survives page refreshes, sign-outs and app restarts. Streamlit Community
Cloud does not keep local files permanently, though: when the app is rebooted, redeployed or woken from
sleep, the container is rebuilt and the app starts again from the sample dataset. That is fine for a
demonstration. For data that must outlive redeployments, point the app at a hosted database.

Refreshing the browser ends the Streamlit session, so you sign in again; no data is lost.
