"""Sample dataset for VITALIS, generated relative to today's date on first launch."""

import json
import random
from datetime import datetime, time, timedelta

import services as svc

FIRST = ["Aarav", "Ananya", "Vikram", "Meera", "Rohan", "Kavya", "Arjun", "Sneha", "Imran", "Fatima",
         "Daniel", "Grace", "Karan", "Pooja", "Nikhil", "Divya", "Suresh", "Lakshmi", "Farhan", "Zoya",
         "Joseph", "Maria", "Harish", "Neha", "Tenzin", "Ritu", "Manoj", "Asha", "Kabir", "Isha"]
LAST = ["Sharma", "Iyer", "Patel", "Nair", "Khan", "Reddy", "D'Souza", "Banerjee", "Singh", "Menon",
        "Joshi", "Fernandes", "Kulkarni", "Gupta", "Das", "Pillai", "Chopra", "Shaikh", "Rao", "Verma"]
SYMPTOMS = ["Prolonged fever, fatigue", "High fever, body ache", "Fever with dry cough", "Fever, headache, chills",
            "Persistent fever, loss of appetite", "Fever, sore throat", "Fever, muscle pain, weakness"]

USERS = [
    ("nurse", "nurse123", "Nurse", "Anita Deshmukh", "Charge Nurse"),
    ("doctor", "doctor123", "Doctor", "Dr. Rohan Mehta", "Head Doctor"),
    ("admin", "admin123", "Admin", "Priya Nair", "Administration Officer"),
]

# (history for the days before today: F fever, N normal, M missed; today's state; today's reading)
CURRENT = (
    [(p, "none", None) for p in ("FFF", "FFFF", "FF", "FFFFF", "NFF", "FFFFFF")]
    + [("FFF", "temp", "fever"), ("FF", "temp", "critical"), ("FFFF", "temp", "fever"),
       ("FFFFF", "temp", "critical"), ("F", "temp", "fever")]
    + [(p, "visit", "fever") for p in ("FFF", "FF", "FFFF", "NNF")]
    + [(p, "none", None) for p in ("FN", "FFFN", "FFN")]
    + [("FFN", "temp", "normal"), ("FN", "temp", "normal"), ("FFN", "visit", "normal"), ("FFFN", "visit", "normal")]
    + [(p, "none", None) for p in ("FNN", "FFNN", "FFFNN")]
    + [(p, "temp", "normal") for p in ("FNN", "FFNN", "FNN")]
    + [(p, "visit", "normal") for p in ("FFNN", "FNN")]
    + [(p, "none", None) for p in ("FNNN", "FFNNN")]
    + [(p, "temp", "normal") for p in ("FNNN", "FFNNN", "FNNNN")]
    + [(p, "visit", "normal") for p in ("FFNNN", "FNNN")]
    + [(p, "approved", "normal") for p in ("FNNN", "FFNNN", "FNNNN")]
    + [("FNMN", "none", None), ("FFNMN", "temp", "normal")]
    + [("", "admit", "fever"), ("", "admit", "fever")]
)


def seed_all(conn, now_ts, threshold=svc.DEFAULT_FEVER_THRESHOLD):
    rng = random.Random(2026)
    today = now_ts.date()
    fmt = svc.TS_FMT
    seq = [0]

    def ts(day, start_hour, end_hour):
        """Random time on a day; for today, never later than the current time."""
        if day == today:
            seconds = max(60, int((now_ts - datetime.combine(today, time.min)).total_seconds()))
            return (datetime.combine(today, time.min) + timedelta(seconds=rng.randint(30, seconds))).strftime(fmt)
        minute = rng.randint(start_hour * 60, end_hour * 60)
        return (datetime.combine(day, time.min) + timedelta(minutes=minute)).strftime(fmt)

    def temp_value(kind):
        low, high = {"fever": (38.2, 39.3), "critical": (39.6, 40.4), "normal": (36.4, 37.4)}[kind]
        return round(rng.uniform(low, high), 1)

    names = rng.sample([f"{f} {l}" for f in FIRST for l in LAST], 80)

    def new_patient(status, admission, room_id, registered_at):
        seq[0] += 1
        pid = f"VT-{seq[0]:05d}"
        conn.execute(
            "INSERT INTO patients (patient_id, full_name, age, gender, contact, symptoms, admission_date, room_id, "
            "status, registered_at, registered_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'admin')",
            (pid, names[seq[0]], rng.randint(19, 78), rng.choice(["Female", "Male"]),
             f"+91 9{rng.randint(100000000, 999999999)}", rng.choice(SYMPTOMS),
             admission.isoformat() if admission else None, room_id, status, registered_at))
        return pid

    def add_temp(pid, day, kind, record_type="Routine", by="nurse", at=None):
        value = temp_value(kind)
        cur = conn.execute(
            "INSERT INTO temperature_records (patient_id, record_date, recorded_at, temperature_c, is_fever, "
            "threshold_c, record_type, recorded_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (pid, day.isoformat(), at or ts(day, 6, 10), value, int(value >= threshold), threshold, record_type, by))
        return cur.lastrowid, value

    def add_visit(pid, day, record_id, fever):
        at = ts(day, 11, 16)
        if fever:
            notes = ("Febrile, hydrated, alert.", "Fever, fatigue", "Active infection, fever persisting.",
                     "Antipyretic therapy and oral fluids", "Paracetamol", "650 mg every 6 hours",
                     "Monitor fluid intake; tepid sponging if temperature rises.")
        else:
            notes = ("Afebrile, comfortable, eating well.", "Mild fatigue", "Recovering, fever resolved.",
                     "Supportive care, continue observation", "", "", "Continue daily temperature check.")
        cur = conn.execute(
            "INSERT INTO doctor_visits (patient_id, visit_date, visited_at, doctor, temperature_record_id, "
            "observations, symptoms, assessment, nursing_instructions) VALUES (?, ?, ?, 'doctor', ?, ?, ?, ?, ?)",
            (pid, day.isoformat(), at, record_id, notes[0], notes[1], notes[2], notes[6]))
        conn.execute(
            "INSERT INTO treatment_records (visit_id, patient_id, treatment, medication, dosage, prescribed_at, "
            "prescribed_by) VALUES (?, ?, ?, ?, ?, ?, 'doctor')", (cur.lastrowid, pid, notes[3], notes[4], notes[5], at))
        return at

    stamp = now_ts.strftime(fmt)
    for key, value in (("fever_threshold", str(threshold)), ("demo_day_offset", "0")):
        conn.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, value))
    for username, password, role, name, title in USERS:
        conn.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?, ?)",
                     (username, svc.hash_password(password), role, name, title, stamp))

    room_no = 0
    for floor, count in ((1, 25), (2, 25), (3, 24)):
        for n in range(1, count + 1):
            room_no += 1
            conn.execute("INSERT INTO rooms (room_id, room_number, floor, status, updated_at) "
                         "VALUES (?, ?, ?, 'Available', ?)", (room_no, f"{floor}{n:02d}", floor, stamp))
    room_ids = list(range(1, svc.CAPACITY + 1))
    rng.shuffle(room_ids)

    # ---- completed historical admissions: 13 recovered, 9 deceased
    for i in range(22):
        admission = today - timedelta(days=rng.randint(11, 28))
        pid = new_patient("Discharged" if i < 13 else "Deceased", admission, rng.choice(room_ids),
                          ts(admission, 9, 18))
        day = admission
        add_temp(pid, day, "fever", "Admission", "admin")
        for _ in range(rng.randint(2, 5)):
            day += timedelta(days=1)
            rid, _ = add_temp(pid, day, "fever")
            add_visit(pid, day, rid, True)
        if i < 13:
            dates = []
            for _ in range(3):
                day += timedelta(days=1)
                rid, _ = add_temp(pid, day, "normal")
                add_visit(pid, day, rid, False)
                dates.append(day.isoformat())
            day += timedelta(days=1)
            rid, _ = add_temp(pid, day, "normal")
            visited = add_visit(pid, day, rid, False)
            checkout = (datetime.strptime(visited, fmt) + timedelta(minutes=rng.randint(40, 150))).strftime(fmt)
            conn.execute(
                "INSERT INTO discharge_approvals (patient_id, approved_by, approved_at, fever_free_streak, "
                "qualifying_dates, checkout_at, checkout_by) VALUES (?, 'doctor', ?, 3, ?, ?, 'admin')",
                (pid, visited, json.dumps(dates), checkout))
            conn.execute("INSERT INTO patient_outcomes (patient_id, outcome, outcome_at, recorded_by, notes) "
                         "VALUES (?, 'Recovered', ?, 'admin', 'Discharged after doctor approval')", (pid, checkout))
        else:
            conn.execute("INSERT INTO patient_outcomes (patient_id, outcome, outcome_at, recorded_by, notes) "
                         "VALUES (?, 'Deceased', ?, 'doctor', 'Deterioration despite treatment; multi-organ involvement.')",
                         (pid, ts(day, 18, 23)))

    # ---- patients currently in the facility
    specs = list(CURRENT)
    rng.shuffle(specs)
    for (history, state, kind), room_id in zip(specs, room_ids):
        admission = today if state == "admit" else today - timedelta(days=len(history) + 1)
        registered = ts(admission, 9, 18)
        pid = new_patient("Discharge Approved" if state == "approved" else "Admitted", admission, room_id, registered)
        conn.execute("UPDATE rooms SET status = 'Occupied', current_patient_id = ? WHERE room_id = ?", (pid, room_id))
        add_temp(pid, admission, "fever", "Admission", "admin", registered)
        for offset, mark in enumerate(history, start=1):
            if mark == "M":
                continue
            day = admission + timedelta(days=offset)
            rid, _ = add_temp(pid, day, "fever" if mark == "F" else "normal")
            add_visit(pid, day, rid, mark == "F")
        if state in ("temp", "visit", "approved"):
            rid, _ = add_temp(pid, today, kind)
            if state in ("visit", "approved"):
                visited = add_visit(pid, today, rid, kind != "normal")
            if state == "approved":
                dates = [(today - timedelta(days=d)).isoformat() for d in (3, 2, 1)]
                streak = len(history) - history.rfind("F") - 1
                conn.execute(
                    "INSERT INTO discharge_approvals (patient_id, approved_by, approved_at, fever_free_streak, "
                    "qualifying_dates) VALUES (?, 'doctor', ?, ?, ?)", (pid, visited, streak, json.dumps(dates)))

    for room_id in room_ids[len(specs):len(specs) + 3]:
        conn.execute("UPDATE rooms SET status = 'Pending Cleaning' WHERE room_id = ?", (room_id,))

    # ---- registered, waiting for a room to be assigned
    for _ in range(3):
        new_patient("Awaiting Admission", None, None, ts(today, 7, 12))

    conn.execute("INSERT INTO settings (key, value) VALUES ('patient_seq', ?)", (str(seq[0]),))
    conn.execute(
        "INSERT INTO audit_logs (logged_at, actor, role, action, entity_type, entity_id, details) "
        "VALUES (?, 'system', 'System', 'DEMO_DATA_LOADED', 'System', NULL, 'Sample dataset initialised')", (stamp,))
