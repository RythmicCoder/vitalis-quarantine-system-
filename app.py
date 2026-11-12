"""VITALIS — Quarantine & Patient Recovery Management System.

Run with:  streamlit run app.py
"""

import json
import sqlite3
from datetime import date, timedelta
from html import escape

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import services as svc
import ui

st.set_page_config(page_title="VITALIS · Patient Recovery Management", page_icon=":material/ecg_heart:",
                   layout="wide", initial_sidebar_state="auto")

FONT = dict(family="Plus Jakarta Sans, Segoe UI, sans-serif", color=ui.NAVY, size=13)
PLOT_CFG = {"displayModeBar": False}


@st.cache_resource(show_spinner="Preparing VITALIS…")
def _boot():
    svc.bootstrap()
    return True


# ------------------------------------------------------------------ helpers
def user():
    return st.session_state["user"]


def flash(kind, message):
    st.session_state["flash"] = (kind, message)


def show_flash():
    item = st.session_state.pop("flash", None)
    if item:
        kind, message = item
        {"success": st.success, "error": st.error, "warning": st.warning, "info": st.info}[kind](
            message, icon=":material/check_circle:" if kind == "success" else None)


def act(func, on_success):
    """Run a workflow action; show the rule that blocked it, or flash a confirmation and refresh."""
    try:
        result = func()
    except svc.WorkflowError as exc:
        st.error(str(exc), icon=":material/block:")
        return
    except sqlite3.IntegrityError:
        st.error("This action was already recorded. The screen has been refreshed with the latest data.",
                 icon=":material/block:")
        return
    except sqlite3.Error as exc:
        st.error(f"The database could not complete this action. Please try again. ({exc})")
        return
    flash("success", on_success(result))
    st.rerun()


def goto(page, patient_id=None):
    st.session_state["page"] = page
    if patient_id:
        st.session_state["current_patient"] = patient_id


def patient_label(p):
    return f"Room {p['room_number']} · {p['full_name']} · {p['patient_id']} · {p['workflow']}"


def patient_picker(patients, key, label="Select a patient or room"):
    """Selectbox that keeps the chosen patient when moving between screens."""
    lookup = {p["patient_id"]: p for p in patients}
    ids = list(lookup)
    if key in st.session_state and st.session_state[key] not in lookup:
        del st.session_state[key]
    current = st.session_state.get("current_patient")
    index = ids.index(current) if current in lookup else 0
    chosen = st.selectbox(label, ids, index=index, key=key, format_func=lambda i: patient_label(lookup[i]))
    st.session_state["current_patient"] = chosen
    return lookup[chosen]


def patient_card(p, extra_chips=""):
    fields = [
        ("Patient ID", f'<span class="mono">{p["patient_id"]}</span>'), ("Room", p["room_number"]),
        ("Age / Gender", f'{p["age"]} · {escape(p["gender"])}'), ("Admitted", ui.fmt_date(p["admission_date"])),
        ("Days in care", p["days_admitted"] + 1), ("Contact", escape(p["contact"])),
        ("Presenting symptoms", escape(p["symptoms"])),
    ]
    grid = "".join(f'<div><div class="pcard-k">{k}</div><div class="pcard-v">{v}</div></div>' for k, v in fields)
    st.html(f'<div class="pcard"><div class="pcard-head"><div class="pcard-name">{escape(p["full_name"])}</div>'
            f'<div>{ui.chip(p["workflow"])} {extra_chips}</div></div><div class="pcard-grid">{grid}</div></div>')


def streak_days_html(p):
    days = "".join(f'<div class="day">{d.strftime("%d %b")} · fever-free</div>' for d in p["qualifying_dates"][-3:])
    for _ in range(max(0, svc.REQUIRED_FEVER_FREE_DAYS - p["streak"])):
        days += '<div class="day todo">pending</div>'
    return f'<div class="days">{days}</div>'


def table(rows, columns=None, height=None):
    frame = pd.DataFrame(rows, columns=columns)
    kwargs = {"height": height} if height else {}
    st.dataframe(frame, hide_index=True, width="stretch", **kwargs)


# -------------------------------------------------------------------- login
def login_screen():
    st.html("<style>[data-testid='stSidebar'], [data-testid='stSidebarCollapsedControl'] {display:none}</style>")
    left, right = st.columns([1.15, 1], gap="large")
    with left:
        st.html(
            '<div class="login-brand"><div><div class="login-system">Quarantine &amp; Patient Recovery Management System</div>'
            '<div class="login-logo">VITAL<span>IS</span></div>'
            '<div class="login-tag">Precision in Care. Efficiency in Recovery.</div>'
            '<div class="login-points">'
            '<div class="login-point"><b>One temperature per patient, per day</b><span>Missed and duplicate checks are caught at entry.</span></div>'
            '<div class="login-point"><b>Rounds follow the readings</b><span>Doctors see only patients whose temperature is recorded.</span></div>'
            '<div class="login-point"><b>Discharge without delay</b><span>Three complete fever-free days trigger one-click approval and bed turnover.</span></div>'
            '</div></div><div class="login-foot">74-bed facility · Asia/Kolkata · Demonstration environment</div></div>')
    with right:
        st.html('<div class="login-title">Sign in to your portal</div>'
                '<div class="login-sub">Choose your role and enter your staff credentials.</div>')
        role = st.segmented_control("Portal", ["Nurse", "Doctor", "Admin"], default="Nurse", key="login_role")
        with st.form("login_form"):
            username = st.text_input("Username", placeholder="e.g. nurse")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", type="primary", width="stretch")
        if submitted:
            account = svc.authenticate(username, password)
            if not role:
                st.error("Select a portal to sign in to.")
            elif not account:
                st.error("Incorrect username or password.")
            elif account["role"] != role:
                st.error(f"This account does not have access to the {role} portal.")
            else:
                st.session_state["user"] = account
                st.session_state["page"] = PAGES[account["role"]][0][0]
                st.rerun()
        with st.expander("Demonstration accounts"):
            st.html('<div class="cred">Nurse &nbsp;· nurse / nurse123<br>Doctor · doctor / doctor123 (Head Doctor)<br>'
                    'Admin &nbsp;· admin / admin123</div>')


# -------------------------------------------------------------- nurse portal
def nurse_overview(now):
    patients = svc.list_inpatients()
    rooms = svc.room_counts()
    pending = [p for p in patients if p["workflow"] == svc.NEEDS_TEMP]
    done = len(patients) - len(pending)
    ready = [p for p in patients if p["workflow"] == svc.READY]
    ui.page_header("Nurse portal", "Nursing overview", "Daily temperature rounds at a glance.", now)
    ui.kpis([
        ("Occupied rooms", f'{rooms["occupied"]}<small> / {rooms["capacity"]}</small>', "Patients in care", ""),
        ("Need temperature check", len(pending), "Not yet recorded today", "amber"),
        ("Checks completed today", done, f"of {len(patients)} patients", "green"),
        ("Awaiting doctor visit", len(ready), "Temperature recorded, visit pending", "teal"),
    ])
    pct = round(done / len(patients) * 100) if patients else 0
    st.html(f'<div class="pcard"><div class="pcard-k">Today\'s temperature round</div>'
            f'<div class="pcard-v">{pct}% complete · {done} recorded, {len(pending)} remaining</div>'
            f'<div class="progress"><div style="width:{pct}%"></div></div></div>')
    left, right = st.columns(2, gap="large")
    with left:
        ui.section("Next patients to check", "missed-yesterday first")
        queue = sorted(pending, key=lambda p: (not p["missed_temp_yesterday"], p["room_number"]))[:6]
        if not queue:
            ui.empty("Every patient has a temperature recorded for today.")
        for p in queue:
            chips = ui.chip("Missed yesterday", "red") if p["missed_temp_yesterday"] else ui.chip(svc.NEEDS_TEMP)
            with st.container(key=f"row_n_{p['patient_id']}"):
                a, b = st.columns([5, 1.5], vertical_alignment="center")
                a.html(ui.patient_row_html(p, chips))
                b.button("Record", key=f"go_{p['patient_id']}", on_click=goto, args=("n_temp", p["patient_id"]),
                         width="stretch")
    with right:
        ui.section("Fever readings today", f"threshold {svc.fever_threshold():.1f} °C")
        fevers = sorted([p for p in patients if p["today_fever"]], key=lambda p: -p["today_temp"])[:6]
        if not fevers:
            ui.empty("No fever readings recorded today.")
        for p in fevers:
            st.html(f'<div class="pcard" style="padding:0.65rem 0.95rem;margin-bottom:0.5rem">'
                    f'{ui.patient_row_html(p, ui.chip(p["priority_label"]))}</div>')


def nurse_rooms(now):
    patients = svc.list_inpatients()
    rooms = svc.list_rooms()
    ui.page_header("Nurse portal", "Live room & patient queue", "All 74 rooms with today's temperature-check status.", now)
    c1, c2 = st.columns([1, 2.2], vertical_alignment="bottom")
    floor = c1.segmented_control("Floor", ["All", "1", "2", "3"], default="All", key="n_floor") or "All"
    with c2:
        ui.legend(["Needs Temp Check", "Temperature Recorded", "Ready for Doctor", "Doctor Visit Completed"])
    shown = [r for r in rooms if floor == "All" or str(r["floor"]) == floor]
    ui.nurse_room_grid(shown, {p["room_id"]: p for p in patients})
    ui.section("Open a room")
    a, b = st.columns([3, 1], vertical_alignment="bottom")
    with a:
        chosen = patient_picker(patients, "n_grid_pick", "Occupied room")
    b.button("Go to temperature entry", type="primary", on_click=goto, args=("n_temp", chosen["patient_id"]),
             width="stretch", icon=":material/thermostat:")


def nurse_temperature(now):
    patients = sorted(svc.list_inpatients(), key=lambda p: (p["workflow"] != svc.NEEDS_TEMP, p["room_number"]))
    threshold = svc.fever_threshold()
    ui.page_header("Nurse portal", "Daily temperature logging",
                   f"One routine reading per patient per calendar day. Fever threshold {threshold:.1f} °C.", now)
    if not patients:
        ui.empty("There are no admitted patients.")
        return
    p = patient_picker(patients, "n_temp_pick")
    streak_chip = ui.chip(f"Fever-free streak: {p['streak']} of 3 days", "green" if p["streak"] else "grey")
    patient_card(p, streak_chip)
    left, right = st.columns([1.1, 1], gap="large")
    with left:
        if p["today_temp"] is None:
            if p["missed_temp_yesterday"]:
                ui.banner("amber", "Yesterday's temperature was missed",
                          "A day without a reading never counts as fever-free, so the streak restarted.")
            with st.form(f"temp_form_{p['patient_id']}", clear_on_submit=True):
                st.markdown(f"**Record today's temperature — Room {p['room_number']}**")
                value = st.number_input("Temperature (°C)", min_value=34.0, max_value=43.0, value=37.0, step=0.1,
                                        format="%.1f")
                st.caption(f"Date, time and nurse ({user()['username']}) are recorded automatically.")
                submitted = st.form_submit_button("Submit reading", type="primary", icon=":material/thermostat:")
            if submitted:
                act(lambda: svc.record_temperature(p["patient_id"], value, user()["username"]),
                    lambda r: (f"Recorded {r['temperature_c']:.1f} °C "
                               f"({'FEVER' if r['is_fever'] else 'normal'}) for {r['patient_name']} at "
                               f"{r['recorded_at']:%H:%M} by {user()['username']}. Status is now Ready for Doctor."))
        else:
            tone = "red" if p["today_fever"] else "green"
            ui.banner(tone, f"Today's reading: {p['today_temp']:.1f} °C — {'fever' if p['today_fever'] else 'normal'}",
                      f"{p['today_record_type']} reading recorded {ui.fmt_dt(p['today_recorded_at'])} by "
                      f"{p['today_recorded_by']}. A second routine reading for today is not allowed.")
            with st.expander("Correct today's reading (audited)"):
                st.caption("The original reading is kept and marked as superseded. The correction, its reason and "
                           "your username are written to the audit log.")
                with st.form(f"fix_form_{p['patient_id']}", clear_on_submit=True):
                    new_value = st.number_input("Corrected temperature (°C)", min_value=34.0, max_value=43.0,
                                                value=float(p["today_temp"]), step=0.1, format="%.1f")
                    reason = st.text_input("Reason for correction", placeholder="e.g. Value mis-keyed")
                    fix = st.form_submit_button("Save correction")
                if fix:
                    act(lambda: svc.correct_temperature(p["today_record_id"], new_value, reason, user()["username"]),
                        lambda r: f"Correction saved for {r['patient_name']}: {r['temperature_c']:.1f} °C. "
                                  "The original reading remains in the audit trail.")
    with right:
        ui.section("Recent readings")
        history = svc.patient_history(p["patient_id"])
        rows = [{"Date": ui.fmt_date(t["record_date"]), "Time": t["recorded_at"][11:16],
                 "Temp (°C)": f"{t['temperature_c']:.1f}", "Result": "Fever" if t["is_fever"] else "Normal",
                 "Type": t["record_type"] if t["is_active"] else f"{t['record_type']} (superseded)",
                 "By": t["recorded_by"]} for t in reversed(history["temps"])][:8]
        table(rows)


def nurse_pending(now):
    patients = svc.list_inpatients()
    pending = [p for p in patients if p["workflow"] == svc.NEEDS_TEMP]
    ui.page_header("Nurse portal", "Pending temperature checks",
                   f"{len(pending)} of {len(patients)} patients have not been checked today.", now)
    c1, c2 = st.columns([2, 1])
    name = c1.text_input("Filter by patient name", placeholder="Type a name").strip().lower()
    room = c2.text_input("Filter by room", placeholder="e.g. 204").strip()
    shown = [p for p in pending if name in p["full_name"].lower() and p["room_number"].startswith(room)]
    shown.sort(key=lambda p: (not p["missed_temp_yesterday"], p["room_number"]))
    if not pending:
        ui.empty("All temperature checks are complete for today.")
    elif not shown:
        ui.empty("No pending patients match the filters.")
    for p in shown:
        chips = ui.chip(svc.NEEDS_TEMP)
        if p["missed_temp_yesterday"]:
            chips += " " + ui.chip("Missed yesterday", "red")
        last = f"Last: {p['last_temp']:.1f} °C on {ui.fmt_date(p['last_temp_date'])}" if p["last_temp"] else ""
        with st.container(key=f"row_p_{p['patient_id']}"):
            a, b = st.columns([5, 1.3], vertical_alignment="center")
            a.html(ui.patient_row_html(p, f'{chips} <span class="prow-meta">&nbsp;{last}</span>'))
            b.button("Record temperature", key=f"pend_{p['patient_id']}", on_click=goto,
                     args=("n_temp", p["patient_id"]), width="stretch")


# ------------------------------------------------------------- doctor portal
def doctor_overview(now):
    patients = svc.list_inpatients()
    ready = sorted([p for p in patients if p["workflow"] == svc.READY], key=_queue_key)
    done = [p for p in patients if p["workflow"] == svc.VISIT_DONE]
    waiting = [p for p in patients if p["workflow"] == svc.NEEDS_TEMP]
    eligible = [p for p in patients if p["eligible"]]
    ui.page_header("Doctor portal", "Clinical overview", "Rounds, recovery progress and discharge readiness.", now)
    ui.kpis([
        ("Total patients", len(patients), "Currently in care", ""),
        ("Ready for doctor visit", len(ready), f"{len(waiting)} awaiting nurse", "teal"),
        ("Visits completed today", len(done), f"of {len(patients)} patients", "green"),
        ("Eligible for discharge", len(eligible), "3 complete fever-free days", "amber"),
    ])
    missed = [p for p in patients if p["missed_visit_yesterday"]]
    if missed:
        ui.banner("amber", f"{len(missed)} patient(s) had no doctor visit yesterday",
                  "Rooms: " + ", ".join(p["room_number"] for p in missed))
    left, right = st.columns(2, gap="large")
    with left:
        ui.section("Highest priority now")
        if not ready:
            ui.empty("No patients are waiting for a visit.")
        for p in ready[:5]:
            with st.container(key=f"row_do_{p['patient_id']}"):
                a, b = st.columns([5, 1.4], vertical_alignment="center")
                a.html(ui.patient_row_html(p, ui.chip(p["priority_label"])))
                b.button("Start visit", key=f"ov_{p['patient_id']}", on_click=goto, args=("d_visit", p["patient_id"]),
                         width="stretch")
    with right:
        ui.section("Eligible for discharge")
        if not eligible:
            ui.empty("No patients have completed three fever-free days yet.")
        for p in eligible[:5]:
            with st.container(key=f"row_de_{p['patient_id']}"):
                a, b = st.columns([5, 1.4], vertical_alignment="center")
                a.html(ui.patient_row_html(p, ui.chip(f"{p['streak']} fever-free days", "green")))
                b.button("Review", key=f"oe_{p['patient_id']}", on_click=goto, args=("d_discharge", p["patient_id"]),
                         width="stretch")


def _queue_key(p):
    return (p["priority"], -p["today_temp"] if p["priority"] == 1 else 0,
            -p["fever_days"] if p["priority"] == 2 else -p["streak"], p["room_number"])


def doctor_queue(now):
    patients = svc.list_inpatients()
    ready = sorted([p for p in patients if p["workflow"] == svc.READY], key=_queue_key)
    waiting = [p for p in patients if p["workflow"] == svc.NEEDS_TEMP]
    done = [p for p in patients if p["workflow"] == svc.VISIT_DONE]
    ui.page_header("Doctor portal", "Rounds queue",
                   "Ordered by clinical priority: critical fever, persistent fever, then recovering patients.", now)
    ui.section("Ready for visit", f"{len(ready)} patients · temperature recorded today")
    if not ready:
        ui.empty("No patients are ready for a visit yet.")
    for p in ready:
        chips = ui.chip(p["priority_label"])
        if p["fever_days"] >= 2:
            chips += " " + ui.chip(f"{p['fever_days']} fever days", "grey")
        if p["streak"]:
            chips += " " + ui.chip(f"{p['streak']} fever-free day{'s' if p['streak'] > 1 else ''}", "green")
        with st.container(key=f"row_q_{p['patient_id']}"):
            a, b, c = st.columns([5, 1.1, 1.2], vertical_alignment="center")
            a.html(ui.patient_row_html(p, chips))
            b.button("Profile", key=f"qp_{p['patient_id']}", on_click=goto, args=("d_profile", p["patient_id"]),
                     width="stretch")
            c.button("Start visit", key=f"qv_{p['patient_id']}", type="primary", on_click=goto,
                     args=("d_visit", p["patient_id"]), width="stretch")
    ui.section("Awaiting nurse", f"{len(waiting)} patients · visit locked until temperature is recorded")
    if not waiting:
        ui.empty("Every patient has a temperature recorded today.")
    for p in waiting:
        with st.container(key=f"row_w_{p['patient_id']}"):
            a, b, c = st.columns([5, 1.1, 1.2], vertical_alignment="center")
            a.html(ui.patient_row_html(p, ui.chip("Awaiting Nurse")))
            b.button("Profile", key=f"wp_{p['patient_id']}", on_click=goto, args=("d_profile", p["patient_id"]),
                     width="stretch")
            c.button("Visit locked", key=f"wv_{p['patient_id']}", disabled=True, width="stretch",
                     icon=":material/lock:")
    ui.section("Visit completed today", f"{len(done)} patients")
    if done:
        table([{"Room": p["room_number"], "Patient": p["full_name"], "Patient ID": p["patient_id"],
                "Temp (°C)": f"{p['today_temp']:.1f}", "Visited": ui.fmt_dt(p["visit_at"], False),
                "Fever-free days": p["streak"], "Status": p["status"]} for p in done])
    else:
        ui.empty("No visits completed yet today.")


def temperature_chart(history, p, threshold, on_date):
    active = {t["record_date"]: t for t in history["temps"] if t["is_active"]}
    days = [p["admission_date"] + timedelta(days=i) for i in range((on_date - p["admission_date"]).days + 1)]
    values = [active[d.isoformat()]["temperature_c"] if d.isoformat() in active else None for d in days]
    colors = [ui.SLATE if v is None else (ui.RED if active[d.isoformat()]["is_fever"] else ui.GREEN)
              for d, v in zip(days, values)]
    fig = go.Figure()
    for d in p["qualifying_dates"]:
        fig.add_vrect(x0=d - timedelta(hours=12), x1=d + timedelta(hours=12), fillcolor=ui.GREEN, opacity=0.08,
                      line_width=0)
    fig.add_trace(go.Scatter(x=days, y=values, mode="lines+markers", connectgaps=False,
                             line=dict(color=ui.NAVY, width=2.5),
                             marker=dict(size=11, color=colors, line=dict(color="#FFFFFF", width=2)),
                             hovertemplate="%{x|%d %b}: %{y:.1f} °C<extra></extra>", name="Temperature"))
    missing = [d for d, v in zip(days, values) if v is None and d < on_date]
    if missing:
        fig.add_trace(go.Scatter(x=missing, y=[threshold - 2.4] * len(missing), mode="markers+text",
                                 marker=dict(symbol="x", size=10, color=ui.AMBER), text=["missed"] * len(missing),
                                 textposition="top center", textfont=dict(color=ui.AMBER, size=11),
                                 hovertemplate="%{x|%d %b}: no reading recorded<extra></extra>", name="Missed"))
    fig.add_hline(y=threshold, line_dash="dash", line_color=ui.RED, line_width=1.5,
                  annotation_text=f"Fever threshold {threshold:.1f} °C", annotation_position="top left",
                  annotation_font=dict(color=ui.RED, size=11))
    fig.update_layout(height=320, margin=dict(l=10, r=10, t=20, b=10), font=FONT, showlegend=False,
                      plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF",
                      yaxis=dict(title="°C", range=[35.2, 41], gridcolor="#EEF1F5", zeroline=False),
                      xaxis=dict(tickformat="%d %b", dtick=86400000, gridcolor="#F4F6F9"))
    return fig


def doctor_profile(now):
    patients = svc.list_inpatients()
    ui.page_header("Doctor portal", "Patient medical profile", "Temperature trend, visits and treatment history.", now)
    if not patients:
        ui.empty("There are no admitted patients.")
        return
    p = patient_picker(patients, "d_profile_pick", "Select a patient")
    history = svc.patient_history(p["patient_id"])
    threshold = svc.fever_threshold()
    extra = ui.chip(p["status"])
    if p["eligible"]:
        extra += " " + ui.chip("Eligible for Discharge")
    patient_card(p, extra)
    temp = f'{p["today_temp"]:.1f}<small> °C</small>' if p["today_temp"] is not None else "—"
    last = f"Last: {p['last_temp']:.1f} °C on {ui.fmt_date(p['last_temp_date'])}" if p["last_temp"] else "No readings"
    ui.kpis([
        ("Current temperature", temp, "Recorded today" if p["today_temp"] is not None else f"Awaiting nurse · {last}",
         "red" if p["today_fever"] else ("green" if p["today_temp"] is not None else "amber")),
        ("Fever-free streak", f'{p["streak"]}<small> / 3 days</small>', "Complete calendar days only",
         "green" if p["streak"] >= 3 else ""),
        ("Workflow status", f'<span style="font-size:1.15rem">{p["workflow"]}</span>', "Today", "teal"),
        ("Doctor visits", len(history["visits"]), "Since admission", ""),
    ])
    a, b, _ = st.columns([1.2, 1.4, 4])
    a.button("Record visit", type="primary", on_click=goto, args=("d_visit", p["patient_id"]), width="stretch",
             icon=":material/stethoscope:")
    b.button("Discharge & outcome", on_click=goto, args=("d_discharge", p["patient_id"]), width="stretch")
    ui.section("Temperature trend", "green band = qualifying fever-free day · today counts once the day ends")
    with st.container(key="card_chart"):
        st.plotly_chart(temperature_chart(history, p, threshold, now.date()), width="stretch", config=PLOT_CFG)
    tab1, tab2, tab3 = st.tabs(["Temperature history", "Doctor visits", "Treatment history"])
    with tab1:
        active = {t["record_date"]: t for t in history["temps"] if t["is_active"]}
        visit_days = {v["visit_date"] for v in history["visits"]}
        rows, day = [], now.date()
        while day >= p["admission_date"]:
            t = active.get(day.isoformat())
            if t:
                result = "Fever" if t["is_fever"] else "Normal"
                rows.append({"Date": ui.fmt_date(day), "Temp (°C)": f"{t['temperature_c']:.1f}", "Result": result,
                             "Type": t["record_type"], "Recorded": t["recorded_at"][11:16], "By": t["recorded_by"],
                             "Doctor visit": "Completed" if day.isoformat() in visit_days else "Not recorded"})
            else:
                rows.append({"Date": ui.fmt_date(day), "Temp (°C)": "—",
                             "Result": "Awaiting nurse" if day == now.date() else "MISSED — not fever-free",
                             "Type": "—", "Recorded": "—", "By": "—",
                             "Doctor visit": "Completed" if day.isoformat() in visit_days else "Not recorded"})
            day -= timedelta(days=1)
        table(rows)
        superseded = [t for t in history["temps"] if not t["is_active"]]
        if superseded:
            st.caption("Superseded readings (kept for audit): " + "; ".join(
                f"{ui.fmt_date(t['record_date'])} {t['temperature_c']:.1f} °C by {t['recorded_by']}" for t in superseded))
    with tab2:
        if history["visits"]:
            table([{"Date & time": ui.fmt_dt(v["visited_at"]), "Doctor": v["doctor"],
                    "Observations": v["observations"], "Symptoms": v["symptoms"], "Assessment": v["assessment"],
                    "Nursing instructions": v["nursing_instructions"]} for v in history["visits"]])
        else:
            ui.empty("No doctor visits recorded yet.")
    with tab3:
        if history["treatments"]:
            table([{"Prescribed": ui.fmt_dt(t["prescribed_at"]), "Treatment": t["treatment"],
                    "Medication": t["medication"] or "—", "Dosage": t["dosage"] or "—", "By": t["prescribed_by"]}
                   for t in history["treatments"]])
        else:
            ui.empty("No treatments recorded yet.")


def doctor_visit(now):
    patients = sorted(svc.list_inpatients(), key=lambda p: ({svc.READY: 0, svc.NEEDS_TEMP: 1}.get(p["workflow"], 2),)
                      + _queue_key(p))
    ui.page_header("Doctor portal", "Doctor visit & treatment",
                   "A visit can be completed only after today's temperature is recorded.", now)
    if not patients:
        ui.empty("There are no admitted patients.")
        return
    p = patient_picker(patients, "d_visit_pick", "Select a patient")
    patient_card(p, ui.chip(f"Fever-free streak: {p['streak']} of 3 days", "green" if p["streak"] else "grey"))
    if p["workflow"] == svc.NEEDS_TEMP:
        ui.banner("amber", "Awaiting Nurse — visit locked",
                  "Today's temperature has not been recorded for this patient. The visit form opens automatically "
                  "once the nurse submits the reading.")
        st.button("Complete Doctor Visit", disabled=True, icon=":material/lock:")
        return
    tone = "red" if p["today_fever"] else "green"
    ui.banner(tone, f"Today's temperature: {p['today_temp']:.1f} °C — {'fever' if p['today_fever'] else 'normal'}",
              f"Recorded {ui.fmt_dt(p['today_recorded_at'])} by {p['today_recorded_by']}.")
    if p["workflow"] == svc.VISIT_DONE:
        visit = svc.patient_history(p["patient_id"])["visits"][0]
        ui.banner("blue", "Today's doctor visit is completed",
                  f"Recorded {ui.fmt_dt(visit['visited_at'])} by {visit['doctor']}. Assessment: {visit['assessment']}")
        if p["eligible"]:
            st.button("Review discharge eligibility", type="primary", on_click=goto,
                      args=("d_discharge", p["patient_id"]))
        return
    with st.form(f"visit_form_{p['patient_id']}"):
        st.markdown(f"**Visit record — {p['full_name']}, Room {p['room_number']}**")
        c1, c2 = st.columns(2)
        observations = c1.text_area("Medical observations *", height=110,
                                    placeholder="General condition, vitals, examination findings")
        symptoms = c2.text_area("Symptoms", height=110, placeholder="Reported and observed symptoms")
        assessment = c1.text_area("Diagnosis / assessment *", height=90)
        treatment = c2.text_area("Treatment prescribed", height=90)
        medication = c1.text_input("Medication")
        dosage = c2.text_input("Dosage", placeholder="e.g. 650 mg every 6 hours")
        instructions = st.text_area("Nursing instructions", height=80)
        st.caption(f"Doctor ({user()['username']}), date and time are recorded automatically. * required")
        submitted = st.form_submit_button("Complete Doctor Visit", type="primary", icon=":material/task_alt:")
    if submitted:
        act(lambda: svc.complete_visit(p["patient_id"], user()["username"], observations, symptoms, assessment,
                                       treatment, medication, dosage, instructions),
            lambda r: f"Visit completed for {r['patient_name']} at {r['visited_at']:%H:%M}. "
                      "Status is now Doctor Visit Completed.")


def doctor_discharge(now):
    patients = svc.list_inpatients()
    eligible = [p for p in patients if p["eligible"]]
    approved = [p for p in patients if p["status"] == "Discharge Approved"]
    progressing = sorted([p for p in patients if p["status"] == "Admitted" and 0 < p["streak"] < 3],
                         key=lambda p: -p["streak"])
    ui.page_header("Doctor portal", "Discharge approval & outcomes",
                   "Approval requires three complete, consecutive fever-free calendar days.", now)
    current = st.session_state.get("current_patient")
    eligible.sort(key=lambda p: (p["patient_id"] != current, p["room_number"]))
    ui.section("Eligible for discharge", f"{len(eligible)} patients")
    if not eligible:
        ui.empty("No patients currently meet the three-day fever-free criterion.")
    for p in eligible:
        with st.container(key=f"card_el_{p['patient_id']}"):
            a, b = st.columns([4.2, 1.5], vertical_alignment="center")
            today_note = ("Today's reading is normal." if p["today_temp"] is not None
                          else "Today's temperature has not been recorded yet.")
            a.html(f'{ui.patient_row_html(p, ui.chip("Eligible for Discharge"))}'
                   f'<div class="prow-meta" style="margin-top:0.5rem">Qualifying days · {today_note}</div>'
                   f'{streak_days_html(p)}')
            if b.button("Approve Discharge", key=f"ap_{p['patient_id']}", type="primary", width="stretch",
                        icon=":material/verified:"):
                act(lambda pid=p["patient_id"]: svc.approve_discharge(pid, user()["username"]),
                    lambda r: f"Discharge approved for {r['patient_name']}. The patient is now in the Admin "
                              "discharge queue.")
    ui.section("Approaching eligibility", "approval is locked until day 3 is complete")
    if progressing:
        table([{"Room": p["room_number"], "Patient": p["full_name"], "Patient ID": p["patient_id"],
                "Fever-free days": f"{p['streak']} of 3",
                "Qualifying dates": ", ".join(d.strftime("%d %b") for d in p["qualifying_dates"]),
                "Today": f"{p['today_temp']:.1f} °C" if p["today_temp"] is not None else "Awaiting nurse"}
               for p in progressing])
    else:
        ui.empty("No patients are partway through their fever-free streak.")
    ui.section("Approved — awaiting administrative checkout", f"{len(approved)} patients")
    if approved:
        table([{"Room": p["room_number"], "Patient": p["full_name"], "Patient ID": p["patient_id"],
                "Approved by": p["approved_by"], "Approved at": ui.fmt_dt(p["approved_at"])} for p in approved])
    else:
        ui.empty("No approvals are waiting for checkout.")

    ui.section("Record patient death", "controlled action · recorded once and cannot be undone")
    with st.expander("Open mortality recording form"):
        if not patients:
            ui.empty("There are no admitted patients.")
            return
        lookup = {p["patient_id"]: p for p in patients}
        with st.form("death_form", clear_on_submit=True):
            pid = st.selectbox("Patient", list(lookup), format_func=lambda i: patient_label(lookup[i]),
                               index=list(lookup).index(current) if current in lookup else 0)
            notes = st.text_area("Relevant medical notes *", placeholder="Cause and circumstances of death")
            st.caption(f"Date and time of death and the responsible doctor ({user()['username']}) are recorded "
                       "automatically. The room moves to Pending Cleaning.")
            confirmed = st.checkbox("I confirm this patient has died and the record should be saved permanently.")
            submitted = st.form_submit_button("Record Patient Death", icon=":material/warning:")
        if submitted:
            act(lambda: svc.record_death(pid, notes, user()["username"], confirmed),
                lambda r: f"Death recorded for {r['patient_name']} at {r['outcome_at']:%H:%M}. Outcome: Deceased. "
                          f"Room {r['room_number']} is now Pending Cleaning.")


# ---------------------------------------------------------------- analytics
def performance(now, kicker, allow_threshold):
    s = svc.facility_stats()
    ui.page_header(kicker, "Facility performance & mortality",
                   "Outcome statistics for all admissions. Every rate uses total admissions as the denominator.", now)
    if s["mortality_alert"]:
        ui.banner("red", f"Mortality alert: {s['mortality_rate']:.1f}% exceeds the 15% expected benchmark",
                  f"{s['deaths']} deaths in {s['admissions']} admissions. Review clinical performance immediately.")
    ui.kpis([
        ("Total admissions", s["admissions"], "All patients ever admitted", ""),
        ("Total recoveries", s["recoveries"], "Discharged after approval", "green"),
        ("Total deaths", s["deaths"], "Outcome: Deceased", "red"),
        ("Currently admitted", s["current"], "No outcome yet", "teal"),
        ("Mortality rate", f'{s["mortality_rate"]:.1f}<small>%</small>', "Deaths ÷ admissions · benchmark 15%",
         "red" if s["mortality_alert"] else "green"),
        ("Recovery rate", f'{s["recovery_rate"]:.1f}<small>%</small>', "Recoveries ÷ admissions", "green"),
    ])
    st.caption(f"Reconciliation: {s['admissions']} admissions = {s['recoveries']} recovered + {s['deaths']} deceased "
               f"+ {s['current']} currently admitted. Each patient has at most one outcome.")
    left, right = st.columns([1, 1.25], gap="large")
    with left:
        ui.section("Mortality rate vs expected benchmark")
        with st.container(key="card_gauge"):
            color = ui.RED if s["mortality_alert"] else ui.NAVY
            fig = go.Figure(go.Indicator(
                mode="gauge+number", value=s["mortality_rate"],
                number=dict(suffix="%", valueformat=".1f", font=dict(size=46, color=color)),
                gauge=dict(axis=dict(range=[0, 40], ticksuffix="%", tickvals=[0, 10, 15, 20, 30, 40]),
                           bar=dict(color=color, thickness=0.55), bgcolor="#FFFFFF", borderwidth=0,
                           steps=[dict(range=[0, 15], color="#E7F6EE"), dict(range=[15, 40], color="#FDEEEE")],
                           threshold=dict(line=dict(color=ui.RED, width=4), thickness=0.9, value=15))))
            fig.update_layout(height=270, margin=dict(l=30, r=30, t=30, b=10), font=FONT, paper_bgcolor="#FFFFFF")
            st.plotly_chart(fig, width="stretch", config=PLOT_CFG)
            st.caption("Red line: expected mortality benchmark of 15%.")
    with right:
        ui.section("Outcomes of all admissions")
        with st.container(key="card_outcomes"):
            labels = ["Recovered", "Deceased", "Currently admitted"]
            values = [s["recoveries"], s["deaths"], s["current"]]
            fig = go.Figure(go.Bar(
                y=labels, x=values, orientation="h", marker_color=[ui.GREEN, ui.RED, ui.TEAL],
                text=[f"{v}  ({v / s['admissions'] * 100:.1f}%)" if s["admissions"] else "0" for v in values],
                textposition="outside", cliponaxis=False, hovertemplate="%{y}: %{x}<extra></extra>"))
            fig.update_layout(height=270, margin=dict(l=10, r=90, t=20, b=30), font=FONT, plot_bgcolor="#FFFFFF",
                              paper_bgcolor="#FFFFFF", xaxis=dict(title="Patients", gridcolor="#EEF1F5"),
                              yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig, width="stretch", config=PLOT_CFG)
            st.caption("Share of total admissions. Patients still admitted have no outcome yet.")
    ui.section("Benchmarks")
    b1, b2 = st.columns(2, gap="large")
    with b1:
        gap = s["mortality_rate"] - svc.MORTALITY_BENCHMARK
        ui.banner("red" if s["mortality_alert"] else "green", "Expected mortality benchmark: 15%",
                  f"Facility mortality is {s['mortality_rate']:.1f}% — {abs(gap):.1f} percentage points "
                  f"{'above' if gap > 0 else 'below'} the benchmark.")
    with b2:
        ui.banner("blue", "Complementary recovery benchmark: 85%",
                  f"This is 100% minus the 15% mortality benchmark, not a guaranteed clinical recovery rate. "
                  f"Recovery rate so far is {s['recovery_rate']:.1f}% of admissions; it rises as the "
                  f"{s['current']} current patients reach an outcome.")
    if s["resolved"]:
        st.caption(f"For reference: among the {s['resolved']} patients with a final outcome, "
                   f"{s['resolved_mortality']:.1f}% died and {100 - s['resolved_mortality']:.1f}% recovered.")
    ui.section("Admissions and outcomes, last 30 days")
    with st.container(key="card_trend"):
        days = [now.date() - timedelta(days=i) for i in range(29, -1, -1)]
        fig = go.Figure()
        for name, series, color in (("Admissions", s["admitted_by_day"], ui.NAVY),
                                    ("Recoveries", s["recovered_by_day"], ui.GREEN),
                                    ("Deaths", s["deaths_by_day"], ui.RED)):
            fig.add_trace(go.Bar(x=days, y=[series.get(d.isoformat(), 0) for d in days], name=name,
                                 marker_color=color, hovertemplate="%{x|%d %b}: %{y}<extra>" + name + "</extra>"))
        fig.update_layout(height=300, barmode="group", bargap=0.25, margin=dict(l=10, r=10, t=10, b=10), font=FONT,
                          plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF",
                          legend=dict(orientation="h", y=1.12, x=0),
                          yaxis=dict(title="Patients", gridcolor="#EEF1F5", dtick=1),
                          xaxis=dict(tickformat="%d %b"))
        st.plotly_chart(fig, width="stretch", config=PLOT_CFG)
    if allow_threshold:
        ui.section("Clinical settings", "Head Doctor only")
        with st.form("threshold_form"):
            value = st.number_input("Fever threshold (°C) — readings at or above this value count as fever",
                                    min_value=37.0, max_value=39.0, value=svc.fever_threshold(), step=0.1,
                                    format="%.1f")
            st.caption("Applies to readings recorded from now on. Earlier readings keep the threshold in force "
                       "when they were taken.")
            if st.form_submit_button("Save threshold"):
                act(lambda: svc.set_fever_threshold(value, user()["username"]),
                    lambda v: f"Fever threshold set to {v:.1f} °C.")


def doctor_analytics(now):
    performance(now, "Head Doctor oversight", True)


# --------------------------------------------------------------- admin portal
def admin_overview(now):
    rooms = svc.room_counts()
    patients = svc.list_inpatients()
    waiting = svc.list_waiting()
    approved = [p for p in patients if p["status"] == "Discharge Approved"]
    ui.page_header("Admin portal", "Administration overview", "Capacity, admissions and discharge processing.", now)
    ui.kpis([
        ("Facility capacity", rooms["capacity"], "Total rooms", ""),
        ("Occupied rooms", rooms["occupied"], f'{rooms["occupied"] / rooms["capacity"] * 100:.0f}% occupancy', "teal"),
        ("Available rooms", rooms["available"], "Clean and ready to assign", "green"),
        ("Pending cleaning", rooms["cleaning"], "Not assignable yet", "amber"),
        ("Awaiting admission", len(waiting), "Registered, no room assigned", "amber"),
        ("Awaiting discharge", len(approved), "Approved by a doctor", "teal"),
    ])
    left, right = st.columns(2, gap="large")
    with left:
        ui.section("Discharge queue")
        if not approved:
            ui.empty("No approved discharges are waiting.")
        for p in approved[:5]:
            st.html(f'<div class="pcard" style="padding:0.65rem 0.95rem;margin-bottom:0.5rem">'
                    f'{ui.patient_row_html(p, ui.chip("Discharge Approved"))}</div>')
        st.button("Process discharges", type="primary", on_click=goto, args=("a_discharge",), disabled=not approved)
    with right:
        ui.section("Rooms pending cleaning")
        cleaning = [r for r in svc.list_rooms() if r["status"] == "Pending Cleaning"]
        if not cleaning:
            ui.empty("No rooms are waiting to be cleaned.")
        else:
            st.html('<div class="pcard"><div class="days">' + "".join(
                f'<div class="day" style="border-color:#F2DDA6;color:#7A4E00">Room {r["room_number"]}</div>'
                for r in cleaning) + "</div></div>")
        st.button("Manage rooms", on_click=goto, args=("a_rooms",))


def admin_register(now):
    rooms = [r for r in svc.list_rooms() if r["status"] == "Available"]
    waiting = svc.list_waiting()
    ui.page_header("Admin portal", "Patient registration & admission",
                   f"{len(rooms)} clean room(s) available. Patient IDs are generated automatically.", now)
    if not rooms:
        ui.banner("amber", "No rooms are available",
                  "New patients can be registered to the admission queue and admitted once a room has been cleaned.")
    room_lookup = {r["room_id"]: r for r in rooms}
    with st.form("register_form", clear_on_submit=True):
        st.markdown("**New patient**")
        c1, c2, c3 = st.columns([2, 1, 1])
        name = c1.text_input("Full name *")
        age = c2.number_input("Age *", min_value=0, max_value=120, value=35, step=1)
        gender = c3.selectbox("Gender *", ["Female", "Male", "Other"])
        c4, c5 = st.columns(2)
        contact = c4.text_input("Contact information *", placeholder="Phone or email")
        admission_date = c5.date_input("Admission date *", value=now.date(), min_value=now.date() - timedelta(days=3),
                                       max_value=now.date(), format="DD/MM/YYYY")
        symptoms = st.text_area("Symptoms *", height=80, placeholder="Presenting symptoms")
        c6, c7 = st.columns(2)
        temp = c6.number_input("Initial temperature (°C) *", min_value=34.0, max_value=43.0, value=38.5, step=0.1,
                               format="%.1f")
        room_id = c7.selectbox(
            "Assigned room *", [None] + list(room_lookup),
            index=1 if rooms else 0,
            format_func=lambda i: "Admission queue — assign a room later" if i is None
            else f"Room {room_lookup[i]['room_number']} · Floor {room_lookup[i]['floor']} · Available")
        submitted = st.form_submit_button("Register patient", type="primary", icon=":material/person_add:")
    if submitted:
        act(lambda: svc.register_patient(user()["username"], name, age, gender, contact, symptoms, room_id,
                                         admission_date, temp),
            lambda r: (f"{r['full_name']} admitted as {r['patient_id']} to Room {r['room_number']}. The patient is "
                       "now visible to nurses and doctors.") if r["room_number"]
            else f"{r['full_name']} registered as {r['patient_id']} and added to the admission queue.")
    ui.section("Awaiting admission processing", f"{len(waiting)} registered patient(s) without a room")
    if not waiting:
        ui.empty("The admission queue is empty.")
    for w in waiting:
        with st.container(key=f"card_w_{w['patient_id']}"):
            with st.form(f"admit_{w['patient_id']}", border=False):
                a, b, c, d = st.columns([3, 2, 1.4, 1.2], vertical_alignment="bottom")
                a.html(f'<div class="prow-name">{escape(w["full_name"])}</div><div class="prow-meta">'
                       f'<span class="mono">{w["patient_id"]}</span> · {w["age"]} y · {escape(w["gender"])} · '
                       f'{escape(w["symptoms"])}<br>Registered {ui.fmt_dt(w["registered_at"])}</div>')
                chosen = b.selectbox("Room", list(room_lookup) or [None],
                                     format_func=lambda i: "No room available" if i is None
                                     else f"Room {room_lookup[i]['room_number']}", key=f"wr_{w['patient_id']}")
                t = c.number_input("Initial temp (°C)", min_value=34.0, max_value=43.0, value=38.5, step=0.1,
                                   format="%.1f", key=f"wt_{w['patient_id']}")
                admit = d.form_submit_button("Admit", type="primary", disabled=not rooms, width="stretch")
            if admit:
                act(lambda: svc.admit_from_queue(w["patient_id"], chosen, t, user()["username"]),
                    lambda r: f"{r['full_name']} admitted to Room {r['room_number']}.")


def admin_rooms(now):
    rooms = svc.list_rooms()
    counts = svc.room_counts()
    ui.page_header("Admin portal", "Room occupancy management",
                   "A room becomes assignable only after it has been marked cleaned.", now)
    ui.kpis([
        ("Occupied", counts["occupied"], "Patient in room", ""),
        ("Available", counts["available"], "Clean, assignable", "green"),
        ("Pending cleaning", counts["cleaning"], "Blocked from assignment", "amber"),
    ])
    cleaning = [r for r in rooms if r["status"] == "Pending Cleaning"]
    ui.section("Rooms pending cleaning", f"{len(cleaning)} room(s)")
    if not cleaning:
        ui.empty("No rooms are waiting to be cleaned.")
    for chunk in [cleaning[i:i + 4] for i in range(0, len(cleaning), 4)]:
        for col, r in zip(st.columns(4), chunk):
            with col.container(key=f"card_c_{r['room_id']}"):
                st.html(f'<div class="prow"><div class="prow-room">{r["room_number"]}</div>'
                        f'<div class="prow-meta">Floor {r["floor"]}<br>since {ui.fmt_dt(r["updated_at"])}</div></div>')
                if st.button("Mark Room Cleaned", key=f"clean_{r['room_id']}", width="stretch",
                             icon=":material/cleaning_services:"):
                    act(lambda rid=r["room_id"]: svc.mark_room_cleaned(rid, user()["username"]),
                        lambda number: f"Room {number} marked cleaned and is now Available.")
    ui.section("Occupancy board", "all 74 rooms")
    ui.legend(["Occupied", "Available", "Pending Cleaning"])
    ui.admin_room_grid(rooms)


def admin_discharge(now):
    approved = [p for p in svc.list_inpatients() if p["status"] == "Discharge Approved"]
    names = svc.user_directory()
    ui.page_header("Admin portal", "Discharge processing queue",
                   "Patients approved for discharge by a doctor. Checkout frees the room for cleaning.", now)
    if not approved:
        ui.empty("No patients are waiting for checkout. Approved discharges appear here immediately.")
    for p in sorted(approved, key=lambda p: p["approved_at"]):
        with st.container(key=f"card_d_{p['patient_id']}"):
            a, b = st.columns([4.2, 1.6], vertical_alignment="center")
            a.html(f'{ui.patient_row_html(p, ui.chip("Discharge Approved"))}'
                   f'<div class="pcard-grid"><div><div class="pcard-k">Approved by</div><div class="pcard-v">'
                   f'{escape(names.get(p["approved_by"], p["approved_by"]))} ({p["approved_by"]})</div></div>'
                   f'<div><div class="pcard-k">Approval time</div><div class="pcard-v">{ui.fmt_dt(p["approved_at"])}</div></div>'
                   f'<div><div class="pcard-k">Fever-free streak</div><div class="pcard-v">{p["streak"]} complete days</div></div></div>')
            if b.button("Complete Patient Checkout", key=f"co_{p['patient_id']}", type="primary", width="stretch",
                        icon=":material/logout:"):
                act(lambda pid=p["patient_id"]: svc.complete_checkout(pid, user()["username"]),
                    lambda r: f"{r['patient_name']} checked out at {r['checkout_at']:%H:%M} and recorded as "
                              f"Recovered/Discharged. Room {r['room_number']} is now Pending Cleaning.")
    cleaning = [r for r in svc.list_rooms() if r["status"] == "Pending Cleaning"]
    if cleaning:
        ui.section("Next step", f"{len(cleaning)} room(s) pending cleaning")
        st.button("Go to room management to mark rooms cleaned", on_click=goto, args=("a_rooms",))


def admin_performance(now):
    performance(now, "Admin portal", False)


def admin_settings(now):
    ui.page_header("Admin portal", "System settings", "Demonstration tools and the audit trail.", now)
    left, right = st.columns(2, gap="large")
    with left:
        with st.container(key="card_clock"):
            offset = svc.demo_day_offset()
            st.markdown("**Demonstration clock**")
            st.caption("Moves the application date forward one calendar day so that completed fever-free days, "
                       "missed checks and discharge eligibility can be demonstrated without waiting overnight. "
                       f"Current offset: +{offset} day(s). Fever threshold: {svc.fever_threshold():.1f} °C "
                       "(set by the Head Doctor).")
            if st.button("Advance to next day", icon=":material/fast_forward:"):
                act(lambda: svc.advance_demo_day(user()["username"]),
                    lambda n: f"Application date advanced. The demo clock is now +{n} day(s).")
    with right:
        with st.container(key="card_reset"):
            st.markdown("**Reset demonstration data**")
            st.caption("Deletes every record and reloads the sample dataset relative to today's real date. "
                       "The demo clock returns to the real date.")
            sure = st.checkbox("I understand all current data will be replaced.")
            if st.button("Reset demo data", disabled=not sure, icon=":material/restart_alt:"):
                try:
                    svc.reset_demo(user()["username"])
                except svc.WorkflowError as exc:
                    st.error(str(exc))
                else:
                    st.session_state.pop("current_patient", None)
                    flash("success", "Demo data has been reset to the sample dataset.")
                    st.rerun()
    ui.section("Audit log", "most recent 200 actions")
    table([{"Time": ui.fmt_dt(a["logged_at"]), "User": a["actor"], "Role": a["role"], "Action": a["action"],
            "Record": a["entity_id"] or "—", "Details": a["details"]} for a in svc.recent_audit()], height=420)


# ------------------------------------------------------------------- routing
PAGES = {
    "Nurse": [
        ("n_overview", "Overview", ":material/dashboard:", nurse_overview),
        ("n_rooms", "Room & Patient Queue", ":material/grid_view:", nurse_rooms),
        ("n_temp", "Temperature Entry", ":material/thermostat:", nurse_temperature),
        ("n_pending", "Pending Checks", ":material/pending_actions:", nurse_pending),
    ],
    "Doctor": [
        ("d_overview", "Overview", ":material/dashboard:", doctor_overview),
        ("d_queue", "Rounds Queue", ":material/format_list_numbered:", doctor_queue),
        ("d_profile", "Patient Profile", ":material/clinical_notes:", doctor_profile),
        ("d_visit", "Visit & Treatment", ":material/stethoscope:", doctor_visit),
        ("d_discharge", "Discharge & Outcomes", ":material/verified:", doctor_discharge),
        ("d_analytics", "Facility Analytics", ":material/monitoring:", doctor_analytics),
    ],
    "Admin": [
        ("a_overview", "Overview", ":material/dashboard:", admin_overview),
        ("a_register", "Patient Registration", ":material/person_add:", admin_register),
        ("a_rooms", "Room Management", ":material/meeting_room:", admin_rooms),
        ("a_discharge", "Discharge Queue", ":material/logout:", admin_discharge),
        ("a_performance", "Facility Performance", ":material/monitoring:", admin_performance),
        ("a_settings", "System Settings", ":material/settings:", admin_settings),
    ],
}


def sign_out():
    for key in list(st.session_state.keys()):
        del st.session_state[key]


def sidebar(pages, now):
    account = user()
    with st.sidebar:
        st.html('<div class="brand"><div class="brand-name">VITAL<span>IS</span></div>'
                '<div class="brand-tag">Precision in Care. Efficiency in Recovery.</div></div>')
        offset = svc.demo_day_offset()
        clock = f" · demo clock +{offset}d" if offset else ""
        st.html(f'<div class="user-card"><div class="user-name">{escape(account["full_name"])}</div>'
                f'<div class="user-role">{escape(account["title"])} · {account["role"]} portal</div>'
                f'<div class="user-time">{now.strftime("%a %d %b %Y · %H:%M")} IST{clock}</div></div>'
                '<div class="nav-label">Navigation</div>')
        for key, label, icon, _ in pages:
            st.button(label, key=f"nav_{key}", icon=icon, width="stretch", on_click=goto, args=(key,),
                      type="primary" if st.session_state["page"] == key else "secondary")
        st.html('<div class="nav-label" style="margin-top:1.2rem">Session</div>')
        st.button("Sign out", key="nav_signout", icon=":material/logout:", width="stretch", on_click=sign_out)


def main():
    _boot()
    ui.inject_css()
    if "user" not in st.session_state:
        login_screen()
        return
    pages = PAGES[user()["role"]]
    routes = {key: func for key, _, _, func in pages}
    if st.session_state.get("page") not in routes:  # role-based access: only this role's screens exist
        st.session_state["page"] = pages[0][0]
    now = svc.now()
    sidebar(pages, now)
    show_flash()
    routes[st.session_state["page"]](now)


main()
