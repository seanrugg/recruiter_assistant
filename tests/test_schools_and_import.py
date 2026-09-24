"""School search, coaching-staff pages, and coach-list import -- all offline."""
import io
import json
import datetime

import openpyxl

from recruiting_desk import coach_finder as cf
from recruiting_desk import coach_import as ci
from recruiting_desk.paths import data_dir

SIDEARM = """
<h2>2026 Softball Coaching Staff</h2><table><tbody>
<tr class="sidearm-coaches-coach"><th><a href="/sports/softball/roster/coaches/jane-doe/1">Jane Doe</a></th>
  <td>Head Coach</td><td>(555) 123-4567</td><td></td></tr>
<tr class="sidearm-coaches-coach"><th><a href="/sports/softball/roster/coaches/rob-smith/2">Rob Smith</a></th>
  <td>Assistant Coach</td><td></td><td><a href="mailto:rsmith@example.edu">rsmith@example.edu</a></td></tr>
</tbody></table>
<h2>2026 Softball Support Staff</h2><table><tbody>
<tr class="sidearm-coaches-coach"><th><a href="/staff/x/3">Pat Lee</a></th>
  <td>Athletic Trainer Softball, Soccer</td><td></td><td><a href="mailto:plee@example.edu">plee@example.edu</a></td></tr>
</tbody></table>"""


def test_sidearm_rows_separate_coaches_from_support_staff():
    got = cf.sidearm_coaches(SIDEARM, "https://example.edu/sports/softball/coaches")
    assert [(c["name"], c["title"], c["support_staff"]) for c in got] == [
        ("Jane Doe", "Head Coach", False),
        ("Rob Smith", "Assistant Coach", False),
        ("Pat Lee", "Athletic Trainer Softball, Soccer", True),
    ]
    jane = got[0]
    assert jane["email"] == ""                         # not published -> blank, never guessed
    assert jane["phone"] == "(555) 123-4567"
    assert jane["profile_url"] == "https://example.edu/sports/softball/roster/coaches/jane-doe/1"


def test_school_search_ranks_and_skips_inactive(monkeypatch):
    cache = data_dir() / cf.DIRECTORY_CACHE
    cache.write_text(json.dumps({"fetched": datetime.datetime.now().isoformat(), "schools": [
        {"name": "University of Mary Washington", "nickname": "Eagles", "acronym": "UMW", "division": "III",
         "conference": "C2C", "city": "", "state": "VA", "athletics_url": "https://www.umweagles.com"},
        {"name": "Washington College", "nickname": "Shoremen", "acronym": "", "division": "III",
         "conference": "Centennial", "city": "", "state": "MD", "athletics_url": "https://example.com"},
    ]}))
    r = cf.search_schools("mary washington")
    assert [s["name"] for s in r["schools"]] == ["University of Mary Washington"]
    assert cf.search_schools("washington")["total"] == 2
    assert cf.search_schools("x")["ok"] is False


def test_normalize_site():
    assert cf._normalize_site("www.lynchburgsports.com/landing/index") == "https://www.lynchburgsports.com"
    assert cf._normalize_site("vuusports.com/") == "https://vuusports.com"


def _xlsx(rows):
    wb = openpyxl.Workbook()
    for r in rows:
        wb.active.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_excel_import_finds_header_below_a_blank_row():
    data = _xlsx([
        [None, None, None],
        ["School", "Division", "LOCATION", "Name", "Email"],
        ["Barton College", "II", "Wilson, NC", "Coach One", "one@barton.edu"],
        ["Some JC", "NJCAA", "Somewhere", "Coach Two", "two@somejc.edu"],
        ["GAME 1", "GAME 2", "GAME 3", "GAME 4", None],
    ])
    r = ci.parse_coach_file("coaches.xlsx", data)
    assert r["ok"] and r["header_line"] == 2
    assert [(x["school"], x["division"], x["usable"]) for x in r["rows"]] == [
        ("Barton College", "II", True), ("Some JC", "JUCO", True), ("GAME 1", "", False)]


def test_csv_import_with_first_last_and_duplicates():
    csv_text = ("College,Div,First Name,Last Name,E-mail,Notes\n"
                "Alpha U,D1,Ann,Lee,ann@alpha.edu,great fit\n"
                "Beta College,Division III,Bo,Ray,bo@beta,\n"
                "Alpha U,NCAA DI,Ann,Lee,ANN@alpha.edu,dup\n")
    r = ci.parse_coach_file("list.csv", csv_text.encode())
    rows = r["rows"]
    assert rows[0]["coachName"] == "Ann Lee" and rows[0]["division"] == "I" and rows[0]["fit"] == "great fit"
    assert "email doesn't look valid" in rows[1]["problems"]
    assert "same email appears earlier in the file" in rows[2]["problems"]
    assert r["usable"] == 1


def test_import_requires_an_email_column():
    r = ci.parse_coach_file("x.csv", b"School,Coach\nAlpha,Ann\n")
    assert r["ok"] is False and "Email" in r["error"]


def test_division_spellings():
    for raw, want in [("D1", "I"), ("Division II", "II"), ("NCAA D-III", "III"), ("NAIA", "NAIA"),
                      ("JUCO", "JUCO"), ("NJCAA D2", "JUCO"), ("3", "III"), ("", "")]:
        assert ci.normalize_division(raw) == want, raw
