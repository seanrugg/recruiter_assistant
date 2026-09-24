"""
Importing a coach list someone already has.

Families and club coaches keep these in spreadsheets, and every one is laid out
a little differently: headers on row two, "Coach" or "Name" or "First"/"Last",
"D1" or "Division I" or "NCAA DI", a half-finished row at the bottom. So this
reads CSV and Excel files, finds the header row itself, recognizes columns by
what they are called, and reports each row it could not use rather than
silently dropping it or silently importing it.

Nothing is added here. This returns a preview; the person ticks what to keep.
"""

import csv
import io
import re
import base64

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

# Column name -> field. Matched after lowercasing and stripping punctuation.
COLUMNS = {
    "school": ["school", "college", "university", "institution", "program", "school name", "college name"],
    "division": ["division", "div", "level", "association", "ncaa division", "conference level"],
    "location": ["location", "where", "city state", "citystate", "town"],
    "city": ["city"],
    "state": ["state", "st"],
    "coach": ["coach", "name", "coach name", "full name", "contact", "contact name", "head coach", "coach full name"],
    "first": ["first", "first name", "firstname", "given name"],
    "last": ["last", "last name", "lastname", "surname", "family name"],
    "title": ["title", "position", "role", "job title"],
    "email": ["email", "e mail", "email address", "coach email", "contact email", "mail"],
    "phone": ["phone", "phone number", "cell", "mobile", "office phone", "telephone"],
    "fit": ["notes", "note", "fit", "why", "comments", "reason", "why this school"],
}


def _key(text):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).split())


LOOKUP = {_key(alias): field for field, aliases in COLUMNS.items() for alias in aliases}


def normalize_division(value):
    """'D1', 'Division II', 'NCAA D-III', '3', 'NJCAA', 'NAIA' -> I / II / III / JUCO / NAIA.

    Strict on purpose: only something that reads as a division counts. A stray
    'GAME 2' is not Division II, and guessing would quietly put the wrong
    contact-date rules on a coach."""
    v = _key(value)
    if not v:
        return ""
    if re.search(r"\b(juco|njcaa|cccaa|nwac|junior college|community college)\b", v):
        return "JUCO"
    if re.fullmatch(r"(ncaa )?naia|naia( .*)?", v):
        return "NAIA"
    compact = v.replace(" ", "")
    for prefix in ("ncaa", "division", "div"):
        if compact.startswith(prefix):
            compact = compact[len(prefix):]
    m = re.fullmatch(r"d?(i{1,3}|[123])", compact)
    if not m:
        return ""
    return {"i": "I", "ii": "II", "iii": "III", "1": "I", "2": "II", "3": "III"}[m.group(1)]


def _rows_from_csv(data):
    text = None
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return [list(r) for r in csv.reader(io.StringIO(text), dialect)]


def _rows_from_xlsx(data):
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    ws = wb.worksheets[0]
    rows = [["" if c is None else str(c).strip() for c in r] for r in ws.iter_rows(values_only=True)]
    wb.close()
    return rows


def _find_header(rows):
    """The header row is the first of the top ten with two or more known column names."""
    best = None
    for i, row in enumerate(rows[:10]):
        mapped = {j: LOOKUP[_key(c)] for j, c in enumerate(row) if _key(c) in LOOKUP}
        if len(set(mapped.values())) >= 2 and (best is None or len(mapped) > len(best[1])):
            best = (i, mapped)
            if len(mapped) >= 3:
                break
    return best


def parse_coach_file(filename, data):
    name = (filename or "").lower()
    try:
        if name.endswith((".xlsx", ".xlsm")):
            rows = _rows_from_xlsx(data)
        elif name.endswith(".xls"):
            return {"ok": False, "error": "Old-style .xls files can't be read. In Excel, choose "
                                          "File \u2192 Save As \u2192 Excel Workbook (.xlsx) or CSV, then try again."}
        else:
            rows = _rows_from_csv(data)
    except Exception as e:
        return {"ok": False, "error": f"That file couldn't be read ({type(e).__name__}). "
                                      "Save it as .xlsx or .csv and try again."}

    header = _find_header(rows)
    if not header:
        return {"ok": False, "error": "Couldn't find column headings. The file needs a heading row "
                                      "with at least two of: School, Division, Coach (or Name), Email."}
    hi, mapping = header
    found = sorted(set(mapping.values()))
    if "email" not in found:
        return {"ok": False, "error": "There is no Email column, so there would be no one to write to. "
                                      "Add an Email column and try again.", "columns": found}

    out = []
    for n, row in enumerate(rows[hi + 1:], start=hi + 2):
        rec = {}
        for j, field in mapping.items():
            if j < len(row) and str(row[j]).strip():
                rec.setdefault(field, str(row[j]).strip())
        if not any(rec.values()):
            continue  # blank row
        coach = rec.get("coach") or " ".join(x for x in [rec.get("first", ""), rec.get("last", "")] if x)
        location = rec.get("location") or ", ".join(x for x in [rec.get("city", ""), rec.get("state", "")] if x)
        email = rec.get("email", "").strip().strip("<>").replace("mailto:", "")
        division = normalize_division(rec.get("division", ""))
        problems = []
        if not rec.get("school"):
            problems.append("no school")
        if not email:
            problems.append("no email")
        elif not EMAIL_RE.match(email):
            problems.append("email doesn't look valid")
        if rec.get("division") and not division:
            problems.append(f"division \u201c{rec['division']}\u201d not recognized")
        out.append({
            "line": n,
            "school": rec.get("school", ""),
            "division": division,
            "location": location,
            "coachName": coach,
            "title": rec.get("title", ""),
            "coachEmail": email,
            "phone": rec.get("phone", ""),
            "fit": rec.get("fit", ""),
            "problems": problems,
            "usable": not any(p in problems for p in ("no email", "email doesn't look valid", "no school")),
        })

    # Same address twice in one file: keep the first, flag the rest.
    seen = set()
    for r in out:
        e = r["coachEmail"].lower()
        if e and e in seen:
            r["problems"].append("same email appears earlier in the file")
            r["usable"] = False
        seen.add(e)

    return {
        "ok": True,
        "rows": out,
        "columns": found,
        "header_line": hi + 1,
        "usable": sum(1 for r in out if r["usable"]),
        "total": len(out),
    }


def parse_upload(filename, data_b64):
    try:
        data = base64.b64decode(data_b64)
    except (ValueError, TypeError):
        return {"ok": False, "error": "The file didn't upload cleanly. Try again."}
    if len(data) > 5 * 1024 * 1024:
        return {"ok": False, "error": "That file is over 5 MB. A coach list should be far smaller -- "
                                      "is it the right file?"}
    return parse_coach_file(filename, data)
