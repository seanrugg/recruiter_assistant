"""Link recognition is offline and must always work."""
from recruiting_desk import profiles as pr


def test_recognises_every_platform():
    cases = {
        "https://web.gc.com/athlete/someplayer12": ("gamechanger", "profile", "someplayer12"),
        "https://www.fieldlevel.com/app/profile/some.player/baseball": ("fieldlevel", "profile", "some.player"),
        "my.sportsrecruits.com/athlete/some_player": ("sportsrecruits", "profile", "some_player"),
        "https://www.hudl.com/profile/12345678": ("hudl", "profile", "12345678"),
        "https://www.youtube.com/@somechannel": ("youtube", "profile", "@somechannel"),
        "https://www.instagram.com/some.player": ("instagram", "social", "some.player"),
        "https://x.com/someplayer": ("x", "social", "someplayer"),
        "https://twitter.com/someplayer": ("x", "social", "someplayer"),
        "https://facebook.com/someone": ("facebook", "social", "someone"),
        "https://www.tiktok.com/@someplayer": ("tiktok", "social", "@someplayer"),
    }
    for url, (platform, kind, handle) in cases.items():
        got = pr.identify(url)
        assert (got["platform"], got["kind"], got["handle"]) == (platform, kind, handle), url


def test_unknown_link_is_filed_not_dropped():
    got = pr.identify("example.org/my-highlights")
    assert got["platform"] == "other"
    assert got["url"].startswith("https://")


def test_fieldlevel_meta_becomes_suggestions():
    page = (
        "<html><head><title>Sam Carter's Baseball Recruiting Profile | FieldLevel</title>"
        '<meta property="og:title" content="Sam Carter\'s Baseball Recruiting Profile | FieldLevel">'
        '<meta property="og:description" content="Pitcher/Center Field | 6\' 1&quot; | 180lbs | Richmond, VA | Learn More">'
        "</head></html>"
    )
    m = pr._Meta()
    m.feed(page)
    got = {s["field"]: s["value"] for s in pr.suggestions_from(m, "fieldlevel")[0]}
    assert got["name"] == "Sam Carter"
    assert got["sport"] == "baseball"
    assert "Pitcher" in got["positions"]
    assert got["height"] == "6'1\""
    assert got["weight"] == "180 lbs"
    assert got["hometown"] == "Richmond, VA"


def test_gamechanger_public_payload_mapping():
    payload = {
        "first_name": "Sam", "last_name": "Carter", "sport": "baseball",
        "graduation_year": 2027, "sport_attributes": {"positions": ["P", "OF", "3B"]},
        "bio": None,
    }
    got = {s["field"]: s["value"] for s in pr.gamechanger_suggestions(payload)}
    assert got == {"name": "Sam Carter", "sport": "baseball", "gradYear": "2027",
                   "positions": "Pitcher / Outfield / Third Base"}


def test_suggestions_are_never_pre_accepted():
    payload = {"first_name": "Sam", "last_name": "Carter"}
    assert all(s["accepted"] is False for s in pr.gamechanger_suggestions(payload))
