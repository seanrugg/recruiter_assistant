"""Directory parsing: right person, right title, never an invented address."""
from recruiting_desk import coach_finder as cf

TABLE = """<table>
<tr><td>Jane Doe</td><td>Head Coach, Softball</td><td><a href="mailto:jdoe@example.edu">Email</a></td><td>(555) 123-4567</td></tr>
<tr><td>Rob Smith</td><td>Assistant Coach, Softball</td><td><a href="mailto:rsmith@example.edu">Email</a></td></tr>
<tr><td>Amy Pine</td><td>Head Coach, Baseball</td><td><a href="mailto:apine@example.edu">Email</a></td></tr>
</table>"""


def test_rows_stay_separate():
    got = cf.extract_contacts(TABLE, "https://example.edu/staff", "softball")
    jane = next(c for c in got if c["email"] == "jdoe@example.edu")
    rob = next(c for c in got if c["email"] == "rsmith@example.edu")
    assert (jane["name"], jane["title"], jane["phone"]) == ("Jane Doe", "Head Coach", "(555) 123-4567")
    assert (rob["name"], rob["title"], rob["phone"]) == ("Rob Smith", "Assistant Coach", "")


def test_sport_sorts_first_but_hides_nothing():
    got = cf.extract_contacts(TABLE, "u", "baseball")
    assert got[0]["email"] == "apine@example.edu"
    assert len(got) == 3


def test_everything_needs_verification():
    assert all(c["needs_verification"] for c in cf.extract_contacts(TABLE, "u"))


def test_no_address_is_invented():
    page = "<table><tr><td>Jane Doe</td><td>Head Coach, Softball</td></tr></table>"
    assert cf.extract_contacts(page, "u", "softball") == []
