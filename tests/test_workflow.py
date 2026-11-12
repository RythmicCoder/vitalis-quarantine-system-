"""End-to-end workflow checks for VITALIS (the 13 acceptance scenarios).

Run with:  python tests/test_workflow.py     (or: pytest tests)
Uses a temporary database, so the real application data is never touched.
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["VITALIS_DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="vitalis_test_"), "test.db")

import db  # noqa: E402
import services as svc  # noqa: E402


def by_id():
    return {p["patient_id"]: p for p in svc.list_inpatients()}


def pick(**conditions):
    for p in svc.list_inpatients():
        if all(p[k] == v for k, v in conditions.items()):
            return p
    raise AssertionError(f"No sample patient matches {conditions}")


def expect_error(fragment, func, *args, **kwargs):
    try:
        func(*args, **kwargs)
    except svc.WorkflowError as exc:
        assert fragment.lower() in str(exc).lower(), f"Unexpected message: {exc}"
        return
    raise AssertionError(f"Expected a WorkflowError containing '{fragment}'")


VISIT = dict(observations="Alert and stable.", symptoms="Fatigue", assessment="Recovering.",
             treatment="Supportive care", medication="Paracetamol", dosage="500 mg as needed",
             nursing_instructions="Continue daily checks.")


def test_full_workflow():
    svc.bootstrap()
    stats0 = svc.facility_stats()
    rooms0 = svc.room_counts()
    assert rooms0["capacity"] == 74
    assert stats0["admissions"] == stats0["current"] + stats0["recoveries"] + stats0["deaths"]
    assert rooms0["occupied"] == stats0["current"]
    assert not stats0["mortality_alert"]
    streaks = {p["streak"] for p in svc.list_inpatients()}
    assert {0, 1, 2, 3} <= streaks, "Seed must include 0, 1, 2 and 3 fever-free days"
    print("SEED     sample data consistent:", stats0["admissions"], "admissions,", rooms0["occupied"], "occupied")

    # TEST 1 - normal temperature -> Ready for Doctor
    p1 = pick(workflow=svc.NEEDS_TEMP, streak=2, missed_temp_yesterday=False)
    svc.record_temperature(p1["patient_id"], 36.9, "nurse")
    assert by_id()[p1["patient_id"]]["workflow"] == svc.READY
    assert by_id()[p1["patient_id"]]["streak"] == 2, "Today's reading must not count until the day is complete"
    print("TEST 1   PASS  normal reading -> Ready for Doctor")

    # TEST 2 - duplicate routine reading blocked
    expect_error("duplicate", svc.record_temperature, p1["patient_id"], 37.0, "nurse")
    with db.read() as conn:
        n = conn.execute("SELECT COUNT(*) FROM temperature_records WHERE patient_id = ? AND record_date = ?",
                         (p1["patient_id"], svc.today().isoformat())).fetchone()[0]
    assert n == 1
    print("TEST 2   PASS  duplicate same-day reading prevented")

    # TEST 3 - fever resets the streak
    p3 = pick(workflow=svc.NEEDS_TEMP, streak=3)
    svc.record_temperature(p3["patient_id"], 38.6, "nurse")
    after = by_id()[p3["patient_id"]]
    assert after["streak"] == 0 and not after["eligible"]
    expect_error("not eligible", svc.approve_discharge, p3["patient_id"], "doctor")
    print("TEST 3   PASS  fever reading resets fever-free streak")

    # Correction keeps the original reading and writes an audit entry
    fixed = svc.correct_temperature(after["today_record_id"], 38.9, "Mis-keyed value", "nurse")
    with db.read() as conn:
        rows = conn.execute("SELECT is_active FROM temperature_records WHERE patient_id = ? AND record_date = ? "
                            "ORDER BY record_id", (p3["patient_id"], svc.today().isoformat())).fetchall()
    assert [r["is_active"] for r in rows] == [0, 1] and fixed["temperature_c"] == 38.9
    print("EXTRA    PASS  correction retains original reading with audit trail")

    # TEST 4 - visit before temperature blocked
    p4 = pick(workflow=svc.NEEDS_TEMP, streak=1)
    expect_error("awaiting nurse", svc.complete_visit, p4["patient_id"], "doctor", **VISIT)
    print("TEST 4   PASS  visit blocked before temperature is recorded")

    # TEST 5 - visit after temperature -> Doctor Visit Completed
    svc.complete_visit(p1["patient_id"], "doctor", **VISIT)
    assert by_id()[p1["patient_id"]]["workflow"] == svc.VISIT_DONE
    expect_error("already completed", svc.complete_visit, p1["patient_id"], "doctor", **VISIT)
    print("TEST 5   PASS  visit completed -> Doctor Visit Completed")

    # Role rules
    expect_error("only doctors", svc.approve_discharge, p1["patient_id"], "nurse")
    expect_error("only nursing", svc.record_temperature, p4["patient_id"], 37.0, "doctor")
    eligible_now = pick(eligible=True)
    expect_error("only administrative", svc.complete_checkout, eligible_now["patient_id"], "doctor")
    expect_error("not approved", svc.complete_checkout, eligible_now["patient_id"], "admin")
    print("EXTRA    PASS  role permissions enforced")

    # TEST 6 - third complete fever-free day -> eligible (p1 had 2 days + normal today)
    svc.advance_demo_day("admin")
    p6 = by_id()[p1["patient_id"]]
    assert p6["streak"] == 3 and p6["eligible"] and len(p6["qualifying_dates"]) == 3
    assert by_id()[p4["patient_id"]]["streak"] == 0, "A missed day must break the streak"
    assert by_id()[p4["patient_id"]]["missed_temp_yesterday"]
    print("TEST 6   PASS  three complete fever-free days -> eligible; missed day breaks streak")

    # TEST 7 - approval -> admin discharge queue
    svc.approve_discharge(p1["patient_id"], "doctor")
    assert by_id()[p1["patient_id"]]["status"] == "Discharge Approved"
    expect_error("already been approved", svc.approve_discharge, p1["patient_id"], "doctor")
    print("TEST 7   PASS  discharge approved -> visible in admin queue")

    # TEST 8 - checkout -> Recovered, room Pending Cleaning
    before = svc.facility_stats()
    svc.complete_checkout(p1["patient_id"], "admin")
    room = next(r for r in svc.list_rooms() if r["room_id"] == p1["room_id"])
    stats = svc.facility_stats()
    assert room["status"] == "Pending Cleaning" and room["current_patient_id"] is None
    assert stats["recoveries"] == before["recoveries"] + 1 and stats["current"] == before["current"] - 1
    expect_error("no longer an in-patient", svc.complete_checkout, p1["patient_id"], "admin")
    print("TEST 8   PASS  checkout -> Recovered, room Pending Cleaning")

    # Rule 11 - a room pending cleaning cannot be assigned
    new = dict(full_name="Test Patient", age=40, gender="Female", contact="+91 9812345678", symptoms="Fever")
    expect_error("cannot be assigned", svc.register_patient, "admin", room_id=p1["room_id"], initial_temp=38.4, **new)

    # TEST 9 - room cleaned -> Available
    svc.mark_room_cleaned(p1["room_id"], "admin")
    assert next(r for r in svc.list_rooms() if r["room_id"] == p1["room_id"])["status"] == "Available"
    print("TEST 9   PASS  room cleaned -> Available")

    # TEST 10 - new patient into the freed room
    created = svc.register_patient("admin", room_id=p1["room_id"], initial_temp=38.4, **new)
    admitted = by_id()[created["patient_id"]]
    assert admitted["room_id"] == p1["room_id"] and admitted["workflow"] == svc.READY
    assert svc.facility_stats()["admissions"] == stats["admissions"] + 1
    print("TEST 10  PASS  new patient admitted to the freed room:", created["patient_id"])

    # TEST 11 - death recorded, statistics update, outcome exactly once
    before = svc.facility_stats()
    victim = pick(priority_label="Awaiting Nurse", status="Admitted")
    expect_error("confirmation", svc.record_death, victim["patient_id"], "Cardiac arrest.", "doctor")
    svc.record_death(victim["patient_id"], "Cardiac arrest following respiratory failure.", "doctor", confirmed=True)
    stats = svc.facility_stats()
    assert stats["deaths"] == before["deaths"] + 1 and stats["recoveries"] == before["recoveries"]
    assert victim["patient_id"] not in by_id()
    assert next(r for r in svc.list_rooms() if r["room_id"] == victim["room_id"])["status"] == "Pending Cleaning"
    expect_error("no longer an in-patient", svc.record_death, victim["patient_id"], "Duplicate entry.", "doctor", confirmed=True)
    assert abs(stats["mortality_rate"] - stats["deaths"] / stats["admissions"] * 100) < 1e-9
    print("TEST 11  PASS  death recorded; mortality %.1f%%" % stats["mortality_rate"])

    # TEST 12 - mortality above 15% raises the alert
    while not svc.facility_stats()["mortality_alert"]:
        victim = pick(status="Admitted")
        svc.record_death(victim["patient_id"], "Deterioration despite treatment.", "doctor", confirmed=True)
    assert svc.facility_stats()["mortality_rate"] > 15
    print("TEST 12  PASS  mortality %.1f%% > 15%% -> alert" % svc.facility_stats()["mortality_rate"])

    # TEST 13 - data persists on disk across connections
    snapshot = svc.facility_stats()
    db.create_schema()  # what a restart runs
    svc.bootstrap()     # must not re-seed
    assert svc.facility_stats() == snapshot
    assert svc.authenticate("nurse", "nurse123") and not svc.authenticate("nurse", "wrong")
    with db.read() as conn:
        assert not any("nurse123" in r["password_hash"] for r in conn.execute("SELECT password_hash FROM users"))
        assert conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0] > 10
    stats = svc.facility_stats()
    counts = svc.room_counts()
    assert stats["admissions"] == stats["current"] + stats["recoveries"] + stats["deaths"]
    assert counts["occupied"] == stats["current"]
    assert counts["occupied"] + counts["available"] + counts["cleaning"] == 74
    print("TEST 13  PASS  data persisted; totals reconcile")

    # Admin reset restores the sample dataset
    svc.reset_demo("admin")
    assert svc.facility_stats()["admissions"] == stats0["admissions"] and svc.demo_day_offset() == 0
    print("EXTRA    PASS  demo reset restores the sample dataset")
    print("\nAll workflow checks passed.")


if __name__ == "__main__":
    test_full_workflow()
