"""Business rules for VITALIS.

Every workflow rule (one reading per day, visit only after temperature,
three complete fever-free days, role permissions, single outcome, room
turnover) is enforced here, so the UI cannot bypass it.
"""

import hashlib
import hmac
import json
import re
import secrets
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import db

APP_TZ = ZoneInfo("Asia/Kolkata")
CAPACITY = 74
REQUIRED_FEVER_FREE_DAYS = 3
DEFAULT_FEVER_THRESHOLD = 38.0
CRITICAL_TEMP = 39.5
MORTALITY_BENCHMARK = 15.0
RECOVERY_BENCHMARK = 85.0
IN_FACILITY = ("Admitted", "Discharge Approved")
TS_FMT = "%Y-%m-%d %H:%M:%S"

NEEDS_TEMP = "Needs Temp Check"
TEMP_RECORDED = "Temperature Recorded"
READY = "Ready for Doctor"
VISIT_DONE = "Doctor Visit Completed"


class WorkflowError(Exception):
    """A request that breaks a workflow or validation rule."""


# ----------------------------------------------------------------- settings
def get_setting(key, default=None):
    with db.read() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def demo_day_offset() -> int:
    try:
        return int(get_setting("demo_day_offset", "0"))
    except (TypeError, ValueError, Exception):
        return 0


def now() -> datetime:
    """Current application time in Asia/Kolkata (plus the demo-clock offset)."""
    current = datetime.now(APP_TZ).replace(tzinfo=None, microsecond=0)
    return current + timedelta(days=demo_day_offset())


def today() -> date:
    return now().date()


def fever_threshold() -> float:
    return float(get_setting("fever_threshold", str(DEFAULT_FEVER_THRESHOLD)))


# ---------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    iterations = 120_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def authenticate(username: str, password: str):
    """Return the user dict when credentials are valid, otherwise None."""
    username = (username or "").strip().lower()
    with db.read() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not row or not verify_password(password or "", row["password_hash"]):
        return None
    user = {k: row[k] for k in ("username", "role", "full_name", "title")}
    with db.transaction() as conn:
        _audit(conn, now(), user, "LOGIN", "User", username, "Signed in")
    return user


# ------------------------------------------------------------------ helpers
def _audit(conn, ts, user, action, entity_type, entity_id, details=""):
    conn.execute(
        "INSERT INTO audit_logs (logged_at, actor, role, action, entity_type, entity_id, details) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (ts.strftime(TS_FMT), user["username"], user["role"], action, entity_type,
         None if entity_id is None else str(entity_id), details),
    )


def _actor(conn, username, roles, denied_message):
    row = conn.execute("SELECT username, role, full_name FROM users WHERE username = ?", (username,)).fetchone()
    if not row or row["role"] not in roles:
        raise WorkflowError(denied_message)
    return dict(row)


def _inpatient(conn, patient_id):
    row = conn.execute(
        "SELECT p.*, r.room_number FROM patients p LEFT JOIN rooms r ON r.room_id = p.room_id "
        "WHERE p.patient_id = ?", (patient_id,)).fetchone()
    if not row:
        raise WorkflowError("Patient record not found.")
    if row["status"] not in IN_FACILITY:
        raise WorkflowError(f"{row['full_name']} is no longer an in-patient (status: {row['status']}).")
    return row


def _valid_temp(value) -> float:
    try:
        temp = round(float(value), 1)
    except (TypeError, ValueError):
        raise WorkflowError("Enter the temperature as a number in °C.")
    if not 34.0 <= temp <= 43.0:
        raise WorkflowError("Temperature must be between 34.0 °C and 43.0 °C. Check the reading and try again.")
    return temp


def _next_patient_id(conn) -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = 'patient_seq'").fetchone()
    seq = int(row["value"]) + 1 if row else 1
    conn.execute("INSERT INTO settings (key, value) VALUES ('patient_seq', ?) "
                 "ON CONFLICT (key) DO UPDATE SET value = excluded.value", (str(seq),))
    return f"VT-{seq:05d}"


def fever_free_streak(day_map, on_date: date, admission_date: date):
    """Count complete, consecutive fever-free calendar days.

    day_map maps date -> True (fever) / False (normal) for the effective
    reading of each day. Rules:
      * today is never counted, because the day has not ended;
      * a fever reading today resets the streak to zero immediately;
      * a day with no reading breaks the streak (missing is never fever-free);
      * the admission day is a partial day and is not counted.
    Returns (streak, [qualifying dates, oldest first]).
    """
    if day_map.get(on_date) is True:
        return 0, []
    dates = []
    day = on_date - timedelta(days=1)
    while day > admission_date and day_map.get(day) is False:
        dates.append(day)
        day -= timedelta(days=1)
    return len(dates), sorted(dates)


def _day_map(conn, patient_id):
    rows = conn.execute(
        "SELECT record_date, is_fever FROM temperature_records WHERE patient_id = ? AND is_active = 1",
        (patient_id,)).fetchall()
    return {date.fromisoformat(r["record_date"]): bool(r["is_fever"]) for r in rows}


# -------------------------------------------------------------------- reads
def list_inpatients():
    """All patients currently in the facility, with today's workflow state computed."""
    current = now()
    on_date = current.date()
    with db.read() as conn:
        patients = conn.execute(
            "SELECT p.*, r.room_number FROM patients p JOIN rooms r ON r.room_id = p.room_id "
            "WHERE p.status IN ('Admitted', 'Discharge Approved') ORDER BY r.room_number").fetchall()
        temps = conn.execute(
            "SELECT t.* FROM temperature_records t JOIN patients p ON p.patient_id = t.patient_id "
            "WHERE t.is_active = 1 AND p.status IN ('Admitted', 'Discharge Approved') "
            "ORDER BY t.record_date").fetchall()
        visits = {r["patient_id"]: r for r in conn.execute(
            "SELECT * FROM doctor_visits WHERE visit_date = ?", (on_date.isoformat(),))}
        yesterday_visits = {r["patient_id"] for r in conn.execute(
            "SELECT patient_id FROM doctor_visits WHERE visit_date = ?",
            ((on_date - timedelta(days=1)).isoformat(),))}
        approvals = {r["patient_id"]: r for r in conn.execute(
            "SELECT * FROM discharge_approvals WHERE checkout_at IS NULL")}

    by_patient = {}
    for t in temps:
        by_patient.setdefault(t["patient_id"], []).append(t)

    result = []
    for p in patients:
        pid = p["patient_id"]
        records = by_patient.get(pid, [])
        admission = date.fromisoformat(p["admission_date"])
        day_map = {date.fromisoformat(t["record_date"]): bool(t["is_fever"]) for t in records}
        today_rec = next((t for t in records if t["record_date"] == on_date.isoformat()), None)
        streak, qualifying = fever_free_streak(day_map, on_date, admission)

        fever_days = 0
        if records and records[-1]["is_fever"]:
            day = date.fromisoformat(records[-1]["record_date"])
            while day_map.get(day) is True:
                fever_days += 1
                day -= timedelta(days=1)

        visit = visits.get(pid)
        if today_rec is None:
            workflow = NEEDS_TEMP
        elif visit is None:
            workflow = READY
        else:
            workflow = VISIT_DONE

        yesterday = on_date - timedelta(days=1)
        was_here_yesterday = admission <= yesterday
        today_temp = today_rec["temperature_c"] if today_rec else None
        today_fever = bool(today_rec["is_fever"]) if today_rec else False
        if today_rec is None:
            priority, priority_label = 9, "Awaiting Nurse"
        elif today_temp >= CRITICAL_TEMP:
            priority, priority_label = 1, "Critical fever"
        elif today_fever:
            priority, priority_label = 2, "Persistent fever" if fever_days >= 2 else "Fever"
        elif streak >= 1:
            priority, priority_label = 3, "Recovering"
        else:
            priority, priority_label = 4, "Stable"

        approval = approvals.get(pid)
        result.append({
            "patient_id": pid, "full_name": p["full_name"], "age": p["age"], "gender": p["gender"],
            "contact": p["contact"], "symptoms": p["symptoms"], "admission_date": admission,
            "days_admitted": (on_date - admission).days,
            "room_id": p["room_id"], "room_number": p["room_number"], "status": p["status"],
            "today_temp": today_temp, "today_fever": today_fever,
            "today_record_id": today_rec["record_id"] if today_rec else None,
            "today_recorded_at": today_rec["recorded_at"] if today_rec else None,
            "today_recorded_by": today_rec["recorded_by"] if today_rec else None,
            "today_record_type": today_rec["record_type"] if today_rec else None,
            "last_temp": records[-1]["temperature_c"] if records else None,
            "last_temp_date": records[-1]["record_date"] if records else None,
            "visit_today": visit is not None,
            "visit_at": visit["visited_at"] if visit else None,
            "workflow": workflow, "streak": streak, "qualifying_dates": qualifying,
            "eligible": p["status"] == "Admitted" and streak >= REQUIRED_FEVER_FREE_DAYS,
            "fever_days": fever_days,
            "missed_temp_yesterday": was_here_yesterday and yesterday not in day_map,
            "missed_visit_yesterday": was_here_yesterday and pid not in yesterday_visits,
            "priority": priority, "priority_label": priority_label,
            "approved_by": approval["approved_by"] if approval else None,
            "approved_at": approval["approved_at"] if approval else None,
        })
    return result


def list_rooms():
    with db.read() as conn:
        rows = conn.execute(
            "SELECT r.*, p.full_name FROM rooms r LEFT JOIN patients p ON p.patient_id = r.current_patient_id "
            "ORDER BY r.room_id").fetchall()
    return [dict(r) for r in rows]


def list_waiting():
    with db.read() as conn:
        rows = conn.execute(
            "SELECT * FROM patients WHERE status = 'Awaiting Admission' ORDER BY registered_at").fetchall()
    return [dict(r) for r in rows]


def patient_history(patient_id):
    with db.read() as conn:
        patient = conn.execute(
            "SELECT p.*, r.room_number FROM patients p LEFT JOIN rooms r ON r.room_id = p.room_id "
            "WHERE p.patient_id = ?", (patient_id,)).fetchone()
        temps = conn.execute(
            "SELECT * FROM temperature_records WHERE patient_id = ? ORDER BY record_date, record_id",
            (patient_id,)).fetchall()
        visits = conn.execute(
            "SELECT * FROM doctor_visits WHERE patient_id = ? ORDER BY visited_at DESC", (patient_id,)).fetchall()
        treatments = conn.execute(
            "SELECT * FROM treatment_records WHERE patient_id = ? ORDER BY prescribed_at DESC",
            (patient_id,)).fetchall()
    return {
        "patient": dict(patient) if patient else None,
        "temps": [dict(r) for r in temps],
        "visits": [dict(r) for r in visits],
        "treatments": [dict(r) for r in treatments],
    }


def facility_stats():
    """Outcome statistics. Every rate uses total admissions as the denominator."""
    with db.read() as conn:
        admissions = conn.execute(
            "SELECT COUNT(*) FROM patients WHERE status != 'Awaiting Admission'").fetchone()[0]
        recoveries = conn.execute(
            "SELECT COUNT(*) FROM patient_outcomes WHERE outcome = 'Recovered'").fetchone()[0]
        deaths = conn.execute(
            "SELECT COUNT(*) FROM patient_outcomes WHERE outcome = 'Deceased'").fetchone()[0]
        current = conn.execute(
            "SELECT COUNT(*) FROM patients WHERE status IN ('Admitted', 'Discharge Approved')").fetchone()[0]
        admitted_by_day = conn.execute(
            "SELECT admission_date AS day, COUNT(*) AS n FROM patients "
            "WHERE status != 'Awaiting Admission' GROUP BY admission_date").fetchall()
        outcomes_by_day = conn.execute(
            "SELECT substr(outcome_at, 1, 10) AS day, outcome, COUNT(*) AS n FROM patient_outcomes "
            "GROUP BY day, outcome").fetchall()
    mortality = deaths / admissions * 100 if admissions else 0.0
    recovery = recoveries / admissions * 100 if admissions else 0.0
    resolved = recoveries + deaths
    return {
        "admissions": admissions, "recoveries": recoveries, "deaths": deaths, "current": current,
        "mortality_rate": mortality, "recovery_rate": recovery,
        "resolved": resolved,
        "resolved_mortality": deaths / resolved * 100 if resolved else 0.0,
        "mortality_alert": mortality > MORTALITY_BENCHMARK,
        "admitted_by_day": {r["day"]: r["n"] for r in admitted_by_day},
        "recovered_by_day": {r["day"]: r["n"] for r in outcomes_by_day if r["outcome"] == "Recovered"},
        "deaths_by_day": {r["day"]: r["n"] for r in outcomes_by_day if r["outcome"] == "Deceased"},
    }


def room_counts():
    rooms = list_rooms()
    return {
        "capacity": len(rooms),
        "occupied": sum(r["status"] == "Occupied" for r in rooms),
        "available": sum(r["status"] == "Available" for r in rooms),
        "cleaning": sum(r["status"] == "Pending Cleaning" for r in rooms),
    }


def recent_audit(limit=200):
    with db.read() as conn:
        rows = conn.execute("SELECT * FROM audit_logs ORDER BY log_id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def user_directory():
    with db.read() as conn:
        return {r["username"]: r["full_name"] for r in conn.execute("SELECT username, full_name FROM users")}


# -------------------------------------------------------------- nurse actions
def record_temperature(patient_id, temperature_c, actor):
    """Record today's routine temperature. Exactly one per patient per calendar day."""
    temp = _valid_temp(temperature_c)
    ts, threshold = now(), fever_threshold()
    on_date = ts.date().isoformat()
    with db.transaction() as conn:
        user = _actor(conn, actor, ("Nurse",), "Only nursing staff can record routine temperatures.")
        patient = _inpatient(conn, patient_id)
        existing = conn.execute(
            "SELECT temperature_c, recorded_at FROM temperature_records "
            "WHERE patient_id = ? AND record_date = ? AND is_active = 1", (patient_id, on_date)).fetchone()
        if existing:
            raise WorkflowError(
                f"Duplicate prevented: {patient['full_name']} already has a temperature for today "
                f"({existing['temperature_c']:.1f} °C at {existing['recorded_at'][11:16]}). "
                "Use the correction option if that value is wrong.")
        is_fever = temp >= threshold
        cur = conn.execute(
            "INSERT INTO temperature_records (patient_id, record_date, recorded_at, temperature_c, is_fever, "
            "threshold_c, record_type, recorded_by) VALUES (?, ?, ?, ?, ?, ?, 'Routine', ?)",
            (patient_id, on_date, ts.strftime(TS_FMT), temp, int(is_fever), threshold, actor))
        _audit(conn, ts, user, "TEMPERATURE_RECORDED", "Patient", patient_id,
               f"{temp:.1f} °C ({'fever' if is_fever else 'normal'}, threshold {threshold:.1f}); room {patient['room_number']}")
    return {"record_id": cur.lastrowid, "temperature_c": temp, "is_fever": is_fever,
            "recorded_at": ts, "patient_name": patient["full_name"]}


def correct_temperature(record_id, new_temperature_c, reason, actor):
    """Correct today's reading. The original is kept (inactive) and linked for audit."""
    temp = _valid_temp(new_temperature_c)
    reason = (reason or "").strip()
    if len(reason) < 5:
        raise WorkflowError("A reason of at least 5 characters is required for a correction.")
    ts, threshold = now(), fever_threshold()
    with db.transaction() as conn:
        user = _actor(conn, actor, ("Nurse", "Doctor"), "Only clinical staff can correct a temperature reading.")
        original = conn.execute("SELECT * FROM temperature_records WHERE record_id = ?", (record_id,)).fetchone()
        if not original or not original["is_active"]:
            raise WorkflowError("That reading has already been superseded. Refresh and try again.")
        if original["record_date"] != ts.date().isoformat():
            raise WorkflowError("Only today's reading can be corrected.")
        patient = _inpatient(conn, original["patient_id"])
        if abs(original["temperature_c"] - temp) < 0.05:
            raise WorkflowError("The corrected value is the same as the original reading.")
        is_fever = temp >= threshold
        conn.execute("UPDATE temperature_records SET is_active = 0 WHERE record_id = ?", (record_id,))
        cur = conn.execute(
            "INSERT INTO temperature_records (patient_id, record_date, recorded_at, temperature_c, is_fever, "
            "threshold_c, record_type, supersedes_id, correction_reason, recorded_by) "
            "VALUES (?, ?, ?, ?, ?, ?, 'Correction', ?, ?, ?)",
            (original["patient_id"], original["record_date"], ts.strftime(TS_FMT), temp, int(is_fever),
             threshold, record_id, reason, actor))
        # A visit recorded today keeps pointing at the effective reading.
        conn.execute("UPDATE doctor_visits SET temperature_record_id = ? WHERE temperature_record_id = ?",
                     (cur.lastrowid, record_id))
        _audit(conn, ts, user, "TEMPERATURE_CORRECTED", "Patient", original["patient_id"],
               f"{original['temperature_c']:.1f} °C -> {temp:.1f} °C; reason: {reason}; "
               f"original record #{record_id} retained")
    return {"record_id": cur.lastrowid, "temperature_c": temp, "is_fever": is_fever,
            "patient_name": patient["full_name"]}


# ------------------------------------------------------------- doctor actions
def complete_visit(patient_id, actor, observations, symptoms, assessment, treatment,
                   medication, dosage, nursing_instructions):
    """Complete today's doctor visit. Blocked until today's temperature exists."""
    observations, assessment = (observations or "").strip(), (assessment or "").strip()
    treatment, medication, dosage = (treatment or "").strip(), (medication or "").strip(), (dosage or "").strip()
    if len(observations) < 3:
        raise WorkflowError("Medical observations are required to complete the visit.")
    if len(assessment) < 3:
        raise WorkflowError("A diagnosis or assessment is required to complete the visit.")
    if medication and not dosage:
        raise WorkflowError("Enter a dosage for the medication prescribed.")
    ts = now()
    on_date = ts.date().isoformat()
    with db.transaction() as conn:
        user = _actor(conn, actor, ("Doctor",), "Only doctors can complete a doctor visit.")
        patient = _inpatient(conn, patient_id)
        temp = conn.execute(
            "SELECT record_id FROM temperature_records WHERE patient_id = ? AND record_date = ? AND is_active = 1",
            (patient_id, on_date)).fetchone()
        if not temp:
            raise WorkflowError(
                f"Awaiting Nurse: today's temperature has not been recorded for {patient['full_name']}. "
                "The visit cannot be completed until it is.")
        if conn.execute("SELECT 1 FROM doctor_visits WHERE patient_id = ? AND visit_date = ?",
                        (patient_id, on_date)).fetchone():
            raise WorkflowError(f"Today's doctor visit for {patient['full_name']} is already completed.")
        cur = conn.execute(
            "INSERT INTO doctor_visits (patient_id, visit_date, visited_at, doctor, temperature_record_id, "
            "observations, symptoms, assessment, nursing_instructions) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (patient_id, on_date, ts.strftime(TS_FMT), actor, temp["record_id"], observations,
             (symptoms or "").strip(), assessment, (nursing_instructions or "").strip()))
        if treatment or medication:
            conn.execute(
                "INSERT INTO treatment_records (visit_id, patient_id, treatment, medication, dosage, "
                "prescribed_at, prescribed_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (cur.lastrowid, patient_id, treatment or "Medication only", medication, dosage,
                 ts.strftime(TS_FMT), actor))
        _audit(conn, ts, user, "DOCTOR_VISIT_COMPLETED", "Patient", patient_id,
               f"Visit #{cur.lastrowid}; room {patient['room_number']}")
    return {"visit_id": cur.lastrowid, "visited_at": ts, "patient_name": patient["full_name"]}


def approve_discharge(patient_id, actor):
    """Medical discharge approval. Requires three complete consecutive fever-free days."""
    ts = now()
    with db.transaction() as conn:
        user = _actor(conn, actor, ("Doctor",), "Only doctors can approve a medical discharge.")
        patient = _inpatient(conn, patient_id)
        if patient["status"] != "Admitted":
            raise WorkflowError(f"Discharge has already been approved for {patient['full_name']}.")
        streak, dates = fever_free_streak(_day_map(conn, patient_id), ts.date(),
                                          date.fromisoformat(patient["admission_date"]))
        if streak < REQUIRED_FEVER_FREE_DAYS:
            raise WorkflowError(
                f"Not eligible: {patient['full_name']} has {streak} of {REQUIRED_FEVER_FREE_DAYS} "
                "complete consecutive fever-free days.")
        qualifying = [d.isoformat() for d in dates[-REQUIRED_FEVER_FREE_DAYS:]]
        conn.execute(
            "INSERT INTO discharge_approvals (patient_id, approved_by, approved_at, fever_free_streak, "
            "qualifying_dates) VALUES (?, ?, ?, ?, ?)",
            (patient_id, actor, ts.strftime(TS_FMT), streak, json.dumps(qualifying)))
        conn.execute("UPDATE patients SET status = 'Discharge Approved' WHERE patient_id = ?", (patient_id,))
        _audit(conn, ts, user, "DISCHARGE_APPROVED", "Patient", patient_id,
               f"Fever-free streak {streak}; qualifying days {', '.join(qualifying)}")
    return {"patient_name": patient["full_name"], "streak": streak, "qualifying_dates": qualifying}


def record_death(patient_id, notes, actor, confirmed=False):
    """Record a patient death (exactly once) and start room turnover."""
    notes = (notes or "").strip()
    if not confirmed:
        raise WorkflowError("Tick the confirmation box before recording a patient death.")
    if len(notes) < 5:
        raise WorkflowError("Medical notes are required when recording a patient death.")
    ts = now()
    with db.transaction() as conn:
        user = _actor(conn, actor, ("Doctor",), "Only doctors can record a patient death.")
        patient = _inpatient(conn, patient_id)
        if conn.execute("SELECT 1 FROM patient_outcomes WHERE patient_id = ?", (patient_id,)).fetchone():
            raise WorkflowError("An outcome has already been recorded for this patient.")
        conn.execute(
            "INSERT INTO patient_outcomes (patient_id, outcome, outcome_at, recorded_by, notes) "
            "VALUES (?, 'Deceased', ?, ?, ?)", (patient_id, ts.strftime(TS_FMT), actor, notes))
        conn.execute("UPDATE patients SET status = 'Deceased' WHERE patient_id = ?", (patient_id,))
        conn.execute(
            "UPDATE rooms SET status = 'Pending Cleaning', current_patient_id = NULL, updated_at = ? "
            "WHERE current_patient_id = ?", (ts.strftime(TS_FMT), patient_id))
        _audit(conn, ts, user, "PATIENT_DEATH_RECORDED", "Patient", patient_id,
               f"Room {patient['room_number']} moved to Pending Cleaning")
    return {"patient_name": patient["full_name"], "room_number": patient["room_number"], "outcome_at": ts}


def set_fever_threshold(value, actor):
    try:
        value = round(float(value), 1)
    except (TypeError, ValueError):
        raise WorkflowError("Enter the threshold as a number in °C.")
    if not 37.0 <= value <= 39.0:
        raise WorkflowError("The fever threshold must be between 37.0 °C and 39.0 °C.")
    ts = now()
    with db.transaction() as conn:
        user = _actor(conn, actor, ("Doctor",), "Only the Head Doctor can change the fever threshold.")
        old = conn.execute("SELECT value FROM settings WHERE key = 'fever_threshold'").fetchone()
        conn.execute("INSERT INTO settings (key, value) VALUES ('fever_threshold', ?) "
                     "ON CONFLICT (key) DO UPDATE SET value = excluded.value", (str(value),))
        _audit(conn, ts, user, "FEVER_THRESHOLD_CHANGED", "Setting", "fever_threshold",
               f"{old['value'] if old else '-'} -> {value}")
    return value


# -------------------------------------------------------------- admin actions
def _validate_registration(full_name, age, gender, contact, symptoms):
    full_name = re.sub(r"\s+", " ", (full_name or "").strip())
    contact, symptoms = (contact or "").strip(), (symptoms or "").strip()
    if len(full_name) < 3 or not re.fullmatch(r"[A-Za-z][A-Za-z .'\-]+", full_name):
        raise WorkflowError("Enter the patient's full name (letters only, at least 3 characters).")
    try:
        age = int(age)
    except (TypeError, ValueError):
        raise WorkflowError("Enter a valid age.")
    if not 0 <= age <= 120:
        raise WorkflowError("Age must be between 0 and 120.")
    if gender not in ("Female", "Male", "Other"):
        raise WorkflowError("Select a gender.")
    if not ("@" in contact or len(re.sub(r"\D", "", contact)) >= 7):
        raise WorkflowError("Enter a contact phone number (at least 7 digits) or an email address.")
    if len(symptoms) < 3:
        raise WorkflowError("Describe the presenting symptoms.")
    return full_name, age, gender, contact, symptoms


def _assign_room(conn, ts, patient_id, room_id, admission_date, initial_temp, threshold, actor):
    room = conn.execute("SELECT * FROM rooms WHERE room_id = ?", (room_id,)).fetchone()
    if not room:
        raise WorkflowError("Select a room.")
    if room["status"] != "Available":
        raise WorkflowError(f"Room {room['room_number']} is {room['status'].lower()} and cannot be assigned.")
    conn.execute("UPDATE rooms SET status = 'Occupied', current_patient_id = ?, updated_at = ? WHERE room_id = ?",
                 (patient_id, ts.strftime(TS_FMT), room_id))
    conn.execute("UPDATE patients SET status = 'Admitted', room_id = ?, admission_date = ? WHERE patient_id = ?",
                 (room_id, admission_date.isoformat(), patient_id))
    conn.execute(
        "INSERT INTO temperature_records (patient_id, record_date, recorded_at, temperature_c, is_fever, "
        "threshold_c, record_type, recorded_by) VALUES (?, ?, ?, ?, ?, ?, 'Admission', ?)",
        (patient_id, admission_date.isoformat(), ts.strftime(TS_FMT), initial_temp,
         int(initial_temp >= threshold), threshold, actor))
    return room["room_number"]


def register_patient(actor, full_name, age, gender, contact, symptoms, room_id=None,
                     admission_date=None, initial_temp=None):
    """Register a patient. With a room: admit immediately. Without: add to the admission queue."""
    full_name, age, gender, contact, symptoms = _validate_registration(full_name, age, gender, contact, symptoms)
    ts, threshold = now(), fever_threshold()
    if room_id is not None:
        initial_temp = _valid_temp(initial_temp)
        admission_date = admission_date or ts.date()
        if admission_date > ts.date():
            raise WorkflowError("The admission date cannot be in the future.")
        if admission_date < ts.date() - timedelta(days=3):
            raise WorkflowError("The admission date cannot be more than 3 days in the past.")
    with db.transaction() as conn:
        user = _actor(conn, actor, ("Admin",), "Only administrative staff can register patients.")
        patient_id = _next_patient_id(conn)
        conn.execute(
            "INSERT INTO patients (patient_id, full_name, age, gender, contact, symptoms, status, "
            "registered_at, registered_by) VALUES (?, ?, ?, ?, ?, ?, 'Awaiting Admission', ?, ?)",
            (patient_id, full_name, age, gender, contact, symptoms, ts.strftime(TS_FMT), actor))
        if room_id is None:
            _audit(conn, ts, user, "PATIENT_QUEUED", "Patient", patient_id, "Added to admission queue")
            return {"patient_id": patient_id, "full_name": full_name, "room_number": None}
        room_number = _assign_room(conn, ts, patient_id, room_id, admission_date, initial_temp, threshold, actor)
        _audit(conn, ts, user, "PATIENT_ADMITTED", "Patient", patient_id,
               f"Room {room_number}; initial temperature {initial_temp:.1f} °C")
    return {"patient_id": patient_id, "full_name": full_name, "room_number": room_number}


def admit_from_queue(patient_id, room_id, initial_temp, actor):
    initial_temp = _valid_temp(initial_temp)
    ts, threshold = now(), fever_threshold()
    with db.transaction() as conn:
        user = _actor(conn, actor, ("Admin",), "Only administrative staff can admit patients.")
        patient = conn.execute("SELECT * FROM patients WHERE patient_id = ?", (patient_id,)).fetchone()
        if not patient or patient["status"] != "Awaiting Admission":
            raise WorkflowError("This patient is not in the admission queue.")
        room_number = _assign_room(conn, ts, patient_id, room_id, ts.date(), initial_temp, threshold, actor)
        _audit(conn, ts, user, "PATIENT_ADMITTED", "Patient", patient_id,
               f"From admission queue; room {room_number}; initial temperature {initial_temp:.1f} °C")
    return {"patient_id": patient_id, "full_name": patient["full_name"], "room_number": room_number}


def complete_checkout(patient_id, actor):
    """Physical checkout by admin. Records the Recovered outcome and sends the room for cleaning."""
    ts = now()
    with db.transaction() as conn:
        user = _actor(conn, actor, ("Admin",), "Only administrative staff can complete a patient checkout.")
        patient = _inpatient(conn, patient_id)
        if patient["status"] != "Discharge Approved":
            raise WorkflowError(f"A doctor has not approved discharge for {patient['full_name']}.")
        if conn.execute("SELECT 1 FROM patient_outcomes WHERE patient_id = ?", (patient_id,)).fetchone():
            raise WorkflowError("An outcome has already been recorded for this patient.")
        conn.execute("UPDATE discharge_approvals SET checkout_at = ?, checkout_by = ? WHERE patient_id = ?",
                     (ts.strftime(TS_FMT), actor, patient_id))
        conn.execute(
            "INSERT INTO patient_outcomes (patient_id, outcome, outcome_at, recorded_by, notes) "
            "VALUES (?, 'Recovered', ?, ?, 'Discharged after doctor approval')",
            (patient_id, ts.strftime(TS_FMT), actor))
        conn.execute("UPDATE patients SET status = 'Discharged' WHERE patient_id = ?", (patient_id,))
        conn.execute(
            "UPDATE rooms SET status = 'Pending Cleaning', current_patient_id = NULL, updated_at = ? "
            "WHERE current_patient_id = ?", (ts.strftime(TS_FMT), patient_id))
        _audit(conn, ts, user, "CHECKOUT_COMPLETED", "Patient", patient_id,
               f"Recovered/Discharged; room {patient['room_number']} moved to Pending Cleaning")
    return {"patient_name": patient["full_name"], "room_number": patient["room_number"], "checkout_at": ts}


def mark_room_cleaned(room_id, actor):
    ts = now()
    with db.transaction() as conn:
        user = _actor(conn, actor, ("Admin",), "Only administrative staff can update room status.")
        room = conn.execute("SELECT * FROM rooms WHERE room_id = ?", (room_id,)).fetchone()
        if not room or room["status"] != "Pending Cleaning":
            raise WorkflowError("This room is not pending cleaning.")
        conn.execute("UPDATE rooms SET status = 'Available', updated_at = ? WHERE room_id = ?",
                     (ts.strftime(TS_FMT), room_id))
        _audit(conn, ts, user, "ROOM_CLEANED", "Room", room["room_number"], "Pending Cleaning -> Available")
    return room["room_number"]


def advance_demo_day(actor):
    """Demonstration aid: move the application clock forward one calendar day."""
    ts = now()
    with db.transaction() as conn:
        user = _actor(conn, actor, ("Admin",), "Only administrative staff can change the demo clock.")
        row = conn.execute("SELECT value FROM settings WHERE key = 'demo_day_offset'").fetchone()
        offset = int(row["value"]) + 1 if row else 1
        conn.execute("INSERT INTO settings (key, value) VALUES ('demo_day_offset', ?) "
                     "ON CONFLICT (key) DO UPDATE SET value = excluded.value", (str(offset),))
        _audit(conn, ts, user, "DEMO_CLOCK_ADVANCED", "Setting", "demo_day_offset", f"Offset now +{offset} day(s)")
    return offset


def reset_demo(actor):
    with db.read() as conn:
        _actor(conn, actor, ("Admin",), "Only administrative staff can reset the demo data.")
    db.drop_all()
    bootstrap()


def bootstrap():
    """Create the schema and load the sample dataset on first launch."""
    import seed
    db.create_schema()
    with db.read() as conn:
        has_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0
    if not has_users:
        ts = datetime.now(APP_TZ).replace(tzinfo=None, microsecond=0)
        with db.transaction() as conn:
            if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
                seed.seed_all(conn, ts)
