"""Coaching-staff pages as real athletics sites build them. Names are invented."""
from recruiting_desk import coach_finder as cf

NEW_LAYOUT = """
<table><tbody>
<tr class="s-table-body__row"><td><a href="/sports/baseball/roster/coaches/pat-one/1"><img alt="x"></a></td>
  <td><a href="/sports/baseball/roster/coaches/pat-one/1"><span>Pat One</span></a></td>
  <td><span>Head Coach</span></td><td><span>Field House 100 / MSC 1234</span></td>
  <td>555-111-2222</td><td><a href='mailto:one@example.edu'>one@example.edu</a></td></tr>
<tr class="s-table-body__row"><td></td>
  <td><a href="/sports/baseball/roster/coaches/sam-two/2"><span>Sam Two</span></a></td>
  <td><span>Manager</span></td><td></td><td></td><td></td></tr>
</tbody></table>
<div class="card"><a href="/sports/baseball/roster/coaches/pat-one/1">Pat One</a></div>"""

DIRECTORY_NEW = """
<h3 class="s-text-title" data-test-id="staff-directory-archive-view-type-list__title">Softball</h3>
<div class="s-person-card__content__person-details"><a aria-label="Someone Else full bio"></a>
  <div class="s-person-details__position s-text-details"><div>Head Coach</div></div></div>
  <a href="mailto:else@example.edu">x</a></div>
<h3 class="s-text-title" data-test-id="staff-directory-archive-view-type-list__title">Baseball</h3>
<div class="s-person-card__content__person-details"><a aria-label="Pat One full bio"></a>
  <div class="s-person-details__position s-text-details"><div>Head Coach</div></div></div>
  <a href="tel:+15551112222">555-111-2222</a><a href="mailto:one@example.edu">one@example.edu</a></div>
<div class="s-person-card__content__person-details"><a aria-label="Chris Three full bio"></a>
  <div class="s-person-details__position s-text-details"><div>Assistant Pitching Coach</div></div></div>
  <a href="tel:+15553334444">555-333-4444</a><a href="mailto:three@example.edu">three@example.edu</a></div>
<div class="s-person-card__content__person-details"><a aria-label="Lee Four full bio"></a>
  <div class="s-person-details__position s-text-details"><div>Administrative Assistant</div><div>ASSIGNED SPORTS \u2013 Baseball, Golf</div></div></div>
  <a href="mailto:four@example.edu">four@example.edu</a></div>
<h3 class="s-text-title" data-test-id="staff-directory-archive-view-type-list__title">Basketball</h3>"""

DIRECTORY_OLD = """<table>
<tr class="sidearm-staff-category"><td>Baseball</td></tr>
<tr class="sidearm-staff-member"><td><a href="/staff/1">Pat One</a></td><td>Head Coach</td><td>(555) 111-2222</td><td><a href="mailto:one@example.edu">x</a></td></tr>
<tr class="sidearm-staff-category"><td>Softball</td></tr>
<tr class="sidearm-staff-member"><td>Not Baseball</td><td>Head Coach</td><td></td><td><a href="mailto:nb@example.edu">x</a></td></tr>
</table>"""


def test_new_layout_rows_found_by_bio_link_and_deduplicated():
    got = cf.sidearm_coaches(NEW_LAYOUT, "https://example.edu/sports/baseball/coaches")
    assert [(c["name"], c["title"], c["email"], c["phone"]) for c in got] == [
        ("Pat One", "Head Coach", "one@example.edu", "555-111-2222"),
        ("Sam Two", "Manager", "", ""),
    ]


def test_directory_reads_only_the_sports_section():
    got = cf.directory_section(DIRECTORY_NEW, "baseball", "u")
    assert [(p["name"], p["title"]) for p in got] == [
        ("Pat One", "Head Coach"), ("Chris Three", "Assistant Pitching Coach"),
        ("Lee Four", "Administrative Assistant")]          # "ASSIGNED SPORTS" suffix trimmed
    assert got[1]["phone"] == "555-333-4444"


def test_older_directory_layout_by_category_row():
    got = cf.directory_section(DIRECTORY_OLD, "baseball", "u")
    assert [(p["name"], p["email"]) for p in got] == [("Pat One", "one@example.edu")]


def test_titles_decide_who_is_a_coach():
    yes = ["Head Coach", "Assistant Coach/Recruiting Coordinator", "Assistant Pitching Coach",
           "Volunteer Assistant Coach", "Associate Head Coach", "Head Softball Coach"]
    no = ["Manager", "Director of Operations", "Athletic Trainer Softball", "Graduate Assistant",
          "Assistant Sports Performance Coach", "Director of Player Development",
          "Administrative Assistant", "Strength and Conditioning Coach"]
    assert all(cf.is_coaching_title(t) for t in yes)
    assert not any(cf.is_coaching_title(t) for t in no)


def test_directory_adds_coaches_missing_from_the_coaches_page(monkeypatch):
    pages = {"https://example.edu/sports/baseball/coaches": NEW_LAYOUT,
             "https://example.edu/staff-directory": DIRECTORY_NEW}
    monkeypatch.setattr(cf, "fetch", lambda url: (pages.get(url), None if url in pages else {"code": "x"}))
    r = cf.school_coaches("example.edu", "baseball")
    rows = [(c["name"], c["is_coach"], c["from_directory"]) for c in r["coaches"]]
    assert rows == [
        ("Pat One", True, False),            # on the coaches page
        ("Chris Three", True, True),         # only in the directory -- added, and marked
        ("Sam Two", False, False),           # manager: listed, not a coach
        ("Lee Four", False, True),
    ]
    assert len(r["sources"]) == 2


def test_no_sport_section_means_nothing_guessed(monkeypatch):
    monkeypatch.setattr(cf, "fetch", lambda url: ("<html><a href='mailto:x@y.edu'>x</a></html>", None))
    r = cf.school_coaches("example.edu", "baseball")
    assert r["ok"] is False and r["coaches"] == []
