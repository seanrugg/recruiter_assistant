"""
Writing an email where the facts cannot be wrong.

The first version asked a model to write the whole email from a pile of data,
and trusted it to copy numbers faithfully. A small local model mostly did --
but it dropped the context that made the numbers honest ("26 innings" without
"junior varsity"), invented a reason for choosing the school, left out the
profile links, and never addressed the coach by name. Getting the numbers right
was luck, not design.

So the work is split:

  THE APP writes every fact -- the coach's name, each stat with its season,
  team and level, the profile links the player ticked, the schedule, the
  signature. These come straight from the player's record.

  THE MODEL writes only a few short sentences of voice -- an opening, a reason
  for the school built only from facts it is given, and an ask. Each is
  rejected if it contains a single digit, retried once, and replaced with a
  standard sentence if it fails again.

Every email type is a template the family can read and edit. The exact prompt
sent to the model is returned alongside the draft, so nothing is hidden.

Without a model at all, the templates still produce a complete, correct email
from the standard sentences.
"""

import re
import json
import string
import datetime

from . import llm
from . import campaign

# --------------------------------------------------------------------------
# Templates
#
# {placeholders} are filled by the app from the record.
# [[slot | instruction]] marks a sentence the model writes. Instructions are
# kept free of digits: the model echoes what it is shown.
# --------------------------------------------------------------------------

DEFAULT_TEMPLATES = {
    "intro": {
        "label": "First email",
        "subject": "{name} | {grad_year} {positions} | {team}",
        "body": """{greeting}

[[opening | One or two sentences: who the player is and that they are interested in playing {sport} at {school}.]]

[[why_school | One sentence on why {school}, built ONLY from the school facts and the player's own reason. If there are none, return an empty string.]]

{window_note}

{stats}

{links}

{schedule}

[[ask | One sentence asking the coach to watch the player's video or come see a game, and welcoming a reply.]]

Thank you,
{signature}""",
    },
    "coming": {
        "label": "Coming up",
        "subject": "{name} | {grad_year} {positions} | Playing at {event_name}",
        "body": """{greeting}

[[opening | One or two sentences saying the player will be playing at {event_name} and would love for the coach to see them play.]]

{event_details}
{jersey_line}

{stats}

{links}

[[ask | One sentence inviting the coach to stop by, and welcoming a reply.]]

Thank you,
{signature}""",
    },
    "follow": {
        "label": "Follow up",
        "subject": "Following up | {name} | {grad_year} {positions}",
        "body": """{greeting}

[[opening | One or two sentences following up on an earlier email to the coach. Friendly and brief. Not apologetic, not impatient.]]

{stats}

{schedule}

{links}

[[ask | One sentence saying the player is still very interested in {school} and would welcome any feedback.]]

Thank you,
{signature}""",
    },
    "thanks": {
        "label": "Thank you",
        "subject": "Thank you | {name} | {grad_year} {positions}",
        "body": """{greeting}

[[opening | One or two sentences thanking the coach for coming out to watch the player play{event_phrase}. Sincere and brief. Do not describe how the player performed.]]

{schedule}

{links}

[[ask | One short sentence welcoming any feedback.]]

Thank you,
{signature}""",
    },
}

# Standard sentences, used whenever the model is unavailable or its sentence is
# rejected. They are deliberately plain; they are always true.
STANDARD = {
    "opening": {
        "intro": "My name is {first_name}, a {grad_year} {sport} player ({positions}), and I'm very interested in playing at {school}.",
        "coming": "I wanted to let you know where I'll be playing next, in case you're able to come watch.",
        "follow": "I wanted to follow up on my earlier email and share where I'll be playing next.",
        "thanks": "Thank you for coming out to watch me play{event_phrase}. It meant a lot to have you there.",
    },
    "why_school": {"*": "{fit}"},
    "ask": {
        "intro": "I'd love for you to take a look at my video, and I'd welcome any feedback.",
        "coming": "I'd love the chance to play in front of you.",
        "follow": "I'm still very interested in {school}, and I'd be grateful for any feedback.",
        "thanks": "I'd welcome any feedback you have.",
    },
}

SLOT_RE = re.compile(r"\[\[\s*([a-z_]+)\s*\|\s*(.*?)\s*\]\]", re.S)
CLAIM_WORDS = re.compile(
    r"\b(led|lead the|best|record|all[- ]state|all[- ]conference|all[- ]district|mvp|honou?r|award|"
    r"champion|ranked|top \w+|undefeated|perfect game|no[- ]hitter|scholarship)\b", re.I)


# --------------------------------------------------------------------------
# Template storage: defaults, overridden by the family's own edits.
# --------------------------------------------------------------------------

def _store():
    return campaign.HOME / "templates.json"


def load_templates():
    saved = {}
    if _store().exists():
        try:
            saved = json.loads(_store().read_text())
        except json.JSONDecodeError:
            saved = {}
    out = {}
    for kind, d in DEFAULT_TEMPLATES.items():
        s = saved.get(kind) or {}
        out[kind] = {
            "label": d["label"],
            "subject": s.get("subject") or d["subject"],
            "body": s.get("body") or d["body"],
            "is_default": not s,
            "default_subject": d["subject"],
            "default_body": d["body"],
        }
    return out


def save_template(kind, subject, body):
    if kind not in DEFAULT_TEMPLATES:
        raise KeyError(kind)
    saved = {}
    if _store().exists():
        try:
            saved = json.loads(_store().read_text())
        except json.JSONDecodeError:
            saved = {}
    saved[kind] = {"subject": subject, "body": body}
    campaign._save("templates.json", saved)
    return load_templates()[kind]


def reset_template(kind):
    if not _store().exists():
        return load_templates()[kind]
    saved = json.loads(_store().read_text())
    saved.pop(kind, None)
    campaign._save("templates.json", saved)
    return load_templates()[kind]


# --------------------------------------------------------------------------
# The facts, written by the app
# --------------------------------------------------------------------------

def _last_name(full):
    parts = (full or "").strip().split()
    return parts[-1] if parts else ""


def greeting(coaches):
    """'Coach Ikenberry,' or 'Coach Ikenberry and Coach Spataro,' -- never 'Dear Sir'."""
    names = [f"Coach {_last_name(c)}" for c in coaches if _last_name(c)]
    if not names:
        return "Coach,"
    if len(names) == 1:
        return names[0] + ","
    return ", ".join(names[:-1]) + " and " + names[-1] + ","


def stats_block(stats):
    """Grouped by season and team, so every number keeps its context."""
    groups, order = {}, []
    for s in stats or []:
        src = (s.get("source") or "").replace("GameChanger \u00b7 ", "").replace(" \u00b7 ", ", ").strip()
        if src not in groups:
            groups[src] = []
            order.append(src)
        groups[src].append(f"{s.get('value', '')} {s.get('label', '')}".strip())
    if not order:
        return ""
    lines = [f"{src or 'Stats'}: " + ", ".join(groups[src]) for src in order]
    return "Recent numbers:\n" + "\n".join(lines)


def links_block(athlete):
    rows = [f"{l.get('label') or 'Profile'}: {l['url']}"
            for l in athlete.get("links") or [] if l.get("url") and l.get("include") is not False]
    rows += [f"{s.get('platform')}: {s.get('handle')}"
             for s in athlete.get("socials") or [] if s.get("include") and s.get("handle")]
    return ("Video and stats:\n" + "\n".join(rows)) if rows else ""


def _event_line(e):
    bits = [e.get("date", ""), e.get("name", "")]
    line = " \u2013 ".join(b for b in bits if b)
    if e.get("location"):
        line += f", {e['location']}"
    return line


def schedule_block(events):
    rows = [_event_line(e) for e in events or [] if e.get("name")]
    return ("Where to see me next:\n" + "\n".join(rows)) if rows else ""


def signature(a):
    lines = [a.get("name", "")]
    head = " | ".join(x for x in [f"Class of {a['gradYear']}" if a.get("gradYear") else "",
                                  a.get("positions", "")] if x)
    if head:
        lines.append(head)
    teams = " | ".join(x for x in [a.get("school", ""), a.get("club", "")] if x)
    if teams:
        lines.append(teams)
    contact = " | ".join(x for x in [a.get("email", ""), a.get("phone", "")] if x)
    if contact:
        lines.append(contact)
    if a.get("ncaaId"):
        lines.append(f"NCAA Eligibility Center ID: {a['ncaaId']}")
    ref = ", ".join(x for x in [a.get("refName", ""), a.get("refPhone", ""), a.get("refEmail", "")] if x)
    if ref:
        lines.append(f"Reference: {ref}")
    return "\n".join(l for l in lines if l)


def _window_note(a, target):
    w = campaign.contact_window(target.get("division", ""), a.get("gradYear", ""))
    if not w.get("known") or w.get("open") or not w.get("date"):
        return ""
    d = datetime.date.fromisoformat(w["date"])
    when = f"{d.strftime('%B')} {d.day}, {d.year}"      # not %-d: Windows doesn't support it
    return f"I know NCAA rules mean you can't reply to my class until {when} \u2014 I wanted to introduce myself now."


def facts(a, target, event=None, coaches=None):
    """Every deterministic value a template can use."""
    coaches = coaches if coaches is not None else [target.get("coachName", "")]
    positions = a.get("positions", "") or ""
    team = a.get("club") or a.get("school") or ""
    ev = event or {}
    return {
        "name": a.get("name", ""),
        "first_name": (a.get("name", "") or "").split(" ")[0],
        "grad_year": a.get("gradYear", ""),
        "positions": positions,
        "positions_lower": positions.lower() if positions else "player",
        "team": team,
        "sport": a.get("sport", "softball"),
        "school": target.get("school", ""),
        "greeting": greeting(coaches),
        "stats": stats_block(a.get("stats")),
        "links": links_block(a),
        "schedule": schedule_block(a.get("events")),
        "signature": signature(a),
        "window_note": _window_note(a, target),
        "event_name": ev.get("name", "my next tournament"),
        "event_details": _event_line(ev) if ev else "",
        "event_phrase": f" at {ev['name']}" if ev.get("name") else "",
        "jersey_line": f"I'll be wearing #{a['jersey']}." if a.get("jersey") else "",
        "fit": target.get("fit", "") or "",
    }


class _Blank(string.Formatter):
    """Unknown {names} in an edited template render empty instead of crashing."""

    def get_value(self, key, args, kwargs):
        return kwargs.get(key, "") if isinstance(key, str) else super().get_value(key, args, kwargs)


def fill(text, values):
    try:
        return _Blank().format(text, **values)
    except (ValueError, IndexError):
        return text  # a stray brace in an edited template: leave it for the person to see


# --------------------------------------------------------------------------
# The voice, written by the model
# --------------------------------------------------------------------------

def school_facts(target):
    out = []
    for k, label in (("division", "Division"), ("conference", "Conference"), ("nickname", "Team name"),
                     ("location", "Location")):
        v = (target.get(k) or "").strip()
        if v and not re.search(r"\d", v):
            out.append(f"{label}: {'Division ' + v if k == 'division' and not v.lower().startswith('div') else v}")
    for f in target.get("facts") or []:
        if f and not re.search(r"\d", f):
            out.append(f)
    return out


def build_prompt(kind, a, target, slots, values, retry_note=""):
    pron = a.get("pronouns") or ""
    sport = a.get("sport", "softball")
    sf = school_facts(target)
    reason = (target.get("fit") or "").strip()
    lines = [
        f"You are helping a high school {sport} player write a few short sentences of an email to a college coach.",
        "The app writes every fact itself: statistics, links, dates, the schedule, the greeting and the signature.",
        "You write ONLY the sentences listed at the end, in the player's own voice.",
        "",
        "RULES",
        "- Never write a number or digit of any kind: no statistics, scores, dates, years, heights, weights, grades or jersey numbers.",
        "- Never claim an honor, award, ranking, record or achievement.",
        "- Never describe how the player performed. The app shows the numbers.",
        "- Never invent a reason for choosing the school. Use only the school facts and the player's reason below.",
        "- Do not greet the coach and do not sign off. The app adds both.",
        "- Plain, warm and direct. Short sentences. It should sound like a teenager wrote it, not a parent or a brochure.",
        ("- Refer to the player using " + pron + " pronouns, or write in the first person as the player."
         if pron else "- Write in the first person, as the player."),
    ]
    if retry_note:
        lines += ["", "YOUR LAST ANSWER WAS REJECTED: " + retry_note]
    lines += [
        "",
        "THE PLAYER",
        f"First name: {values['first_name']}",
        f"Sport: {sport}",
        f"Positions: {re.sub(r'[0-9]', '', a.get('positions', '')).strip() or 'not given'}",
        f"High school: {re.sub(r'[0-9]', '', a.get('school', '')).strip() or 'not given'}",
        "",
        "THE SCHOOL",
        f"Name: {target.get('school', '')}",
        *(sf or ["No other school facts given."]),
        f"The player's own reason for this school: {reason if reason and not re.search(r'[0-9]', reason) else 'none given'}",
        "",
        "HOW THE PLAYER WRITES (match this voice)",
        (a.get("voice") or "No sample given. Write plainly, in short sentences.")[:1500],
        "",
        "WRITE THESE",
    ]
    for name, instruction in slots:
        lines.append(f'- "{name}": {fill(instruction, values)}')
    lines += ["", "Reply with only a JSON object whose keys are exactly: "
              + ", ".join(f'"{n}"' for n, _ in slots) + ". Each value is a string."]
    return "\n".join(lines)


def check_slot(name, text):
    """Returns (clean_text, problem). A problem means the sentence is not used."""
    t = re.sub(r"<think>.*?</think>", "", str(text or ""), flags=re.S).strip().strip('"').strip()
    t = re.sub(r"^(dear\s+)?coach\b[^,\n]*,\s*", "", t, flags=re.I)          # model added a greeting anyway
    t = re.sub(r"\s*(thank you|thanks|sincerely|best)[,!.]?\s*$", "", t, flags=re.I) if name == "ask" and len(t) > 40 else t
    if re.search(r"\d", t):
        return t, "contains a number"
    if len(t) > 500:
        return t, "too long"
    return t, ""


def standard_sentence(kind, name, values):
    table = STANDARD.get(name, {})
    s = table.get(kind) or table.get("*") or ""
    return fill(s, values).strip()


def compose(kind, athlete, target, event=None, coaches=None, template=None, use_model=True):
    templates = load_templates()
    if kind not in templates:
        raise KeyError(f"No email type '{kind}'.")
    tpl = template or templates[kind]
    values = facts(athlete, target, event, coaches)
    slots = [(m.group(1), m.group(2)) for m in SLOT_RE.finditer(tpl["body"])]

    written, notes, prompt, provider = {}, [], "", None
    if use_model and slots:
        prompt = build_prompt(kind, athlete, target, slots, values)
        answer, err = _ask(prompt)
        if err:
            notes.append(err)
        else:
            bad = {}
            for name, _ in slots:
                clean, problem = check_slot(name, answer.get(name, ""))
                (bad.__setitem__(name, problem) if problem else written.__setitem__(name, clean))
            if bad:
                retry = build_prompt(kind, athlete, target, [(n, i) for n, i in slots if n in bad], values,
                                     retry_note="; ".join(f"{n} {p}" for n, p in bad.items())
                                     + ". Rewrite those sentences with no digits at all.")
                answer2, err2 = _ask(retry)
                for name in bad:
                    clean, problem = check_slot(name, (answer2 or {}).get(name, "")) if not err2 else ("", err2)
                    if problem:
                        notes.append(f"The assistant's {name.replace('_', ' ')} sentence {problem}, "
                                     "so the standard sentence was used instead.")
                    else:
                        written[name] = clean
        provider = llm.public_settings().get("label") or None

    slot_report, body = {}, tpl["body"]
    for name, instruction in slots:
        if name in written and (written[name] or name == "why_school"):
            text, source = written[name], "assistant"
        else:
            text, source = standard_sentence(kind, name, values), "standard"
        slot_report[name] = {"text": text, "source": source}
        body = SLOT_RE.sub(lambda m, n=name, t=text: t if m.group(1) == n else m.group(0), body, count=1)

    body = fill(body, values)
    body = re.sub(r"[ \t]+\n", "\n", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    subject = re.sub(r"\s*\|\s*(?=\||$)", "", fill(tpl["subject"], values)).strip(" |")

    checks = [line for block in (values["stats"], values["links"], values["schedule"]) for line in block.split("\n")[1:] if line]
    if athlete.get("ncaaId"):
        checks.append(f"NCAA Eligibility Center ID: {athlete['ncaaId']}")
    claims = [f"\u201c{r['text']}\u201d" for r in slot_report.values()
              if r["source"] == "assistant" and CLAIM_WORDS.search(r["text"])]
    if claims:
        notes.append("These sentences from the assistant sound like a claim about the player. "
                     "Keep them only if they are true: " + " ".join(claims))
    return {
        "subject": subject, "body": body, "slots": slot_report, "facts": checks, "notes": notes,
        "prompt": prompt, "provider": provider,
        "numbers_from_record_only": _numbers_are_facts(body, values, athlete, event),
    }


def _ask(prompt):
    try:
        ans = llm.complete_json(prompt, max_tokens=700)
    except llm.NotConfigured as e:
        return None, f"No assistant is set up ({e}) \u2014 the standard sentences were used."
    except llm.ProviderError as e:
        return None, f"The assistant didn't answer usably ({e}) \u2014 the standard sentences were used."
    if not isinstance(ans, dict):
        return None, "The assistant's answer wasn't in the expected shape \u2014 the standard sentences were used."
    return ans, None


def _numbers_are_facts(body, values, athlete, event):
    """Belt and braces: every number in the finished email must come from the record."""
    allowed = " ".join(str(v) for v in values.values()) + " " + json.dumps(athlete) + " " + json.dumps(event or {})
    for n in re.findall(r"\d[\d.,:/'\"-]*", body):
        core = n.strip(".,:")
        if core and core not in allowed:
            return False
    return True


def prompt_preview(kind, athlete, target, event=None, coaches=None, template=None):
    templates = load_templates()
    tpl = template or templates[kind]
    values = facts(athlete, target, event, coaches)
    slots = [(m.group(1), m.group(2)) for m in SLOT_RE.finditer(tpl["body"])]
    return build_prompt(kind, athlete, target, slots, values) if slots else "(This template has no sentences for the assistant to write.)"
