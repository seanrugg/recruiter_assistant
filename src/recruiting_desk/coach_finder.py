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

class _StaffRows(HTMLParser):
    """Collects every table row on a coaching-staff page, with the section it
    sits in, its cell text, its email links, and any link to a coach bio.

    What makes a row a coach is decided afterwards, not by class name: Sidearm
    has at least two generations of markup ('sidearm-coaches-coach' rows on
    older sites, 's-table-body__row' on newer ones), but on both, every coach
    row links to that coach's bio under /roster/coaches/. That link is the
    signal, and it survives redesigns that class names do not."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self._row = None
        self._cell = None
        self._link = None
        self._heading = None
        self._last_heading = ""
        self._table = 0
        self._group = ""
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style", "svg"):
            self._skip += 1
        if tag in ("h2", "h3"):
            self._heading = []
        elif tag == "table":
            self._table += 1
            self._group = self._last_heading
        elif tag == "tr":
            self._row = {"cells": [], "emails": [], "coach_links": [], "table": self._table,
                         "group": self._group, "legacy": "sidearm-coaches-coach" in (a.get("class") or "")}
        elif self._row is not None and tag in ("th", "td"):
            self._cell = []
        elif self._row is not None and tag == "a":
            href = a.get("href") or ""
            if href.lower().startswith("mailto:"):
                addr = html.unescape(href[7:].split("?")[0]).strip()
                if EMAIL_RE.fullmatch(addr):
                    self._row["emails"].append(addr)
            elif "/roster/coaches/" in href or ("/coaches/" in href and self._row["legacy"]):
                self._link = {"href": href, "text": []}

    def handle_endtag(self, tag):
        if tag in ("script", "style", "svg") and self._skip:
            self._skip -= 1
        if tag in ("h2", "h3") and self._heading is not None:
            self._last_heading = " ".join(" ".join(self._heading).split())
            self._heading = None
        if tag == "a" and self._link is not None and self._row is not None:
            self._link["text"] = " ".join(" ".join(self._link["text"]).split())
            self._row["coach_links"].append(self._link)
            self._link = None
        if self._row is not None and tag in ("th", "td") and self._cell is not None:
            self._row["cells"].append(" ".join(" ".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._skip:
            return
        if self._heading is not None:
            self._heading.append(data)
        if self._cell is not None:
            self._cell.append(data)
        if self._link is not None:
            self._link["text"].append(data)


def sidearm_coaches(page_html, source_url):
    """Coaches from a Sidearm staff page, old or new layout."""
    p = _StaffRows()
    try:
        p.feed(page_html)
    except Exception:
        return []
    rows = [r for r in p.rows if r["legacy"] or r["coach_links"]]
    if not rows:
        return []
    base = urllib.parse.urlsplit(source_url)
    first_table = min(r["table"] for r in rows)
    out, seen = [], set()
    for row in rows:
        cells = [c for c in row["cells"]]
        named = [l["text"] for l in row["coach_links"] if l["text"]]
        name = named[0] if named else next((c for c in cells if c), "")
        # Title is the first non-empty cell after the name that is not a phone,
        # an email, or an office address.
        title = ""
        if name in cells:
            for c in cells[cells.index(name) + 1:]:
                if c and not PHONE_RE.search(c) and "@" not in c and not re.search(r"\d{3,}", c):
                    title = c
                    break
        phone = ""
        for c in cells:
            m = PHONE_RE.search(c)
            if m:
                phone = m.group(0)
                break
        profile = row["coach_links"][0]["href"] if row["coach_links"] else ""
        if profile.startswith("/"):
            profile = f"{base.scheme}://{base.netloc}{profile}"
        email = row["emails"][0] if row["emails"] else ""
        key = (name.lower(), email.lower())
        if not name or key in seen:
            continue  # newer layouts repeat each coach as a card and a table row
        seen.add(key)
        out.append({
            "name": name,
            "title": title,
            "email": email,
            "phone": phone,
            "profile_url": profile,
            "source_url": source_url,
            "needs_verification": True,
            "support_staff": row["table"] != first_table or "support" in row["group"].lower(),
            "group": row["group"],
        })
    return out


# --------------------------------------------------------------------------
# Who is a coach
#
# Staff pages list managers, trainers, operations and communications staff
# alongside coaches, sometimes in the same table. Titles say which is which.
# Only coaching titles are pre-ticked; everyone else is shown, unticked.
# --------------------------------------------------------------------------

NOT_COACHING = re.compile(
    r"performance|strength|conditioning|trainer|sports medicine|nutrition|video|"
    r"communications|operations|manager|administrative|equipment|analyst|"
    r"player development|academic|compliance|ticket|marketing|creative", re.I)
COACHING = re.compile(r"\bcoach\b|recruiting coordinator|coordinator of recruiting", re.I)


def is_coaching_title(title):
    t = title or ""
    return bool(COACHING.search(t)) and not NOT_COACHING.search(t)


# --------------------------------------------------------------------------
# The department staff directory, one sport's section
#
# Coaches pages are not always complete: JMU's baseball page leaves out its
# assistant pitching coach, who is listed only in the department directory
# under "Baseball". So the directory's section for the sport is read too, and
# anyone missing from the coaches page is added -- marked as coming from the
# directory. Never the whole directory: that is hundreds of people, nearly all
# of them in other sports.
# --------------------------------------------------------------------------

_TAGS = re.compile(r"<[^>]+>")


def _text(fragment):
    return " ".join(html.unescape(_TAGS.sub(" ", fragment)).split())


def _sport_heading(text, sport):
    return bool(re.search(r"\b" + re.escape(sport) + r"\b", text or "", re.I))


def directory_section(page_html, sport, source_url):
    """People listed under the sport's heading in a staff directory."""
    out = []
    # Newer Sidearm: <h3 ... staff-directory...__title>Baseball</h3>, then cards.
    titles = list(re.finditer(r'<h3[^>]*staff-directory[^>]*__title[^>]*>(.*?)</h3>', page_html, re.S))
    if titles:
        for n, m in enumerate(titles):
            if not _sport_heading(_text(m.group(1)), sport):
                continue
            end = titles[n + 1].start() if n + 1 < len(titles) else len(page_html)
            section = page_html[m.end():end]
            starts = [c.start() for c in re.finditer(r"s-person-card__content__person-details", section)]
            for k, st in enumerate(starts):
                card = section[st: starts[k + 1] if k + 1 < len(starts) else len(section)]
                name = re.search(r'aria-label="([^"]+?) full bio"', card)
                pos = re.search(r's-person-details__position[^>]*>(.*?)</div>\s*</div>', card, re.S)
                mail = re.search(r'href=["\']mailto:([^"\'?]+)', card)
                tel = re.search(r'href=["\']tel:[^"\']*["\'][^>]*>([^<]+)<', card)
                if not name:
                    continue
                title = _text(pos.group(1)) if pos else ""
                title = re.split(r"\s*ASSIGNED SPORTS", title, flags=re.I)[0].strip()
                out.append({
                    "name": html.unescape(name.group(1)).strip(),
                    "title": title,
                    "email": html.unescape(mail.group(1)).strip() if mail else "",
                    "phone": tel.group(1).strip() if tel else "",
                })
        return out
    # Older Sidearm: a category row, then member rows beneath it.
    category, rows = "", re.finditer(r"<tr([^>]*)>(.*?)</tr>", page_html, re.S)
    for r in rows:
        attrs, body = r.group(1), r.group(2)
        if "sidearm-staff-category" in attrs:
            category = _text(body)
            continue
        if "sidearm-staff-member" not in attrs or not _sport_heading(category, sport):
            continue
        cells = [_text(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", body, re.S)]
        mail = re.search(r'href=["\']mailto:([^"\'?]+)', body)
        phone = next((PHONE_RE.search(c).group(0) for c in cells if PHONE_RE.search(c)), "")
        if not cells or not cells[0]:
            continue
        out.append({"name": cells[0], "title": cells[1] if len(cells) > 1 else "",
                    "email": html.unescape(mail.group(1)).strip() if mail else "", "phone": phone})
    return out


def school_coaches(site, sport):
    """Coaching staff for one sport, from the school's own athletics site.

    The sport's coaches page first. Then the department staff directory's
    section for that sport, to catch anyone the coaches page leaves out. If
    neither has a section for the sport, nothing is guessed from the rest of
    the site."""
    site = _normalize_site(site)
    if not site:
        return {"ok": False, "error": {"code": "no_site", "message": "No athletics website to read."}, "coaches": []}
    sport = (sport or "softball").lower()
    coaches_url = f"{site}/sports/{sport}/coaches"
    directory_url = f"{site}/staff-directory"

    people, sources = [], []
    page, _ = fetch(coaches_url)
    if page:
        found = sidearm_coaches(page, coaches_url)
        if found:
            people.extend(found)
            sources.append(coaches_url)

    dpage, _ = fetch(directory_url)
    if dpage:
        extra = directory_section(dpage, sport, directory_url)
        known_emails = {c["email"].lower() for c in people if c["email"]}
        known_names = {c["name"].lower() for c in people}
        added = 0
        for d in extra:
            match = next((c for c in people if c["name"].lower() == d["name"].lower()), None)
            if match:
                if not match["email"] and d["email"]:
                    match["email"] = d["email"]          # directory fills a gap on the coaches page
                if not match["phone"] and d["phone"]:
                    match["phone"] = d["phone"]
                continue
            if (d["email"] and d["email"].lower() in known_emails) or d["name"].lower() in known_names:
                continue
            people.append({**d, "profile_url": "", "source_url": directory_url, "needs_verification": True,
                           "support_staff": False, "group": sport.title(), "from_directory": True})
            added += 1
        if added or extra:
            sources.append(directory_url)

    if not people:
        return {"ok": False, "site": site, "coaches": [],
                "error": {"code": "not_found",
                          "message": f"Couldn't find a {sport} coaching staff on {site}.",
                          "hint": "Open the site in a browser, find the coaches page, and use “Type one in”."}}

    for c in people:
        c["is_coach"] = is_coaching_title(c.get("title")) and not c.get("support_staff")
        c.setdefault("from_directory", False)
    people.sort(key=lambda c: (not c["is_coach"], c.get("from_directory", False)))
    missing = [c["name"] for c in people if c["is_coach"] and not c["email"]]
    coaches = sum(1 for c in people if c["is_coach"])
    note = (f"{coaches} coach{'es' if coaches != 1 else ''} found. Other staff — managers, trainers, "
            "operations — are listed below them, unticked. Check each name on the school’s page before writing.")
    if missing:
        note += (f" {len(missing)} coach{'es have' if len(missing) != 1 else ' has'} no email published; "
                 "left blank rather than guessed.")
    return {"ok": True, "site": site, "source_url": sources[0], "sources": sources,
            "coaches": people, "missing_email": missing, "note": note}
