"""Composing emails: every fact from the record, the model only supplies voice,
and a number from the model never reaches the email. Names are invented."""
import json
import pytest

from recruiting_desk import compose, llm

ATHLETE = {
    "name": "Sam Carter", "gradYear": "2027", "positions": "Pitcher, OF", "sport": "baseball",
    "pronouns": "he/him", "school": "Example High School", "club": "Example 17U",
    "email": "sam@example.com", "phone": "555-000-1111", "ncaaId": "1234567890",
    "refName": "Pat Coach", "refEmail": "pat@club.org", "refPhone": "555-222-3333",
    "jersey": "12",
    "stats": [
        {"label": "AVG", "value": ".524", "source": "GameChanger \u00b7 Summer 2026 \u00b7 Example 18U"},
        {"label": "IP", "value": "26.0", "source": "GameChanger \u00b7 Spring 2025 \u00b7 Example HS Junior Varsity"},
        {"label": "ERA", "value": "1.88", "source": "GameChanger \u00b7 Spring 2025 \u00b7 Example HS Junior Varsity"},
    ],
    "links": [{"label": "GameChanger", "url": "https://web.gc.com/athlete/x", "include": True},
              {"label": "YouTube", "url": "https://youtube.com/@x", "include": False}],
    "socials": [{"platform": "Instagram", "handle": "@sam", "include": True}],
    "events": [{"date": "Oct 18", "name": "Fall Showcase", "location": "Field 4, 9:00am"}],
}
TARGET = {"school": "Example University", "division": "III", "coachName": "Jordan Smith",
          "coachEmail": "js@example.edu", "fit": "", "conference": "Example Conference"}


def fake_model(answers):
    calls = []

    def _fake(prompt, **kw):
        calls.append(prompt)
        return answers[min(len(calls) - 1, len(answers) - 1)]
    return _fake, calls


def test_facts_come_from_the_record_with_context(monkeypatch):
    fn, _ = fake_model([{"opening": "I'm Sam and I'd love to pitch for you.", "why_school": "",
                         "ask": "Would you take a look at my video?"}])
    monkeypatch.setattr(llm, "complete_json", fn)
    r = compose.compose("intro", ATHLETE, TARGET)
    body = r["body"]
    assert body.startswith("Coach Smith,")
    assert "Summer 2026, Example 18U: .524 AVG" in body
    assert "Spring 2025, Example HS Junior Varsity: 26.0 IP, 1.88 ERA" in body   # the level stays attached
    assert "GameChanger: https://web.gc.com/athlete/x" in body
    assert "youtube.com" not in body                                               # unticked link left out
    assert "Instagram: @sam" in body
    assert "Oct 18 \u2013 Fall Showcase, Field 4, 9:00am" in body
    assert "NCAA Eligibility Center ID: 1234567890" in body
    assert "Reference: Pat Coach, 555-222-3333, pat@club.org" in body
    assert r["subject"] == "Sam Carter | 2027 Pitcher, OF | Example 17U"
    assert r["numbers_from_record_only"] is True


def test_a_number_from_the_model_never_reaches_the_email(monkeypatch):
    fn, calls = fake_model([
        {"opening": "I hit .612 this summer with 40 RBIs!", "why_school": "", "ask": "Watch my video."},
        {"opening": "I went 12 for 20 last week."},                     # still a number on the retry
    ])
    monkeypatch.setattr(llm, "complete_json", fn)
    r = compose.compose("intro", ATHLETE, TARGET)
    assert ".612" not in r["body"] and "40 RBI" not in r["body"] and "12 for 20" not in r["body"]
    assert r["slots"]["opening"]["source"] == "standard"
    assert len(calls) == 2 and "REJECTED" in calls[1]
    assert any("contains a number" in n for n in r["notes"])
    assert r["numbers_from_record_only"] is True


def test_retry_can_recover(monkeypatch):
    fn, _ = fake_model([{"opening": "I pitched 26 innings.", "why_school": "", "ask": "Please reply."},
                        {"opening": "I'm a pitcher who loves to compete."}])
    monkeypatch.setattr(llm, "complete_json", fn)
    r = compose.compose("intro", ATHLETE, TARGET)
    assert r["slots"]["opening"] == {"text": "I'm a pitcher who loves to compete.", "source": "assistant"}


def test_no_model_still_makes_a_complete_true_email(monkeypatch):
    def broken(*a, **k):
        raise llm.NotConfigured("none chosen")
    monkeypatch.setattr(llm, "complete_json", broken)
    r = compose.compose("intro", ATHLETE, TARGET)
    assert "My name is Sam, a 2027 baseball player (Pitcher, OF), and I'm very interested in playing at Example University." in r["body"]
    assert "Coach Smith," in r["body"] and "Recent numbers:" in r["body"]
    assert all(s["source"] == "standard" for s in r["slots"].values())


def test_reason_for_school_is_never_invented_without_facts(monkeypatch):
    fn, calls = fake_model([{"opening": "Hi.", "why_school": "", "ask": "Thanks for reading."}])
    monkeypatch.setattr(llm, "complete_json", fn)
    r = compose.compose("intro", ATHLETE, {**TARGET, "conference": ""})
    assert "The player's own reason for this school: none given" in calls[0]
    assert r["slots"]["why_school"]["text"] == ""


def test_prompt_carries_no_digits_from_the_record():
    p = compose.prompt_preview("intro", ATHLETE, TARGET)
    body_of_prompt = p.split("HOW THE PLAYER WRITES")[0]
    assert ".524" not in p and "1234567890" not in p and "555-" not in p
    assert "Example 17U" not in p               # team names with digits are not shown to the model
    assert "Never write a number" in p


def test_claims_are_flagged(monkeypatch):
    fn, _ = fake_model([{"opening": "I was named MVP of my league.", "why_school": "", "ask": "Please write back."}])
    monkeypatch.setattr(llm, "complete_json", fn)
    r = compose.compose("intro", ATHLETE, TARGET)
    assert any("sound like a claim" in n for n in r["notes"])


def test_several_coaches_at_one_school_are_greeted_by_name():
    assert compose.greeting(["Jordan Smith", "Alex Lee", "Chris Park"]) == \
        "Coach Smith, Coach Lee and Coach Park,"
    assert compose.greeting([""]) == "Coach,"


def test_coming_up_uses_the_chosen_event_and_jersey(monkeypatch):
    fn, _ = fake_model([{"opening": "I'll be playing nearby soon.", "ask": "Hope to see you there."}])
    monkeypatch.setattr(llm, "complete_json", fn)
    r = compose.compose("coming", ATHLETE, TARGET, event=ATHLETE["events"][0])
    assert "Oct 18 \u2013 Fall Showcase, Field 4, 9:00am" in r["body"]
    assert "I'll be wearing #12." in r["body"]
    assert r["subject"].endswith("Playing at Fall Showcase")


def test_held_division_gets_an_honest_note(monkeypatch):
    fn, _ = fake_model([{"opening": "Hi.", "why_school": "", "ask": "Thanks."}])
    monkeypatch.setattr(llm, "complete_json", fn)
    r = compose.compose("intro", {**ATHLETE, "gradYear": "2031"}, {**TARGET, "division": "I"})
    assert "can't reply to my class until September 1, 2029" in r["body"]


def test_edited_templates_save_and_reset():
    t = compose.save_template("intro", "Hi from {name}", "{greeting}\n\n[[opening | say hello]]\n\n{signature}")
    assert t["is_default"] is False and t["subject"] == "Hi from {name}"
    assert compose.reset_template("intro")["is_default"] is True


def test_reasoning_blocks_are_ignored():
    assert llm.parse_json('<think>let me consider</think>{"opening": "Hi"}') == {"opening": "Hi"}
