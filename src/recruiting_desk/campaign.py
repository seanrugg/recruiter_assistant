"""
The campaign's own data: athletes, target programs, what was sent and when.

Plain JSON files under the app's data folder . No database, because this has to be
readable and editable by a parent without tooling, and portable between
machines by copying a folder.

GameChanger owns the stats and the schedule. This file owns everything
GameChanger does not know: academics, the target list, the fit rationale, and
the record of what actually went out.
"""

import json
import pathlib
import datetime
import os

from .paths import data_dir

HOME = data_dir()


def _load(name, default):
    p = HOME / name
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        raise RuntimeError(f"{p} is not valid JSON. Fix or remove it before continuing.")


def _save(name, data):
    HOME.mkdir(parents=True, exist_ok=True)
    p = HOME / name
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tmp.replace(p)
    return str(p)


# -- athletes ------------------------------------------------------------

def athletes():
    return _load("athletes.json", {})


def athlete(athlete_id):
    a = athletes().get(athlete_id)
    if not a:
        known = ", ".join(athletes().keys()) or "none yet"
        raise KeyError(f"No athlete '{athlete_id}'. Known: {known}.")
    return a


def save_athlete(athlete_id, record):
    data = athletes()
    existing = data.get(athlete_id, {})
    existing.update(record)
    existing["id"] = athlete_id
    data[athlete_id] = existing
    _save("athletes.json", data)
    return existing


# -- target programs -----------------------------------------------------

def programs():
    return _load("programs.json", {})


def save_program(program_id, record):
    data = programs()
    existing = data.get(program_id, {})
    existing.update(record)
    existing["id"] = program_id
    data[program_id] = existing
    _save("programs.json", data)
    return existing


def programs_for(athlete_id):
    return [p for p in programs().values() if p.get("athlete_id") == athlete_id]


# -- outreach log --------------------------------------------------------

def outreach():
    return _load("outreach.json", [])


def log_outreach(entry):
    log = outreach()
    entry["logged_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    log.append(entry)
    _save("outreach.json", log)
    return entry


def history_for(program_id):
    return [e for e in outreach() if e.get("program_id") == program_id]


def follow_ups_due(athlete_id, as_of=None):
    as_of = as_of or datetime.date.today().isoformat()
    due = []
    for p in programs_for(athlete_id):
        sent = [e for e in history_for(p["id"]) if e.get("action") == "sent"]
        if not sent:
            continue
        replied = [e for e in history_for(p["id"]) if e.get("action") == "replied"]
        if replied:
            continue
        last = max(e["date"] for e in sent if e.get("date"))
        nudge = (datetime.date.fromisoformat(last) + datetime.timedelta(days=14)).isoformat()
        if nudge <= as_of:
            due.append({"program_id": p["id"], "school": p.get("school"), "last_sent": last, "due": nudge})
    return sorted(due, key=lambda d: d["due"])


# -- contact windows -----------------------------------------------------

DEFAULT_RULES = {
    "verified_on": "",
    "verified_by": "",
    "divisions": {
        "I":    {"label": "NCAA Division I",   "month_day": "09-01", "years_before_grad": 2,
                 "note": "Coaches may begin recruiting communication Sept 1 of junior year."},
        "II":   {"label": "NCAA Division II",  "month_day": "06-15", "years_before_grad": 2,
                 "note": "Coaches may begin recruiting communication June 15 after sophomore year."},
        "III":  {"label": "NCAA Division III", "month_day": "", "years_before_grad": 0, "note": "No date restriction."},
        "NAIA": {"label": "NAIA",              "month_day": "", "years_before_grad": 0, "note": "No date restriction."},
        "JUCO": {"label": "Junior college",    "month_day": "", "years_before_grad": 0, "note": "No date restriction."},
    },
}


def rules(overrides=None):
    stored = _load("contact_rules.json", None)
    if stored:
        return stored
    r = dict(DEFAULT_RULES)
    if overrides:
        r.update(overrides)
    return r


def save_rules(r):
    return _save("contact_rules.json", r)


def contact_window(division, grad_year, as_of=None):
    """When may a coach at this division begin recruiting communication?"""
    r = rules()
    div = r["divisions"].get(str(division))
    if not div:
        return {"known": False, "reason": f"No rule on file for division '{division}'."}
    if not div.get("month_day"):
        return {"known": True, "open": True, "date": None, "note": div["note"],
                "verified_on": r.get("verified_on", ""), "division": div["label"]}
    try:
        grad = int(grad_year)
    except (TypeError, ValueError):
        return {"known": False, "reason": "Graduation year missing, so the date cannot be computed."}
    year = grad - int(div.get("years_before_grad", 0))
    opens = datetime.date.fromisoformat(f"{year}-{div['month_day']}")
    today = datetime.date.fromisoformat(as_of) if as_of else datetime.date.today()
    return {
        "known": True,
        "open": today >= opens,
        "date": opens.isoformat(),
        "division": div["label"],
        "note": div["note"],
        "verified_on": r.get("verified_on", ""),
        "caveat": ("An athlete may write to a coach at any time. What this date governs is when "
                   "the coach may answer. Verify against current NCAA rules before relying on it."),
    }
