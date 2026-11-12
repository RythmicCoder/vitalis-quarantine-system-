"""SQLite access layer for VITALIS: connection handling, transactions and schema."""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    username      TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('Nurse', 'Doctor', 'Admin')),
    full_name     TEXT NOT NULL,
    title         TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rooms (
    room_id            INTEGER PRIMARY KEY,
    room_number        TEXT NOT NULL UNIQUE,
    floor              INTEGER NOT NULL,
    status             TEXT NOT NULL DEFAULT 'Available'
                       CHECK (status IN ('Available', 'Occupied', 'Pending Cleaning')),
    current_patient_id TEXT REFERENCES patients (patient_id),
    updated_at         TEXT NOT NULL,
    CHECK ((status = 'Occupied') = (current_patient_id IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS patients (
    patient_id     TEXT PRIMARY KEY,
    full_name      TEXT NOT NULL,
    age            INTEGER NOT NULL CHECK (age BETWEEN 0 AND 120),
    gender         TEXT NOT NULL,
    contact        TEXT NOT NULL,
    symptoms       TEXT NOT NULL,
    admission_date TEXT,
    room_id        INTEGER REFERENCES rooms (room_id),
    status         TEXT NOT NULL
                   CHECK (status IN ('Awaiting Admission', 'Admitted', 'Discharge Approved',
                                     'Discharged', 'Deceased')),
    registered_at  TEXT NOT NULL,
    registered_by  TEXT NOT NULL REFERENCES users (username)
);

CREATE TABLE IF NOT EXISTS temperature_records (
    record_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id        TEXT NOT NULL REFERENCES patients (patient_id),
    record_date       TEXT NOT NULL,
    recorded_at       TEXT NOT NULL,
    temperature_c     REAL NOT NULL CHECK (temperature_c BETWEEN 30 AND 45),
    is_fever          INTEGER NOT NULL CHECK (is_fever IN (0, 1)),
    threshold_c       REAL NOT NULL,
    record_type       TEXT NOT NULL CHECK (record_type IN ('Routine', 'Admission', 'Correction')),
    is_active         INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    supersedes_id     INTEGER REFERENCES temperature_records (record_id),
    correction_reason TEXT,
    recorded_by       TEXT NOT NULL REFERENCES users (username)
);
-- One effective reading per patient per calendar day. Corrections retire the
-- original (is_active = 0) instead of overwriting it.
CREATE UNIQUE INDEX IF NOT EXISTS ux_temperature_one_per_day
    ON temperature_records (patient_id, record_date) WHERE is_active = 1;
CREATE INDEX IF NOT EXISTS ix_temperature_patient ON temperature_records (patient_id, record_date);

CREATE TABLE IF NOT EXISTS doctor_visits (
    visit_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id            TEXT NOT NULL REFERENCES patients (patient_id),
    visit_date            TEXT NOT NULL,
    visited_at            TEXT NOT NULL,
    doctor                TEXT NOT NULL REFERENCES users (username),
    temperature_record_id INTEGER NOT NULL REFERENCES temperature_records (record_id),
    observations          TEXT NOT NULL,
    symptoms              TEXT,
    assessment            TEXT NOT NULL,
    nursing_instructions  TEXT,
    UNIQUE (patient_id, visit_date)
);

CREATE TABLE IF NOT EXISTS treatment_records (
    treatment_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    visit_id      INTEGER NOT NULL REFERENCES doctor_visits (visit_id),
    patient_id    TEXT NOT NULL REFERENCES patients (patient_id),
    treatment     TEXT NOT NULL,
    medication    TEXT,
    dosage        TEXT,
    prescribed_at TEXT NOT NULL,
    prescribed_by TEXT NOT NULL REFERENCES users (username)
);

CREATE TABLE IF NOT EXISTS discharge_approvals (
    approval_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id        TEXT NOT NULL UNIQUE REFERENCES patients (patient_id),
    approved_by       TEXT NOT NULL REFERENCES users (username),
    approved_at       TEXT NOT NULL,
    fever_free_streak INTEGER NOT NULL,
    qualifying_dates  TEXT NOT NULL,
    checkout_at       TEXT,
    checkout_by       TEXT REFERENCES users (username)
);

-- UNIQUE (patient_id) guarantees an outcome is recorded exactly once.
CREATE TABLE IF NOT EXISTS patient_outcomes (
    outcome_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id  TEXT NOT NULL UNIQUE REFERENCES patients (patient_id),
    outcome     TEXT NOT NULL CHECK (outcome IN ('Recovered', 'Deceased')),
    outcome_at  TEXT NOT NULL,
    recorded_by TEXT NOT NULL REFERENCES users (username),
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS audit_logs (
    log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    logged_at   TEXT NOT NULL,
    actor       TEXT NOT NULL,
    role        TEXT NOT NULL,
    action      TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id   TEXT,
    details     TEXT
);
"""

TABLES = [
    "audit_logs", "patient_outcomes", "discharge_approvals", "treatment_records",
    "doctor_visits", "temperature_records", "rooms", "patients", "users", "settings",
]


def db_path() -> Path:
    """Database file location, relative to the project (override with VITALIS_DB_PATH)."""
    override = os.environ.get("VITALIS_DB_PATH")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent / "data" / "vitalis.db"


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def read():
    """Read-only style connection (no explicit transaction)."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction():
    """All-or-nothing write transaction. Rolls back on any exception."""
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def create_schema() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
    finally:
        conn.close()


def drop_all() -> None:
    conn = connect()
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        for table in TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
    finally:
        conn.close()
