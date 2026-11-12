"""Design system for VITALIS: theme CSS and reusable HTML components."""

from datetime import datetime
from html import escape

import streamlit as st

NAVY, TEAL = "#14283D", "#20BFA9"
RED, AMBER, GREEN, SLATE = "#D64545", "#D98A00", "#1E9E63", "#6B7A8C"

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;600&display=swap');
:root {
  --navy:#14283D; --navy-2:#1D3852; --teal:#20BFA9; --teal-d:#0E8F7E; --bg:#F4F6F9; --card:#FFFFFF;
  --line:#E3E8EF; --ink:#14283D; --muted:#6B7A8C;
  --red:#D64545; --red-bg:#FDEEEE; --amber:#B97400; --amber-bg:#FFF5DD;
  --green:#1E9E63; --green-bg:#E7F6EE; --blue:#2C6FBB; --blue-bg:#E9F1FB; --teal-bg:#E4F7F4;
}
html, body, .stApp, .stApp p, .stApp label, .stApp input, .stApp textarea, .stApp button, .stApp li {
  font-family:'Plus Jakarta Sans', 'Segoe UI', sans-serif; }
.stApp { background:var(--bg); color:var(--ink); }
header[data-testid="stHeader"] { background:transparent; }
.block-container { padding-top:2.2rem; padding-bottom:3rem; max-width:1440px; }
h1, h2, h3, h4 { color:var(--ink); letter-spacing:-0.01em; }

/* Sidebar */
[data-testid="stSidebar"] { background:var(--navy); border-right:none; }
[data-testid="stSidebar"] * { color:#DCE6F0; }
[data-testid="stSidebar"] .stButton button {
  background:transparent; border:1px solid transparent; color:#C9D6E3; justify-content:flex-start;
  text-align:left; font-weight:500; padding:0.5rem 0.8rem; border-radius:10px; box-shadow:none; }
[data-testid="stSidebar"] .stButton button > div, [data-testid="stSidebar"] .stButton button > div > span {
  justify-content:flex-start; width:100%; }
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap:0.3rem; }
[data-testid="stSidebar"] .stButton button:hover { background:rgba(255,255,255,0.07); color:#FFFFFF; border-color:transparent; }
[data-testid="stSidebar"] .stButton button[kind="primary"] {
  background:rgba(32,191,169,0.16); color:#FFFFFF; border-color:rgba(32,191,169,0.45); font-weight:600; }
[data-testid="stSidebar"] .stButton button[kind="primary"] [data-testid="stIconMaterial"] { color:var(--teal); }
.brand { padding:0.2rem 0.3rem 1rem; }
.brand-name { font-size:1.55rem; font-weight:800; letter-spacing:0.14em; color:#FFFFFF; }
.brand-name span { color:var(--teal); }
.brand-tag { font-size:0.72rem; color:#9FB2C6; margin-top:0.15rem; line-height:1.4; }
.user-card { background:rgba(255,255,255,0.06); border:1px solid rgba(255,255,255,0.09); border-radius:12px;
  padding:0.8rem 0.9rem; margin:0.2rem 0 1rem; }
.user-name { font-weight:700; color:#FFFFFF; font-size:0.95rem; }
.user-role { font-size:0.78rem; color:var(--teal); font-weight:600; margin-top:0.1rem; }
.user-time { font-size:0.74rem; color:#9FB2C6; margin-top:0.45rem; }
.nav-label { font-size:0.68rem; letter-spacing:0.12em; text-transform:uppercase; color:#7F94AA; margin:0.2rem 0.3rem 0.3rem; }

/* Buttons and inputs in the main area */
[data-testid="stMain"] .stButton button, [data-testid="stMain"] .stFormSubmitButton button {
  border-radius:10px; font-weight:600; border:1px solid var(--line); color:var(--ink); background:#FFFFFF; }
[data-testid="stMain"] .stButton button:hover, [data-testid="stMain"] .stFormSubmitButton button:hover {
  border-color:var(--teal); color:var(--teal-d); }
[data-testid="stMain"] .stButton button[kind="primary"], [data-testid="stMain"] .stFormSubmitButton button[kind="primaryFormSubmit"] {
  background:var(--navy); border-color:var(--navy); color:#FFFFFF; }
[data-testid="stMain"] .stButton button[kind="primary"]:hover, [data-testid="stMain"] .stFormSubmitButton button[kind="primaryFormSubmit"]:hover {
  background:var(--teal-d); border-color:var(--teal-d); color:#FFFFFF; }
[data-testid="stMain"] button:disabled { opacity:0.5; }
[data-testid="stForm"], [data-testid="stExpander"] details {
  background:var(--card); border:1px solid var(--line); border-radius:14px; box-shadow:0 1px 2px rgba(20,40,61,0.04); }
[data-testid="stForm"] { padding:1.2rem 1.3rem; }
[data-testid="stVerticalBlockBorderWrapper"], .stVerticalBlock[class*="st-key-card"] {
  background:var(--card); border-radius:14px; }
div[class*="st-key-card"] { background:var(--card); border:1px solid var(--line); border-radius:14px;
  padding:1rem 1.15rem; box-shadow:0 1px 2px rgba(20,40,61,0.04); }
div[class*="st-key-row"] { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:0.65rem 0.95rem; }
[data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:12px; overflow:hidden; }
[data-testid="stAlert"] { border-radius:12px; }

div[class*="st-key-card_w"] [data-testid="stForm"] { border:none; padding:0; box-shadow:none; }
/* Page header */
.page-head { display:flex; justify-content:space-between; align-items:flex-end; gap:1rem; flex-wrap:wrap;
  margin-bottom:1.1rem; padding-bottom:0.9rem; border-bottom:1px solid var(--line); }
.page-kicker { font-size:0.7rem; font-weight:700; letter-spacing:0.14em; text-transform:uppercase; color:var(--teal-d); }
.page-title { font-size:1.7rem; font-weight:800; color:var(--ink); line-height:1.2; margin-top:0.15rem; }
.page-sub { font-size:0.92rem; color:var(--muted); margin-top:0.2rem; }
.page-date { font-size:0.82rem; color:var(--muted); background:var(--card); border:1px solid var(--line);
  border-radius:999px; padding:0.35rem 0.85rem; white-space:nowrap; }
.section-title { font-size:1.02rem; font-weight:700; color:var(--ink); margin:1.3rem 0 0.6rem; }
.section-title small { font-weight:500; color:var(--muted); font-size:0.82rem; margin-left:0.4rem; }

/* KPI cards */
.kpi-grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:0.85rem; margin-bottom:0.4rem; }
.kpi { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:1rem 1.1rem;
  box-shadow:0 1px 2px rgba(20,40,61,0.04); border-top:3px solid var(--navy); min-width:0; }
.kpi.teal { border-top-color:var(--teal); } .kpi.red { border-top-color:var(--red); }
.kpi.amber { border-top-color:#E0A21B; } .kpi.green { border-top-color:var(--green); }
.kpi-label { font-size:0.74rem; font-weight:600; letter-spacing:0.05em; text-transform:uppercase; color:var(--muted); }
.kpi-value { font-size:2rem; font-weight:800; color:var(--ink); line-height:1.15; margin-top:0.3rem; font-variant-numeric:tabular-nums; }
.kpi-value small { font-size:1rem; font-weight:600; color:var(--muted); }
.kpi-sub { font-size:0.8rem; color:var(--muted); margin-top:0.15rem; }

/* Chips */
.chip { display:inline-block; font-size:0.72rem; font-weight:700; padding:0.18rem 0.6rem; border-radius:999px;
  white-space:nowrap; line-height:1.5; }
.chip.red { background:var(--red-bg); color:var(--red); } .chip.amber { background:var(--amber-bg); color:var(--amber); }
.chip.green { background:var(--green-bg); color:var(--green); } .chip.blue { background:var(--blue-bg); color:var(--blue); }
.chip.teal { background:var(--teal-bg); color:var(--teal-d); } .chip.grey { background:#EEF1F5; color:var(--muted); }
.chip.navy { background:var(--navy); color:#FFFFFF; }

/* Room grid */
.legend { display:flex; gap:0.5rem; flex-wrap:wrap; margin:0.2rem 0 0.8rem; align-items:center; font-size:0.8rem; color:var(--muted); }
.room-floor { font-size:0.76rem; font-weight:700; letter-spacing:0.1em; text-transform:uppercase; color:var(--muted); margin:1rem 0 0.5rem; }
.room-grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(158px, 1fr)); gap:0.6rem; }
.room { background:var(--card); border:1px solid var(--line); border-left:4px solid var(--line); border-radius:12px;
  padding:0.6rem 0.7rem; min-height:118px; display:flex; flex-direction:column; gap:0.12rem; min-width:0; }
.room.t-amber { border-left-color:#E0A21B; } .room.t-blue { border-left-color:var(--blue); }
.room.t-green { border-left-color:var(--green); } .room.t-navy { border-left-color:var(--navy); }
.room.t-empty { background:repeating-linear-gradient(135deg,#F8FAFC,#F8FAFC 8px,#F1F4F8 8px,#F1F4F8 16px);
  border-style:dashed; border-left-style:dashed; color:var(--muted); }
.room.t-clean { background:var(--amber-bg); border-left-color:#E0A21B; }
.room-top { display:flex; justify-content:space-between; align-items:center; }
.room-no { font-family:'JetBrains Mono', monospace; font-weight:600; font-size:0.95rem; color:var(--ink); }
.room-name { font-weight:600; font-size:0.84rem; color:var(--ink); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.room-id { font-family:'JetBrains Mono', monospace; font-size:0.7rem; color:var(--muted); }
.room-temp { font-size:0.72rem; color:var(--muted); margin-bottom:0.25rem; }
.room-val { font-size:0.82rem; font-weight:800; color:var(--green); white-space:nowrap; font-variant-numeric:tabular-nums; }
.room-val.fever { color:var(--red); }
.room-foot { margin-top:auto; }
.room-empty-label { font-size:0.8rem; margin-top:auto; font-weight:600; }

/* Patient rows and cards */
.prow { display:flex; align-items:center; gap:0.9rem; flex-wrap:wrap; }
.prow-room { font-family:'JetBrains Mono', monospace; font-weight:600; background:var(--navy); color:#FFFFFF;
  border-radius:8px; padding:0.3rem 0.55rem; font-size:0.85rem; }
.prow-main { min-width:150px; flex:1; }
.prow-name { font-weight:700; color:var(--ink); font-size:0.95rem; }
.prow-meta { font-size:0.78rem; color:var(--muted); }
.prow-meta .mono, .mono { font-family:'JetBrains Mono', monospace; }
.prow-temp { font-weight:800; font-size:1.05rem; font-variant-numeric:tabular-nums; min-width:70px; text-align:right; }
.prow-temp.fever { color:var(--red); } .prow-temp.ok { color:var(--green); } .prow-temp.none { color:var(--muted); font-weight:600; font-size:0.85rem; }
.pcard { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:1.1rem 1.25rem;
  box-shadow:0 1px 2px rgba(20,40,61,0.04); margin-bottom:0.8rem; }
.pcard-head { display:flex; justify-content:space-between; align-items:flex-start; gap:1rem; flex-wrap:wrap; }
.pcard-name { font-size:1.25rem; font-weight:800; color:var(--ink); }
.pcard-grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:0.8rem 1.2rem; margin-top:0.9rem; }
.pcard-k { font-size:0.7rem; font-weight:600; letter-spacing:0.06em; text-transform:uppercase; color:var(--muted); }
.pcard-v { font-size:0.95rem; font-weight:600; color:var(--ink); margin-top:0.1rem; }
.banner { border-radius:14px; padding:1rem 1.2rem; margin-bottom:0.9rem; border:1px solid; }
.banner-title { font-weight:800; font-size:1.05rem; } .banner-text { font-size:0.88rem; margin-top:0.2rem; }
.banner.green { background:var(--green-bg); border-color:#BFE5D0; color:#136B43; }
.banner.red { background:var(--red-bg); border-color:#F3C2C2; color:#A32E2E; }
.banner.amber { background:var(--amber-bg); border-color:#F2DDA6; color:#7A4E00; }
.banner.blue { background:var(--blue-bg); border-color:#C7DBF3; color:#1F4F87; }
.days { display:flex; gap:0.5rem; flex-wrap:wrap; margin-top:0.6rem; }
.day { background:#FFFFFF; border:1px solid #BFE5D0; border-radius:10px; padding:0.35rem 0.7rem; font-size:0.82rem; font-weight:700; color:#136B43; }
.day.todo { border-style:dashed; border-color:var(--line); color:var(--muted); font-weight:600; }
.progress { height:10px; background:#E6EBF1; border-radius:999px; overflow:hidden; margin-top:0.5rem; }
.progress > div { height:100%; background:var(--teal); border-radius:999px; }
.empty { background:var(--card); border:1px dashed var(--line); border-radius:12px; padding:1.1rem; color:var(--muted); font-size:0.9rem; text-align:center; }

/* Login */
.login-brand { background:linear-gradient(160deg, #14283D 0%, #1D3852 70%, #0E8F7E 160%); border-radius:20px; padding:2.6rem 2.4rem;
  color:#FFFFFF; min-height:520px; display:flex; flex-direction:column; justify-content:space-between; }
.login-logo { font-size:2.6rem; font-weight:800; letter-spacing:0.16em; } .login-logo span { color:var(--teal); }
.login-tag { font-size:1.05rem; color:#BFD0E0; margin-top:0.5rem; }
.login-system { font-size:0.74rem; letter-spacing:0.14em; text-transform:uppercase; color:var(--teal); font-weight:700; margin-bottom:0.8rem; }
.login-points { display:grid; gap:0.9rem; margin-top:2rem; }
.login-point { border-left:3px solid var(--teal); padding-left:0.9rem; }
.login-point b { display:block; font-size:0.95rem; } .login-point span { font-size:0.83rem; color:#BFD0E0; }
.login-foot { font-size:0.76rem; color:#8FA5BB; margin-top:2rem; }
.login-title { font-size:1.5rem; font-weight:800; color:var(--ink); margin-top:1.2rem; }
.login-sub { font-size:0.9rem; color:var(--muted); margin-bottom:0.6rem; }
.cred { font-family:'JetBrains Mono', monospace; font-size:0.82rem; }
@media (max-width: 900px) { .login-brand { min-height:auto; } .page-title { font-size:1.4rem; } }
</style>
"""

TONE = {
    "Needs Temp Check": "amber", "Temperature Recorded": "teal", "Ready for Doctor": "blue",
    "Doctor Visit Completed": "green", "Awaiting Nurse": "amber", "Critical fever": "red",
    "Persistent fever": "red", "Fever": "red", "Recovering": "green", "Stable": "grey",
    "Occupied": "navy", "Available": "green", "Pending Cleaning": "amber",
    "Discharge Approved": "teal", "Admitted": "grey", "Eligible for Discharge": "green",
}


def inject_css():
    st.markdown(CSS, unsafe_allow_html=True)


def fmt_dt(value, with_date=True):
    if not value:
        return "—"
    if isinstance(value, str):
        value = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    return value.strftime("%d %b %Y, %H:%M" if with_date else "%H:%M")


def fmt_date(value):
    if not value:
        return "—"
    if isinstance(value, str):
        value = datetime.strptime(value[:10], "%Y-%m-%d").date()
    return value.strftime("%d %b %Y")


def chip(text, tone=None):
    return f'<span class="chip {tone or TONE.get(text, "grey")}">{escape(str(text))}</span>'


def page_header(kicker, title, subtitle, now):
    st.html(
        f'<div class="page-head"><div><div class="page-kicker">{escape(kicker)}</div>'
        f'<div class="page-title">{escape(title)}</div><div class="page-sub">{escape(subtitle)}</div></div>'
        f'<div class="page-date">{now.strftime("%A, %d %B %Y · %H:%M")} IST</div></div>')


def section(title, note=""):
    st.html(f'<div class="section-title">{escape(title)}<small>{escape(note)}</small></div>')


def kpis(items):
    """items: (label, value, sub-text, tone)."""
    cards = "".join(
        f'<div class="kpi {tone}"><div class="kpi-label">{escape(label)}</div>'
        f'<div class="kpi-value">{value}</div><div class="kpi-sub">{escape(sub)}</div></div>'
        for label, value, sub, tone in items)
    st.html(f'<div class="kpi-grid">{cards}</div>')


def banner(tone, title, text="", extra_html=""):
    st.html(f'<div class="banner {tone}"><div class="banner-title">{escape(title)}</div>'
            f'<div class="banner-text">{escape(text)}</div>{extra_html}</div>')


def empty(text):
    st.html(f'<div class="empty">{escape(text)}</div>')


def legend(items):
    st.html('<div class="legend">' + "".join(chip(t) for t in items) + "</div>")


def temp_html(p):
    if p["today_temp"] is None:
        return '<div class="prow-temp none">No reading</div>'
    return f'<div class="prow-temp {"fever" if p["today_fever"] else "ok"}">{p["today_temp"]:.1f} °C</div>'


def patient_row_html(p, chips_html=""):
    return (
        f'<div class="prow"><div class="prow-room">{escape(p["room_number"])}</div>'
        f'<div class="prow-main"><div class="prow-name">{escape(p["full_name"])}</div>'
        f'<div class="prow-meta"><span class="mono">{p["patient_id"]}</span> · {p["age"]} y · {escape(p["gender"])} · '
        f'day {p["days_admitted"] + 1}</div></div><div>{chips_html}</div>{temp_html(p)}</div>')


def nurse_room_grid(rooms, patients_by_room):
    """All rooms for the nursing view: patient, ID, temperature status and workflow status."""
    html, floor = [], None
    for r in rooms:
        if r["floor"] != floor:
            if floor is not None:
                html.append("</div>")
            floor = r["floor"]
            html.append(f'<div class="room-floor">Floor {floor}</div><div class="room-grid">')
        p = patients_by_room.get(r["room_id"])
        if p is None:
            label = "Pending cleaning" if r["status"] == "Pending Cleaning" else "Empty"
            tone = "t-clean" if r["status"] == "Pending Cleaning" else "t-empty"
            html.append(f'<div class="room {tone}"><div class="room-no">{r["room_number"]}</div>'
                        f'<div class="room-empty-label">{label}</div></div>')
            continue
        tone = {"Needs Temp Check": "t-amber", "Ready for Doctor": "t-blue"}.get(p["workflow"], "t-green")
        if p["today_temp"] is None:
            temp_line, value = "Temperature not recorded", ""
        else:
            temp_line = "Temperature Recorded"
            value = f'<div class="room-val {"fever" if p["today_fever"] else ""}">{p["today_temp"]:.1f} °C</div>'
        html.append(
            f'<div class="room {tone}"><div class="room-top"><div class="room-no">{r["room_number"]}</div>{value}</div>'
            f'<div class="room-name" title="{escape(p["full_name"])}">{escape(p["full_name"])}</div>'
            f'<div class="room-id">{p["patient_id"]}</div><div class="room-temp">{temp_line}</div>'
            f'<div class="room-foot">{chip(p["workflow"])}</div></div>')
    html.append("</div>")
    st.html("".join(html))


def admin_room_grid(rooms):
    html, floor = [], None
    for r in rooms:
        if r["floor"] != floor:
            if floor is not None:
                html.append("</div>")
            floor = r["floor"]
            html.append(f'<div class="room-floor">Floor {floor}</div><div class="room-grid">')
        tone = {"Occupied": "t-navy", "Available": "t-empty", "Pending Cleaning": "t-clean"}[r["status"]]
        body = ""
        if r["status"] == "Occupied":
            body = (f'<div class="room-name">{escape(r["full_name"] or "")}</div>'
                    f'<div class="room-id">{r["current_patient_id"]}</div>')
        html.append(f'<div class="room {tone}" style="min-height:96px"><div class="room-no">{r["room_number"]}</div>'
                    f'{body}<div class="room-foot">{chip(r["status"])}</div></div>')
    html.append("</div>")
    st.html("".join(html))
