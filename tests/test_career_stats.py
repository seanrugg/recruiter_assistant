"""Career stats: formatting a coach can read, newest season first, honest failures."""
import httpx
from recruiting_desk import profiles as pr


def test_formats_like_a_scorebook():
    assert pr.fmt_stat(0.40880, "avg") == ".409"
    assert pr.fmt_stat(1.3772, "avg") == "1.377"
    assert pr.fmt_stat(12.3333, "ip") == "12.1"
    assert pr.fmt_stat(12.6667, "ip") == "12.2"
    assert pr.fmt_stat(4.2994, "era") == "4.30"
    assert pr.fmt_stat(0.5147, "pct") == "51%"
    assert pr.fmt_stat(None, "avg") == ""


def test_seasons_sort_newest_first():
    names = ["Summer 2025", "Fall 2025", "Winter 2026", "Summer 2026", "Spring 2026"]
    assert sorted(names, key=pr.season_sort_key, reverse=True) == [
        "Summer 2026", "Spring 2026", "Winter 2026", "Fall 2025", "Summer 2025"]


PAYLOAD = {
    "player_stats_data": [
        {"team_id": "t1", "info": {"season_display_name": "Summer 2025", "team_display_name": "Older Team"},
         "stats": {"offense": {"PA": 28, "AVG": 0.4, "OPS": 1.2714}, "defense": {}}},
        {"team_id": "t2", "info": {"season_display_name": "Summer 2026", "team_display_name": "Newer Team"},
         "stats": {"offense": {"PA": 26, "AVG": 0.5238, "OBP": 0.615}, "defense": {"IP": 1.6667, "ERA": 0.0}}},
        {"team_id": "t3", "info": {"season_display_name": "Spring 2026", "team_display_name": "Did Not Play"},
         "stats": {"offense": {"PA": 0}, "defense": {"IP": 0}}},
    ],
    "aggregated_stats_data": {"offense": {"AVG": 0.409}, "defense": {"ERA": 4.2995}},
}


def test_summary_drops_empty_seasons_and_names_sources():
    seasons, career = pr.summarize_career_stats(PAYLOAD)
    assert [s["season"] for s in seasons] == ["Summer 2026", "Summer 2025"]
    newest = seasons[0]
    assert newest["source"] == "GameChanger \u00b7 Summer 2026 \u00b7 Newer Team"
    assert {b["label"]: b["value"] for b in newest["batting"]}["AVG"] == ".524"
    assert {b["label"]: b["value"] for b in newest["pitching"]}["IP"] == "1.2"
    assert seasons[1]["pitching"] == []          # no innings -> no pitching block
    assert "career total" in career["source"]


def test_blocked_stats_say_so_instead_of_returning_nothing(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(403, text="Forbidden"))
    data, err = pr.gamechanger_career_stats("some-id", "some-token")
    assert data is None
    assert err["code"] == "blocked"
    assert "by hand" in err["message"]
