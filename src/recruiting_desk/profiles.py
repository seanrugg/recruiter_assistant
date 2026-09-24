"""
Paste a link, get a filled-in record.

Two separate jobs, and they succeed at very different rates:

1. RECOGNITION -- what is this link? Pure pattern matching on the URL, no
   network, always works. A pasted address lands in the right place with the
   right label and the handle pulled out of it.

2. READING -- what does the page say about the player? A fetch and a parse of
   whatever the page publishes about itself: OpenGraph tags, JSON-LD, the
   title. This works on some platforms and not others, and the honest answer
   differs per site:

   - GameChanger athlete pages render in the browser and publish nothing in
     their HTML -- but the app behind them has a public endpoint that answers
     for a published profile with no credentials at all. That is what this
     module calls, and it is the single best source in the list.
   - SportsRecruits, FieldLevel and Hudl publish some of it in meta tags --
     often a name, sometimes a class year, position or school.
   - Instagram, Facebook and X serve a login wall to anything that is not a
     signed-in browser. Nothing readable comes back, and pretending otherwise
     would just produce made-up fields.

Everything read is a SUGGESTION. Nothing is written to the record without
someone accepting it, because a name scraped out of a page title is a guess and
a recruiting email built on a guess is worse than one built on a blank.
"""

import re
import json
import html
from html.parser import HTMLParser

import httpx

UA = ("Mozilla/5.0 (compatible; RecruitingDesk/1.0; personal college-recruiting assistant)")

PLATFORMS = [
    {"id": "gamechanger", "label": "GameChanger", "kind": "profile",
     "patterns": [r"(?:web\.)?gc\.com/athlete/([A-Za-z0-9_.\-]+)", r"gc\.com/"],
     "readable": True,
     "note": ""},
    {"id": "sportsrecruits", "label": "SportsRecruits", "kind": "profile",
     "patterns": [r"sportsrecruits\.com/athlete/([A-Za-z0-9_.\-]+)", r"sportsrecruits\.com/"],
     "readable": True},
    {"id": "fieldlevel", "label": "FieldLevel", "kind": "profile",
     "patterns": [r"fieldlevel\.com/(?:app/)?profile/([A-Za-z0-9_.\-]+)", r"fieldlevel\.com/"],
     "readable": True},
    {"id": "hudl", "label": "Hudl", "kind": "profile",
     "patterns": [r"hudl\.com/profile/(\d+)", r"hudl\.com/"], "readable": True},
    {"id": "youtube", "label": "YouTube", "kind": "profile",
     "patterns": [r"youtube\.com/(@[A-Za-z0-9_.\-]+)", r"youtube\.com/channel/([A-Za-z0-9_\-]+)",
                  r"youtu\.be/([A-Za-z0-9_\-]+)", r"youtube\.com/"],
     "readable": True},
    {"id": "instagram", "label": "Instagram", "kind": "social",
     "patterns": [r"instagram\.com/([A-Za-z0-9_.]+)", r"instagram\.com/"], "readable": False,
     "note": "Instagram serves a login wall to anything that is not a signed-in browser, so nothing "
             "can be read from the link. The handle is filed as typed."},
    {"id": "x", "label": "X", "kind": "social",
     "patterns": [r"(?:twitter|x)\.com/([A-Za-z0-9_]+)"], "readable": False,
     "note": "X does not serve profile details to anything but a signed-in browser."},
    {"id": "facebook", "label": "Facebook", "kind": "social",
     "patterns": [r"facebook\.com/([A-Za-z0-9_.\-]+)", r"facebook\.com/"], "readable": False,
     "note": "Facebook serves a login wall, so nothing can be read from the link."},
    {"id": "tiktok", "label": "TikTok", "kind": "social",
     "patterns": [r"tiktok\.com/(@[A-Za-z0-9_.]+)"], "readable": False,
     "note": "TikTok does not serve profile details to anything but a signed-in browser."},
]

POSITIONS = [
    "pitcher", "catcher", "first base", "second base", "third base", "shortstop",
    "left field", "center field", "right field", "outfield", "infield", "utility",
    "designated hitter", "middle infield", "corner infield",
]
POS_ABBR = {"rhp": "RHP", "lhp": "LHP", "1b": "1B", "2b": "2B", "3b": "3B",
            "ss": "SS", "of": "OF", "if": "IF", "c": "C", "dh": "DH", "p": "P"}


def identify(url):
    """What is this link? No network, always answers."""
    u = (url or "").strip()
    if not u:
        return None
    low = u.lower()
    for p in PLATFORMS:
        for pattern in p["patterns"]:
            m = re.search(pattern, low)
            if m:
                handle = ""
                if m.groups():
                    handle = m.group(1)
                    original = re.search(pattern, u, re.I)
                    if original and original.groups():
                        handle = original.group(1)
                return {
                    "platform": p["id"], "label": p["label"], "kind": p["kind"],
                    "handle": handle, "readable": p["readable"],
                    "note": p.get("note", ""),
                    "url": u if u.lower().startswith("http") else "https://" + u,
                }
    return {"platform": "other", "label": "Profile", "kind": "profile", "handle": "",
            "readable": True, "note": "", "url": u if low.startswith("http") else "https://" + u}


class _Meta(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = {}
        self.title = ""
        self.ld = []
        self._in_title = False
        self._in_ld = False
        self._buf = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key and a.get("content"):
                self.meta[key] = html.unescape(a["content"])
        if tag == "title":
            self._in_title = True
        if tag == "script" and (a.get("type", "").lower() == "application/ld+json"):
            self._in_ld = True
            self._buf = []

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag == "script" and self._in_ld:
            self._in_ld = False
            try:
                self.ld.append(json.loads("".join(self._buf)))
            except (json.JSONDecodeError, ValueError):
                pass

    def handle_data(self, data):
        if self._in_title:
            self.title += data.strip()
        if self._in_ld:
            self._buf.append(data)


def _suggest(field, value, source):
    return {"field": field, "value": value, "source": source, "accepted": False}


def read_page(url, timeout=15.0):
    """Fetch a profile page and return what it publishes about itself."""
    try:
        r = httpx.get(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"},
                      timeout=timeout, follow_redirects=True)
    except httpx.HTTPError as e:
        return None, {"code": "unreachable", "message": f"Could not open the page: {e}"}
    if r.status_code >= 400:
        return None, {"code": "http_error", "message": f"The page returned {r.status_code}."}
    m = _Meta()
    try:
        m.feed(r.text)
    except Exception:
        pass
    return m, None


def suggestions_from(meta, platform):
    """Turn page metadata into field suggestions. Conservative on purpose."""
    m = meta.meta
    blob_parts = [meta.title, m.get("og:title", ""), m.get("og:description", ""),
                  m.get("description", ""), m.get("twitter:title", ""), m.get("twitter:description", "")]
    for ld in meta.ld:
        items = ld if isinstance(ld, list) else [ld]
        for item in items:
            if isinstance(item, dict):
                for k in ("name", "description", "jobTitle", "affiliation"):
                    v = item.get(k)
                    if isinstance(v, str):
                        blob_parts.append(v)
    blob = " \u00b7 ".join(p for p in blob_parts if p)
    low = blob.lower()
    out = []

    generic = ("gamechanger app", "log in", "sign up", "page not found")
    if not blob or any(g in low for g in generic):
        return out, blob

    # -- name. Recruiting sites title pages three predictable ways.
    name = ""
    title = m.get("og:title") or meta.title or ""
    for pattern in (r"^(.+?)['\u2019]s\s", r"^([A-Za-z][A-Za-z.'\-]+(?:\s+[A-Za-z][A-Za-z.'\-]+){1,3})\s*\("):
        hit = re.search(pattern, title) or re.search(pattern, m.get("twitter:title", ""))
        if hit:
            name = hit.group(1).strip()
            break
    if not name and title:
        first = re.split(r"\s+[|\u2013\u2014-]\s+", title)[0].strip()
        words = first.split()
        if 2 <= len(words) <= 4 and not any(ch.isdigit() for ch in first):
            name = first
    if name:
        out.append(_suggest("name", name, "page title"))

    # -- sport, stated outright on recruiting profiles
    sport_hit = re.search(r"\b(baseball|softball)\b", low)
    if sport_hit:
        out.append(_suggest("sport", sport_hit.group(1), "page text"))

    # -- class year
    hit = re.search(r"class of\s*(20\d{2})", low) or re.search(r"\b(20[2-4]\d)\s*grad", low)
    if hit:
        out.append(_suggest("gradYear", hit.group(1), "page text"))

    # -- positions, spelled out or abbreviated
    found = [p.title() for p in POSITIONS if p in low]
    if not found:
        for abbr, disp in POS_ABBR.items():
            if len(abbr) > 1 and re.search(r"\b" + abbr + r"\b", low):
                found.append(disp)
    if found:
        out.append(_suggest("positions", " / ".join(dict.fromkeys(found))[:60], "page text"))

    # -- height and weight
    hit = re.search(r"(\d)\s*['\u2019]\s*(\d{1,2})\s*[\"\u201d]?", blob)
    if hit:
        out.append(_suggest("height", f"{hit.group(1)}'{hit.group(2)}\"", "page text"))
    hit = re.search(r"(\d{2,3})\s*lbs", low)
    if hit:
        out.append(_suggest("weight", hit.group(1) + " lbs", "page text"))

    # -- hometown, usually between pipes as "Town, ST"
    hit = re.search(r"([A-Z][A-Za-z .'\-]{2,25},\s*[A-Z]{2})\b", blob)
    if hit:
        out.append(_suggest("hometown", hit.group(1).strip(), "page text"))

    hit = re.search(r"([A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){0,3}\s+High School)", blob)
    if hit:
        out.append(_suggest("school", hit.group(1), "page text"))

    hit = re.search(r"\bgpa[:\s]*([0-4]\.\d{1,2})", low)
    if hit:
        out.append(_suggest("gpa", hit.group(1), "page text"))

    return out, blob


def inspect(url):
    """Recognize a link, and read it if the platform allows."""
    who = identify(url)
    if not who:
        return {"ok": False, "error": {"code": "empty", "message": "No link given."}}

    result = {
        "ok": True, "platform": who["platform"], "label": who["label"], "kind": who["kind"],
        "handle": who["handle"], "url": who["url"], "note": who["note"],
        "suggestions": [], "read": False,
    }

    if who["platform"] == "gamechanger":
        if not who["handle"]:
            result["message"] = ("That GameChanger address has no athlete handle in it. The profile link "
                                 "looks like web.gc.com/athlete/<handle>.")
            return result
        payload, err = gamechanger_public(who["handle"])
        if err:
            result["message"] = err["message"] + " The link is still saved."
            return result
        result["read"] = True
        result["suggestions"] = gamechanger_suggestions(payload)
        result["profile_id"] = payload.get("id", "")
        result["published"] = payload.get("publish_status") == "published"
        result["has_premium_access"] = payload.get("has_premium_access")
        result["avatar_url"] = payload.get("avatar_url", "")
        if not result["published"]:
            result["message"] = ("That profile is unpublished, so GameChanger serves nothing for it. "
                                 "Publishing it in the GameChanger app is what makes it readable -- "
                                 "and what lets a coach open the link you send.")
        else:
            result["message"] = "Read straight from the published GameChanger profile. Check each field before accepting it."
        return result

    if not who["readable"]:
        result["message"] = who["note"] or "This platform does not publish details to anything but a signed-in browser."
        return result

    meta, err = read_page(who["url"])
    if err:
        result["message"] = err["message"] + " The link is still saved."
        return result

    result["read"] = True
    sugg, blob = suggestions_from(meta, who["platform"])
    result["suggestions"] = sugg
    result["page_says"] = blob[:300]
    if not sugg:
        result["message"] = ("The page loaded but published nothing usable about the player. "
                             "Fill the fields in by hand.")
    else:
        result["message"] = ("Read off the page and not confirmed by anyone. Check each one before "
                             "accepting it.")
    return result


# --------------------------------------------------------------------------
# GameChanger's public profile endpoint
#
# A published athlete profile answers to anyone, no account and no password.
# It returns the athlete's own details and a capability token scoped to that
# one profile, valid for a day. Nothing here reaches another family's data: an
# unpublished profile simply is not served.
# --------------------------------------------------------------------------

GC_API = "https://api.team-manager.gc.com"

POSITION_NAMES = {
    "P": "Pitcher", "C": "Catcher", "1B": "First Base", "2B": "Second Base",
    "3B": "Third Base", "SS": "Shortstop", "LF": "Left Field", "CF": "Center Field",
    "RF": "Right Field", "OF": "Outfield", "IF": "Infield", "DH": "Designated Hitter",
    "UTIL": "Utility", "RHP": "RHP", "LHP": "LHP",
}


def gamechanger_public(handle, timeout=20.0):
    """Read a published GameChanger athlete profile by its handle."""
    headers = {"User-Agent": UA, "Accept": "application/json",
               "Origin": "https://web.gc.com",
               "Referer": f"https://web.gc.com/athlete/{handle}"}
    try:
        r = httpx.get(f"{GC_API}/public/athlete-profile/{handle}", headers=headers, timeout=timeout)
    except httpx.HTTPError as e:
        return None, {"code": "unreachable", "message": f"Could not reach GameChanger: {e}"}
    if r.status_code == 404:
        return None, {"code": "not_found",
                      "message": "GameChanger has no published profile at that address. Check the handle."}
    if r.status_code >= 400:
        return None, {"code": "http_error", "message": f"GameChanger returned {r.status_code}."}
    try:
        return r.json(), None
    except ValueError:
        return None, {"code": "bad_response", "message": "GameChanger returned something unreadable."}


def gamechanger_suggestions(payload):
    """Turn the public profile into field suggestions."""
    out = []
    src = "GameChanger profile"
    name = " ".join(x for x in [payload.get("first_name"), payload.get("last_name")] if x).strip()
    if name:
        out.append(_suggest("name", name, src))
    if payload.get("sport"):
        out.append(_suggest("sport", str(payload["sport"]).lower(), src))
    if payload.get("graduation_year"):
        out.append(_suggest("gradYear", str(payload["graduation_year"]), src))
    positions = (payload.get("sport_attributes") or {}).get("positions") or []
    if positions:
        readable = [POSITION_NAMES.get(str(p).upper(), str(p)) for p in positions]
        out.append(_suggest("positions", " / ".join(readable), src))
    if payload.get("bio"):
        out.append(_suggest("bio", str(payload["bio"])[:400], src))
    return out
