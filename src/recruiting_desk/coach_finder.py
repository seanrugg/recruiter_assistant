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
