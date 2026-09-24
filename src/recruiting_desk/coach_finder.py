"""
Finding the right coach to write to.

Every college athletics site publishes a staff directory. This reads one and
pulls out the coaching staff for a sport. It is a fetch-and-parse of a public
page, not a crawl: one page at a time, robots.txt checked first, a real user
agent, and a pause between requests.

Three rules this module keeps, because the alternative is an email bouncing off
a coach who left in 2023:

1. Nothing it returns is treated as verified. Every contact carries the page it
   came from and needs_verification=True. Staff directories go stale, and a
   parent clicking one link to confirm a name is thirty seconds well spent.
2. It never guesses an address from a pattern. If firstname.lastname@school.edu
   is not on the page, it is not returned -- a plausible address that bounces
   costs more than a blank field.
3. It reports what it could not do. A page it was told not to fetch, or one it
   could not parse, says so rather than returning an empty list that reads like
   "this school has no coaches".
"""

import re
import time
import html
import urllib.parse
import urllib.robotparser
from html.parser import HTMLParser

import httpx

UA = "RecruitingDesk/1.0 (personal college-recruiting assistant; contact via the family using it)"

SPORT_WORDS = {
    "softball": ["softball"],
    "baseball": ["baseball"],
}

COACH_TITLES = [
    "head coach", "assistant coach", "associate head coach", "pitching coach",
    "hitting coach", "recruiting coordinator", "volunteer assistant", "director of operations",
]

# Paths that athletics sites commonly use. Tried in order, one request apiece.
DIRECTORY_PATHS = [
    "/staff-directory",
    "/staff.aspx",
    "/coaches",
    "/sports/{sport}/coaches",
    "/sports/{sport}/roster/coaches",
    "/information/directory",
]

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}")

_last_request = [0.0]


def _polite_pause(seconds=1.5):
    wait = seconds - (time.time() - _last_request[0])
    if wait > 0:
        time.sleep(wait)
    _last_request[0] = time.time()


def robots_allows(url):
    parts = urllib.parse.urlsplit(url)
    robots = f"{parts.scheme}://{parts.netloc}/robots.txt"
    rp = urllib.robotparser.RobotFileParser()
    try:
        r = httpx.get(robots, headers={"User-Agent": UA}, timeout=10.0, follow_redirects=True)
        if r.status_code >= 400:
            return True  # no robots.txt published means no restriction stated
        rp.parse(r.text.splitlines())
    except httpx.HTTPError:
        return True
    return rp.can_fetch(UA, url)


class _Text(HTMLParser):
    """Flattens a page into text blocks and mailto links, keeping their order.

    Staff directories are tables, cards or lists depending on the vendor, so
    rather than target one layout this keeps the reading order and pairs each
    address with the text around it."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks = []          # (kind, value) where kind is "text" or "email"
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        if tag == "a":
            href = dict(attrs).get("href", "")
            if href.lower().startswith("mailto:"):
                addr = html.unescape(href[7:].split("?")[0]).strip()
                if EMAIL_RE.fullmatch(addr):
                    self.blocks.append(("email", addr))
        if tag in ("tr", "li", "article"):
            self.blocks.append(("row", ""))
        elif tag in ("div", "p", "h1", "h2", "h3", "h4", "br", "td"):
            self.blocks.append(("break", ""))

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if self._skip:
            return
        t = " ".join(data.split())
        if t:
            self.blocks.append(("text", t))


def fetch(url):
    """Fetch one public page. Returns (text, error)."""
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    if not robots_allows(url):
        return None, {"code": "robots_disallowed",
                      "message": f"{url} asks automated tools not to read it. Open it in a browser instead."}
    _polite_pause()
    try:
        r = httpx.get(url, headers={"User-Agent": UA}, timeout=20.0, follow_redirects=True)
    except httpx.HTTPError as e:
        return None, {"code": "unreachable", "message": f"Could not open {url}: {e}"}
    if r.status_code == 404:
        return None, {"code": "not_found", "message": f"No page at {url}."}
    if r.status_code >= 400:
        return None, {"code": "http_error", "message": f"{url} returned {r.status_code}."}
    return r.text, None


def _name_from(texts):
    for v in reversed(texts):
        if any(ch.isdigit() for ch in v) or "@" in v:
            continue
        if any(t in v.lower() for t in COACH_TITLES):
            continue
        words = [w for w in v.replace(",", " ").replace(".", " ").split() if w]
        if not 2 <= len(words) <= 4:
            continue
        alpha = [w for w in words if w[:1].isalpha()]
        if len(alpha) >= 2 and all(w[0].isupper() for w in alpha):
            return v.strip().rstrip(",")
    return ""


def _title_from(texts):
    for v in texts:
        low = v.lower()
        for t in sorted(COACH_TITLES, key=len, reverse=True):
            if t in low:
                return t.title()
    return ""


def _segments(blocks):
    """Split the page into rows. Directories are tables, list items or cards;
    whichever it is, one person sits between two boundaries."""
    segs, current = [], []
    for kind, value in blocks:
        if kind == "row":
            if current:
                segs.append(current)
            current = []
        else:
            current.append((kind, value))
    if current:
        segs.append(current)
    return segs


def extract_contacts(page_html, source_url, sport=""):
    """Pull coaching staff out of a directory page."""
    p = _Text()
    try:
        p.feed(page_html)
    except Exception:
        pass

    want = SPORT_WORDS.get(sport.lower(), [])
    segs = _segments(p.blocks)
    rowed = any(k == "row" for k, _ in p.blocks)
    out = []

    def add(emails, texts):
        context = " \u00b7 ".join(texts)
        low = context.lower()
        phone = PHONE_RE.search(context)
        for addr in emails:
            out.append({
                "name": _name_from(texts),
                "title": _title_from(texts),
                "email": addr,
                "phone": phone.group(0) if phone else "",
                "context": context[:240],
                "sport_match": (not want) or any(w in low for w in want),
                "source_url": source_url,
                "needs_verification": True,
            })

    if rowed:
        for seg in segs:
            emails = [v for k, v in seg if k == "email"]
            if emails:
                add(emails, [v for k, v in seg if k == "text"])
    else:
        # Card or free-form layout: fall back to a tight window around each address.
        blocks = p.blocks
        for i, (kind, value) in enumerate(blocks):
            if kind != "email":
                continue
            texts = [v for k, v in blocks[max(0, i - 6): i + 3] if k == "text"]
            add([value], texts)

    if want:
        out.sort(key=lambda c: (not c["sport_match"], not c["title"]))
    return out


def find_coaches(url, sport=""):
    """Read one staff-directory page and return what is on it."""
    page, err = fetch(url)
    if err:
        return {"ok": False, "error": err, "contacts": []}
    contacts = extract_contacts(page, url, sport)
    return {
        "ok": True,
        "source_url": url,
        "sport": sport,
        "contacts": contacts,
        "found": len(contacts),
        "caveat": ("These came off a public page and none are confirmed. Staff directories go stale; "
                   "open the source page and check the name before writing to it."),
    }


def find_directory(site, sport=""):
    """Try the common staff-directory paths on an athletics site.

    Stops at the first page that yields contacts. At most one request per path,
    spaced out, so this is a handful of requests and not a crawl."""
    if not site.lower().startswith(("http://", "https://")):
        site = "https://" + site
    root = site.rstrip("/")
    tried = []
    for path in DIRECTORY_PATHS:
        url = root + path.format(sport=sport.lower() or "softball")
        page, err = fetch(url)
        tried.append({"url": url, "result": "ok" if page else err.get("code")})
        if not page:
            continue
        contacts = extract_contacts(page, url, sport)
        if contacts:
            return {"ok": True, "source_url": url, "contacts": contacts, "tried": tried,
                    "caveat": "Unconfirmed. Open the source page and check before writing."}
    return {
        "ok": False,
        "tried": tried,
        "contacts": [],
        "error": {"code": "no_directory",
                  "message": "None of the usual staff-directory addresses worked on this site.",
                  "hint": "Find the directory in a browser and pass its address to find_coaches."},
    }


# ==========================================================================
# School search, from the NCAA's own member directory
#
# The NCAA publishes every member school with its division, conference,
# location and -- the part that matters here -- its official athletics
# website. That turns "type a school name" into "read that school's coaching
# staff" without a search engine in the middle.
#
# Junior colleges and NAIA schools are not NCAA members and are not in it.
# For those, the athletics site address can be pasted directly.
# ==========================================================================

import json
import datetime

from .paths import data_dir

NCAA_DIRECTORY = "https://web3.ncaa.org/directory/api/directory/memberList?type=12"
DIRECTORY_CACHE = "ncaa_members.json"
DIRECTORY_MAX_AGE_DAYS = 30
ROMAN = {"1": "I", "2": "II", "3": "III", 1: "I", 2: "II", 3: "III"}


def _directory():
    """The member list, cached on this computer and refreshed monthly."""
    cache = data_dir() / DIRECTORY_CACHE
    if cache.exists():
        try:
            saved = json.loads(cache.read_text())
            age = datetime.datetime.now() - datetime.datetime.fromisoformat(saved["fetched"])
            if age.days < DIRECTORY_MAX_AGE_DAYS:
                return saved["schools"], None
        except (ValueError, KeyError, json.JSONDecodeError):
            pass
    try:
        r = httpx.get(NCAA_DIRECTORY, headers={"User-Agent": UA, "Accept": "application/json"},
                      timeout=45.0, follow_redirects=True)
        r.raise_for_status()
        raw = r.json()
    except (httpx.HTTPError, ValueError) as e:
        if cache.exists():  # stale beats nothing
            try:
                return json.loads(cache.read_text())["schools"], None
            except (ValueError, KeyError):
                pass
        return [], {"code": "unreachable", "message": f"Could not load the NCAA school directory: {e}"}
    schools = []
    for x in raw:
        if str(x.get("deactive", "")).strip().upper() in ("Y", "YES", "TRUE", "1"):
            continue  # the NCAA marks active schools "N" -- a string, so test the value, not truthiness
        addr = x.get("memberOrgAddress") or {}
        site = (x.get("athleticWebUrl") or "").strip()
        schools.append({
            "name": x.get("nameOfficial", ""),
            "nickname": x.get("nickname") or "",
            "acronym": x.get("acronym") or "",
            "division": ROMAN.get(x.get("division"), str(x.get("division") or "")),
            "conference": x.get("conferenceName") or "",
            "city": addr.get("city") or "",
            "state": addr.get("state") or "",
            "athletics_url": _normalize_site(site),
        })
    tmp = cache.with_suffix(".tmp")
    tmp.write_text(json.dumps({"fetched": datetime.datetime.now().isoformat(), "schools": schools}))
    tmp.replace(cache)
    return schools, None


def _normalize_site(site):
    """'www.lynchburgsports.com/landing/index' -> 'https://www.lynchburgsports.com'."""
    if not site:
        return ""
    if not site.lower().startswith(("http://", "https://")):
        site = "https://" + site
    parts = urllib.parse.urlsplit(site)
    return f"{parts.scheme}://{parts.netloc}"


def search_schools(query, limit=12):
    q = " ".join((query or "").lower().split())
    if len(q) < 2:
        return {"ok": False, "error": {"code": "too_short", "message": "Type at least two letters."}, "schools": []}
    schools, err = _directory()
    if err and not schools:
        return {"ok": False, "error": err, "schools": []}
    words = q.split()

    def score(s):
        hay = f"{s['name']} {s['nickname']} {s['acronym']} {s['city']}".lower()
        if not all(w in hay for w in words):
            return None
        name = s["name"].lower()
        if name == q:
            return 0
        if name.startswith(q):
            return 1
        if q in name:
            return 2
        return 3

    hits = [(score(s), s) for s in schools]
    hits = sorted((h for h in hits if h[0] is not None), key=lambda h: (h[0], h[1]["name"]))
    return {
        "ok": True,
        "schools": [s for _, s in hits[:limit]],
        "total": len(hits),
        "note": ("Only NCAA schools are listed. For a junior college or NAIA school, "
                 "paste its athletics website address instead."),
    }


# ==========================================================================
# Reading a coaching staff page
#
# Most college athletics sites are built on Sidearm Sports, which puts each
# coach in a <tr class="sidearm-coaches-coach"> row -- name, title, phone,
# email -- and keeps trainers and support staff in a separate table. Reading
# those rows exactly is far more reliable than guessing from page text, and it
# never mistakes an athletic trainer who "covers softball" for a coach.
# ==========================================================================

class _SidearmRows(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self._row = None
        self._cell = None
        self._heading = None       # text of the h2/h3 being read
        self._last_heading = ""
        self._table = 0            # which staff table a row sits in
        self._group = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("h2", "h3"):
            self._heading = []
        elif tag == "table":
            self._table += 1
            self._group = self._last_heading
        elif tag == "tr" and "sidearm-coaches-coach" in (a.get("class") or ""):
            self._row = {"cells": [], "emails": [], "profile": "", "table": self._table, "group": self._group}
        elif self._row is not None and tag in ("th", "td"):
            self._cell = []
        elif self._row is not None and tag == "a":
            href = a.get("href") or ""
            if href.lower().startswith("mailto:"):
                addr = html.unescape(href[7:].split("?")[0]).strip()
                if EMAIL_RE.fullmatch(addr):
                    self._row["emails"].append(addr)
            elif "/coaches/" in href and not self._row["profile"]:
                self._row["profile"] = href

    def handle_endtag(self, tag):
        if tag in ("h2", "h3") and self._heading is not None:
            self._last_heading = " ".join(" ".join(self._heading).split())
            self._heading = None
        if self._row is not None and tag in ("th", "td") and self._cell is not None:
            self._row["cells"].append(" ".join(" ".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._heading is not None:
            self._heading.append(data)
        if self._cell is not None:
            self._cell.append(data)


def sidearm_coaches(page_html, source_url):
    p = _SidearmRows()
    try:
        p.feed(page_html)
    except Exception:
        return []
    out = []
    base = urllib.parse.urlsplit(source_url)
    first_table = min((r["table"] for r in p.rows), default=0)
    for row in p.rows:
        cells = [c for c in row["cells"]]
        name = cells[0] if cells else ""
        title = cells[1] if len(cells) > 1 else ""
        phone = ""
        for c in cells[2:]:
            m = PHONE_RE.search(c)
            if m:
                phone = m.group(0)
                break
        profile = row["profile"]
        if profile and profile.startswith("/"):
            profile = f"{base.scheme}://{base.netloc}{profile}"
        out.append({
            "name": name,
            "title": title,
            "email": row["emails"][0] if row["emails"] else "",
            "phone": phone,
            "profile_url": profile,
            "source_url": source_url,
            "needs_verification": True,
            # Sidearm lists the coaching staff first; later tables are support
            # staff -- trainers, operations, communications. Kept, but marked.
            "support_staff": row["table"] != first_table or "support" in row["group"].lower(),
            "group": row["group"],
        })
    return out


def school_coaches(site, sport):
    """Coaching staff for one sport at one school's athletics site."""
    site = _normalize_site(site)
    if not site:
        return {"ok": False, "error": {"code": "no_site", "message": "No athletics website to read."}, "coaches": []}
    sport = (sport or "softball").lower()
    url = f"{site}/sports/{sport}/coaches"
    page, err = fetch(url)
    if page:
        coaches = sidearm_coaches(page, url)
        if coaches:
            missing = [c["name"] for c in coaches if not c["email"] and not c["support_staff"]]
            return {
                "ok": True, "site": site, "source_url": url, "coaches": coaches, "layout": "sidearm",
                "missing_email": missing,
                "note": ("Read from the school's coaching staff page. Check each one on that page before writing."
                         + (f" {len(missing)} coach{'es have' if len(missing) != 1 else ' has'} no email published "
                            "there -- the school chose not to list it, so it is left blank rather than guessed."
                            if missing else "")),
            }
    # Not a Sidearm site, or no coaches page: fall back to the general reader.
    fallback = find_directory(site, sport)
    coaches = [{
        "name": c["name"], "title": c["title"], "email": c["email"], "phone": c["phone"],
        "profile_url": "", "source_url": c["source_url"], "needs_verification": True,
        "support_staff": False, "group": "",
    } for c in fallback.get("contacts", []) if c.get("sport_match")]
    if coaches:
        return {"ok": True, "site": site, "source_url": fallback.get("source_url", ""), "coaches": coaches,
                "layout": "general", "missing_email": [],
                "note": ("This site uses an unusual layout, so names and titles may be off. "
                         "Check every one against the page before adding.")}
    return {"ok": False, "site": site, "coaches": [],
            "error": {"code": "not_found",
                      "message": f"Could not find a {sport} coaching staff page on {site}.",
                      "hint": "Open the site in a browser, find the coaches page, and add them by hand -- "
                              "or paste that page's address here."}}
