"""Contact windows and follow-ups."""
from recruiting_desk import campaign


def test_open_divisions_have_no_date():
    w = campaign.contact_window("III", "2029", as_of="2026-09-01")
    assert w["open"] is True and w["date"] is None


def test_division_one_holds_until_junior_year():
    w = campaign.contact_window("I", "2029", as_of="2026-09-01")
    assert w["open"] is False and w["date"] == "2027-09-01"
    assert campaign.contact_window("I", "2029", as_of="2027-09-01")["open"] is True


def test_missing_class_year_is_reported_not_guessed():
    w = campaign.contact_window("I", "")
    assert w["known"] is False


def test_follow_up_due_after_two_weeks_without_reply():
    campaign.save_athlete("a1", {"name": "Test", "grad_year": "2028"})
    campaign.save_program("p1", {"athlete_id": "a1", "school": "Somewhere", "division": "III"})
    campaign.log_outreach({"program_id": "p1", "action": "sent", "date": "2026-01-01"})
    due = campaign.follow_ups_due("a1", as_of="2026-01-20")
    assert [d["program_id"] for d in due] == ["p1"]
    campaign.log_outreach({"program_id": "p1", "action": "replied", "date": "2026-01-21"})
    assert campaign.follow_ups_due("a1", as_of="2026-02-20") == []
