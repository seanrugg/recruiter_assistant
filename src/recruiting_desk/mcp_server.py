"""
Recruiting Desk -- a local MCP server that lets whichever AI assistant an athlete
already uses read her own GameChanger data and help her write to college coaches.

Runs on the family's machine. The token never leaves it. Every GameChanger tool
is a GET. There is deliberately no tool that sends mail, and there will not be
one: a coach who can tell an adult or a script wrote the email deletes it, so
the last step belongs to the athlete.

  stdio (Claude Desktop, most MCP clients):
      python server.py
  streamable HTTP (ChatGPT developer-mode connectors, remote clients):
      python server.py --http --port 8756
  OpenAPI (Open WebUI, anything that speaks OpenAPI tool servers):
      uvx mcpo --port 8000 -- python server.py
"""

import sys
import argparse
import datetime

try:                                        # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer as _Server
except ModuleNotFoundError:                 # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from . import campaign
from . import coach_finder
from . import profiles as profile_links
from .gc_client import GameChangerClient, load_config, NotConfigured, AuthExpired

mcp = _Server("recruiting-desk")

BASE_URL, ENDPOINTS, RULE_OVERRIDES, CFG = load_config()
gc = GameChangerClient(BASE_URL, ENDPOINTS)


DELIVERY_INSTRUCTIONS = {
    "draft_to_mailbox": (
        "Use your mail connector to create this as a DRAFT in her own mailbox -- do not send it. "
        "Tell her it is waiting, and that she should read it, change anything that does not sound "
        "like her, and send it herself. A coach who can tell an adult or a script wrote the email "
        "deletes it, and her own edit is what keeps it hers."
    ),
    "send": (
        "She has set this campaign to send directly. Show her the full text and the recipient first, "
        "wait for her to say yes to that specific email, then send it from her address with her "
        "parent copied. Never send a batch on one approval."
    ),
}


def _delivery_instruction(athlete_record):
    mode = (athlete_record.get("delivery") or "draft_to_mailbox").strip()
    return {
        "mode": mode,
        "instruction": DELIVERY_INSTRUCTIONS.get(mode, DELIVERY_INSTRUCTIONS["draft_to_mailbox"]),
        "from_address": athlete_record.get("email", ""),
        "log_after": "Call outreach_log_entry with action='sent' once it has actually gone.",
    }


def _wrap(fn, *args, **kwargs):
    """Every failure becomes a readable instruction, never a stack trace.

    An assistant that gets 'this needs entering by hand' does the right thing.
    One that gets a traceback invents the number instead."""
    try:
        return {"ok": True, "data": fn(*args, **kwargs)}
    except AuthExpired as e:
        return {"ok": False, "error": "auth_expired", "message": str(e),
                "what_to_do": "Ask the family to sign in again and replace the token. Do not guess at the data."}
    except PermissionError as e:
        return {"ok": False, "error": "premium_required", "message": str(e),
                "what_to_do": "Ask the athlete for these figures directly and record the source she gives."}
    except NotConfigured as e:
        return {"ok": False, "error": "not_configured", "message": str(e),
                "what_to_do": "Ask the athlete for this information directly. Do not infer it."}
    except LookupError as e:
        return {"ok": False, "error": "not_found", "message": str(e)}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__, "message": str(e)}


# ---------------------------------------------------------------- GameChanger

@mcp.tool()
def gc_auth_status() -> dict:
    """Check whether this machine holds a usable GameChanger token, and which endpoints are configured."""
    st = gc.auth_status()
    st["config_file"] = CFG.get("config")
    st["config_found"] = CFG.get("found")
    st["endpoints_configured"] = sorted(ENDPOINTS.keys())
    return st


@mcp.tool()
def gc_list_teams() -> dict:
    """List the teams this GameChanger account is linked to.

    An account only reaches teams it actually joined. A parent who joined for the
    school season but not the travel team will see one and not the other."""
    return _wrap(gc.get, "teams")


@mcp.tool()
def gc_team_schedule(team_id: str, start_date: str = "", end_date: str = "") -> dict:
    """Games for a team, past and upcoming, with dates, times, locations and opponents.

    Upcoming games are what turns 'come watch me' into a real field and time."""
    query = {}
    if start_date:
        query["start"] = start_date
    if end_date:
        query["end"] = end_date
    return _wrap(gc.get, "team_schedule", team_id=team_id, query=query or None)


@mcp.tool()
def gc_team_roster(team_id: str) -> dict:
    """Roster for a team: players, jersey numbers, positions."""
    return _wrap(gc.get, "team_roster", team_id=team_id)


@mcp.tool()
def gc_player_season_stats(team_id: str, player_id: str) -> dict:
    """Season and career stat lines for one player on one team.

    Needs Premium on a parent or fan account. Staff accounts see it free."""
    return _wrap(gc.get, "player_stats", team_id=team_id, player_id=player_id)


@mcp.tool()
def gc_game_box_score(game_id: str) -> dict:
    """Box score for one scored game -- the source a single-game claim traces back to."""
    return _wrap(gc.get, "game_box_score", game_id=game_id)


@mcp.tool()
def gc_game_play_by_play(game_id: str) -> dict:
    """Play-by-play for one scored game."""
    return _wrap(gc.get, "game_play_by_play", game_id=game_id)


@mcp.tool()
def gc_player_video(team_id: str, player_id: str) -> dict:
    """Game streams and auto-cut clips for one player -- the link that goes in the email."""
    return _wrap(gc.get, "player_video", team_id=team_id, player_id=player_id)


# ---------------------------------------------------------------- the athlete

@mcp.tool()
def athlete_list() -> dict:
    """Every athlete set up on this machine."""
    return {"athletes": [{"id": k, "name": v.get("name", "")} for k, v in campaign.athletes().items()]}


@mcp.tool()
def athlete_get(athlete_id: str) -> dict:
    """One athlete's record: academics, positions, links, and anything GameChanger does not know."""
    return _wrap(campaign.athlete, athlete_id)


@mcp.tool()
def athlete_save(athlete_id: str, fields: dict) -> dict:
    """Create or update an athlete record.

    Useful fields: sport ("softball" or "baseball"), pronouns ("she/her", "he/him",
    "they/them"), name, grad_year, high_school, club_team, positions, jersey,
    gpa, test_scores, academic_interest, gc_profile_url, recruiting_profile_url,
    email, phone, coach_reference, writing_sample, gc_team_id, gc_player_id,
    delivery.

    delivery is how finished emails reach coaches, and the assistant's mail
    connector is what carries them out:
      "draft_to_mailbox" (default) -- compose it as a draft in her own mailbox.
                          She opens it, changes what does not sound like her,
                          and presses send.
      "send"           -- send it directly from her address on her say-so.

    writing_sample matters more than it looks: drafts are matched to it, and
    without one they read like an adult wrote them."""
    return _wrap(campaign.save_athlete, athlete_id, fields)


# ---------------------------------------------------------------- the programs

@mcp.tool()
def program_list(athlete_id: str) -> dict:
    """Target programs for one athlete, with contact windows resolved against her class year."""
    a = campaign.athletes().get(athlete_id, {})
    out = []
    for p in campaign.programs_for(athlete_id):
        row = dict(p)
        row["contact_window"] = campaign.contact_window(p.get("division"), a.get("grad_year"))
        row["history"] = campaign.history_for(p["id"])
        out.append(row)
    return {"athlete_id": athlete_id, "programs": out}


@mcp.tool()
def program_save(program_id: str, fields: dict) -> dict:
    """Create or update a target program.

    Useful fields: athlete_id, school, division (I/II/III/NAIA/JUCO), location,
    coach_name, coach_email, tier, fit (why this program specifically), notes."""
    return _wrap(campaign.save_program, program_id, fields)


@mcp.tool()
def contact_window_check(division: str, grad_year: str) -> dict:
    """When coaches at this division may begin recruiting communication with this class.

    Returns the date and whether it has passed. The athlete may write earlier;
    the restriction is on when the coach may answer."""
    return campaign.contact_window(division, grad_year)


@mcp.tool()
def contact_rules_get() -> dict:
    """The contact-date table this machine is using, and when it was last verified."""
    return campaign.rules(RULE_OVERRIDES)


@mcp.tool()
def contact_rules_set(rules: dict) -> dict:
    """Replace the contact-date table. Record verified_on and verified_by when you do."""
    path = campaign.save_rules(rules)
    return {"ok": True, "written": path}


# ---------------------------------------------------------------- profile links

@mcp.tool()
def profile_link_inspect(url: str) -> dict:
    """Recognize a pasted profile or social link and read what the page publishes.

    Handles GameChanger, SportsRecruits, FieldLevel, Hudl, YouTube, Instagram, X,
    Facebook and TikTok. Always identifies the platform and the handle. Reading
    the page for a name, class year, position or school works on some platforms
    and not others, and the result says which happened.

    Everything it reads is a suggestion off a public page, never confirmed.
    Offer each field to the athlete before writing it to the record."""
    return profile_links.inspect(url)


# ---------------------------------------------------------------- coach data

@mcp.tool()
def coach_directory_read(url: str, sport: str = "") -> dict:
    """Read a college athletics staff directory and pull out the coaching staff.

    Pass the directory page's address. sport is "softball" or "baseball" and
    sorts the sport's own staff to the top rather than hiding the rest.

    Nothing this returns is confirmed. Every contact carries the page it came
    from -- open it and check the name before writing. Directories go stale, and
    an email to a coach who left two years ago is a wasted one."""
    return coach_finder.find_coaches(url, sport)


@mcp.tool()
def coach_directory_find(site: str, sport: str = "") -> dict:
    """Try the usual staff-directory addresses on an athletics site.

    Pass the site root, e.g. "godeacs.com". Tries a handful of common paths, one
    request each, and stops at the first that yields contacts. If it finds
    nothing, open the site in a browser and pass the real address to
    coach_directory_read."""
    return coach_finder.find_directory(site, sport)


# ---------------------------------------------------------------- drafting

@mcp.tool()
def draft_brief(athlete_id: str, program_id: str) -> dict:
    """Everything needed to write one email, assembled and sourced.

    Call this before drafting. It returns the athlete's record, the program, the
    contact window, her upcoming games, and the drafting rules. Write the email
    from what comes back and nothing else -- if a field is empty, leave that
    subject out rather than filling it with something plausible."""
    try:
        a = campaign.athlete(athlete_id)
    except KeyError as e:
        return {"ok": False, "error": "no_athlete", "message": str(e)}
    p = campaign.programs().get(program_id)
    if not p:
        return {"ok": False, "error": "no_program", "message": f"No program '{program_id}'."}

    window = campaign.contact_window(p.get("division"), a.get("grad_year"))
    stats = a.get("stats", [])
    schedule = {"ok": False, "note": "Not fetched. Call gc_team_schedule for upcoming games."}
    if a.get("gc_team_id"):
        today = datetime.date.today().isoformat()
        schedule = _wrap(gc.get, "team_schedule", team_id=a["gc_team_id"], query={"start": today})

    return {
        "ok": True,
        "athlete": a,
        "program": p,
        "contact_window": window,
        "stats_on_file": stats,
        "upcoming_games": schedule,
        "prior_contact": campaign.history_for(program_id),
        "sport": a.get("sport", "softball"),
        "pronouns": a.get("pronouns", ""),
        "rules_for_drafting": [
            "Use only facts present in this brief. Invent nothing.",
            "Use the athlete's own pronouns, given above. If none are recorded, use their name and "
            "avoid pronouns entirely rather than assuming.",
            "Every number must come from stats_on_file or a box score you actually read, and must be "
            "stated with the source it came from. Do not round up, project, or describe a figure you were not given.",
            "If a field is empty, leave that subject out of the email entirely.",
            "Write in the athlete's voice, matched to writing_sample. A teenager wrote this, not a development office.",
            "Under 200 words. No bullet lists. No flattery of the coach. No 'I am reaching out'.",
            "Include: who they are and their class year, why this program specifically, the two or three "
            "stats that matter for their position, the video link, when and where they can next be seen, one clear ask.",
            "DELIVERY is set on the athlete record and repeated below. Follow it exactly.",
            "List back every factual claim you made and where each one came from, so the athlete can check them.",
        ],
        "if_window_closed": ("She may still write; the coach may not answer until the date above. Say so plainly "
                             "rather than drafting as though the date does not exist."),
        "delivery": _delivery_instruction(a),
    }


@mcp.tool()
def outreach_log_entry(program_id: str, action: str, date: str = "", note: str = "", subject: str = "") -> dict:
    """Record something that happened: action is one of drafted, sent, replied, no_reply, closed.

    Log 'sent' only after the athlete tells you she sent it. This tool records
    history; it does not send anything."""
    if action not in ("drafted", "sent", "replied", "no_reply", "closed"):
        return {"ok": False, "error": "bad_action",
                "message": "action must be drafted, sent, replied, no_reply or closed."}
    entry = {
        "program_id": program_id,
        "action": action,
        "date": date or datetime.date.today().isoformat(),
        "note": note,
        "subject": subject,
    }
    return _wrap(campaign.log_outreach, entry)


@mcp.tool()
def follow_ups_due(athlete_id: str) -> dict:
    """Programs written to that have not replied and are past a two-week wait."""
    return {"due": campaign.follow_ups_due(athlete_id)}


@mcp.prompt()
def recruiting_session(athlete_id: str = "") -> str:
    """Standing instructions for a recruiting session. Load this first."""
    return RECRUITING_INSTRUCTIONS.format(athlete_id=athlete_id or "(ask which athlete)")


RECRUITING_INSTRUCTIONS = """\
You are helping a high school softball or baseball player write to college coaches. Her data
lives in a local GameChanger connection and a campaign folder on this machine.

Athlete: {athlete_id}

How to work:

1. Start with athlete_get and program_list. Do not ask her for anything the
   tools already know.
2. Before drafting any email, call draft_brief. Write from what it returns and
   nothing else.
3. Never state a number that did not come from her own data. If a stat is not
   available -- no Premium, endpoint not configured, game not scored -- ask her
   for it and record where she says it came from. An inflated figure a coach
   checks is worse than no email at all, and it cannot be walked back.
4. Respect the contact window. If it has not opened, say so and say what it
   means: she may write, the coach may not answer yet.
5. Write in her voice. Match the writing sample. If there is no sample, ask for
   a few paragraphs she wrote herself before drafting anything.
6. After each draft, list every factual claim and its source so she can check
   them.
7. Deliver it the way her record says, using your own mail connector. The
   default is a draft in her mailbox that she reads and sends herself; the
   brief tells you which mode is set and what it requires. Either way the mail
   leaves from her address, not yours and not a parent's.
8. Log it with outreach_log_entry once it has actually gone.

Do one or two programs at a time. Fifty drafts she never reads is worse than
five she actually sent.
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--http", action="store_true", help="serve streamable HTTP instead of stdio")
    ap.add_argument("--port", type=int, default=8756)
    args = ap.parse_args()
    if args.http:
        mcp.settings.port = args.port
        mcp.run(transport="streamable-http")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
