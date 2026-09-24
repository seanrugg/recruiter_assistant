"""
The local app. Double-clicking the installed icon runs this and opens a browser
at http://127.0.0.1:8770.

Everything stays on this computer: the GameChanger password is typed here and
exchanged for a session token that is written to the app's data folder  and never
sent anywhere else; the athlete's record and coach list are JSON files in the
same folder; the AI key is in settings.json.

The one thing that does leave, if the family chooses a cloud assistant, is the
text of the draft prompt -- her stats, her school, her schedule. The settings
screen says so, and choosing Ollama means nothing leaves at all.

Bound to 127.0.0.1 deliberately. This is not a server for other people.
"""

import os
import json
import webbrowser
import threading
import pathlib

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import llm
from . import campaign
from . import coach_finder
from . import profiles as profile_links
from .gc_client import GameChangerClient, load_config, NotConfigured, AuthExpired, TOKEN_FILE, CONFIG_DIR

from .paths import static_dir, data_dir

STATIC = static_dir()

app = FastAPI(title="Recruiting Desk")

BASE_URL, ENDPOINTS, _RULES, CFG = load_config()
gc = GameChangerClient(BASE_URL, ENDPOINTS)

# The UI's three collections map onto the files the MCP server also reads, so an
# assistant driving the tools and a parent clicking the app see the same data.
FILES = {"athletes": "athletes.json", "targets": "programs.json", "config": "contact_rules_store.json"}


def _read(collection):
    name = FILES.get(collection)
    if not name:
        raise HTTPException(404, f"No collection '{collection}'.")
    path = campaign.HOME / name
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        raise HTTPException(500, f"{path} is not valid JSON.")
    return data if isinstance(data, dict) else {}


def _write(collection, data):
    campaign.HOME.mkdir(parents=True, exist_ok=True)
    path = campaign.HOME / FILES[collection]
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tmp.replace(path)


# ---------------------------------------------------------------- data

@app.get("/api/db/{collection}")
def db_list(collection: str):
    return {"docs": _read(collection)}


class Doc(BaseModel):
    data: dict


@app.put("/api/db/{collection}/{doc_id}")
def db_set(collection: str, doc_id: str, body: Doc):
    docs = _read(collection)
    docs[doc_id] = body.data
    _write(collection, docs)
    return {"ok": True}


@app.delete("/api/db/{collection}/{doc_id}")
def db_delete(collection: str, doc_id: str):
    docs = _read(collection)
    docs.pop(doc_id, None)
    _write(collection, docs)
    return {"ok": True}


# ---------------------------------------------------------------- assistant

class Prompt(BaseModel):
    prompt: str
    max_tokens: int = 1400


@app.get("/api/settings")
def settings_get():
    s = llm.public_settings()
    s["gamechanger"] = {
        "connected": TOKEN_FILE.exists(),
        "endpoints_configured": sorted(k for k, v in ENDPOINTS.items() if v),
        "config_file": CFG.get("config"),
    }
    return s


class Settings(BaseModel):
    provider: str | None = None
    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None


@app.post("/api/settings")
def settings_set(body: Settings):
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    return llm.save_settings(patch)


@app.post("/api/llm/json")
def llm_json(body: Prompt):
    try:
        return {"ok": True, "data": llm.complete_json(body.prompt, max_tokens=body.max_tokens)}
    except llm.NotConfigured as e:
        return JSONResponse(status_code=409, content={"ok": False, "code": "not_configured", "message": str(e)})
    except llm.ProviderError as e:
        return JSONResponse(status_code=502, content={"ok": False, "code": "provider_error",
                                                      "message": str(e), "hint": e.hint})


@app.post("/api/llm/test")
def llm_test():
    try:
        out = llm.complete("Reply with exactly: ready", max_tokens=16, temperature=0)
        return {"ok": True, "reply": out.strip()[:80]}
    except llm.NotConfigured as e:
        return JSONResponse(status_code=409, content={"ok": False, "message": str(e)})
    except llm.ProviderError as e:
        return JSONResponse(status_code=502, content={"ok": False, "message": str(e), "hint": e.hint})


# ---------------------------------------------------------------- GameChanger

class Login(BaseModel):
    email: str
    password: str


@app.post("/api/gc/login")
def gc_login(body: Login):
    """Exchange a sign-in for a session token, on this machine only.

    The password is used for this one request and is never written to disk. Only
    the token it returns is kept, because that is all the app needs afterwards.

    The login path is not hardcoded -- fill 'login' under [endpoints] in
    config.toml from a request you have observed on your own account."""
    path = ENDPOINTS.get("login")
    if not path:
        return JSONResponse(status_code=409, content={
            "ok": False, "code": "not_configured",
            "message": "Sign-in is not set up in this build.",
            "hint": "Add the login path under [endpoints] in config.toml. Until then, "
                    "enter her stats by hand -- everything else in the app works."})
    import httpx
    url = path if path.startswith("http") else BASE_URL + "/" + path.lstrip("/")
    try:
        r = httpx.post(url, json={"email": body.email, "password": body.password}, timeout=30.0)
    except httpx.HTTPError as e:
        return JSONResponse(status_code=502, content={"ok": False, "message": f"Could not reach GameChanger: {e}"})
    if r.status_code in (400, 401, 403):
        return JSONResponse(status_code=401, content={
            "ok": False, "code": "bad_credentials",
            "message": "GameChanger did not accept that email and password."})
    if r.status_code >= 400:
        return JSONResponse(status_code=502, content={"ok": False, "message": f"GameChanger returned {r.status_code}."})
    body_json = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    token = body_json.get("token") or body_json.get("access_token") or body_json.get("session_token")
    if not token:
        return JSONResponse(status_code=502, content={
            "ok": False, "message": "Signed in, but no session token came back.",
            "hint": "The response shape differs from what this build expects. Check the login endpoint."})
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(token.strip())
    try:
        TOKEN_FILE.chmod(0o600)
    except OSError:
        pass
    return {"ok": True, "connected": True}


@app.post("/api/gc/disconnect")
def gc_disconnect():
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()
    return {"ok": True, "connected": False}


@app.get("/api/gc/{name}")
def gc_get(name: str, team_id: str = "", player_id: str = "", game_id: str = ""):
    params = {k: v for k, v in
              {"team_id": team_id, "player_id": player_id, "game_id": game_id}.items() if v}
    try:
        return {"ok": True, "data": gc.get(name, **params)}
    except AuthExpired as e:
        return JSONResponse(status_code=401, content={"ok": False, "code": "auth_expired", "message": str(e)})
    except PermissionError as e:
        return JSONResponse(status_code=402, content={"ok": False, "code": "premium_required", "message": str(e)})
    except NotConfigured as e:
        return JSONResponse(status_code=409, content={"ok": False, "code": "not_configured", "message": str(e)})
    except LookupError as e:
        return JSONResponse(status_code=404, content={"ok": False, "code": "not_found", "message": str(e)})


# ---------------------------------------------------------------- profile links

@app.get("/api/profile/inspect")
def profile_inspect(url: str):
    """Recognize a pasted profile or social link, and read it where the platform allows."""
    return profile_links.inspect(url)


# ---------------------------------------------------------------- coach data

@app.get("/api/coaches/read")
def coaches_read(url: str, sport: str = ""):
    return coach_finder.find_coaches(url, sport)


@app.get("/api/coaches/find")
def coaches_find(site: str, sport: str = ""):
    return coach_finder.find_directory(site, sport)


# ---------------------------------------------------------------- the page

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


if STATIC.exists():
    app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.post("/api/app/quit")
def app_quit():
    """Stop the app. A windowed build has no console to close, so this is the off switch."""
    threading.Timer(0.4, lambda: os._exit(0)).start()
    return {"ok": True}


@app.get("/api/app/ping")
def app_ping():
    return {"app": "recruiting-desk", "data_dir": str(data_dir())}


def _already_running(port):
    """If a copy is already up, reuse it rather than failing on a busy port."""
    import httpx
    try:
        r = httpx.get(f"http://127.0.0.1:{port}/api/app/ping", timeout=1.5)
        return r.status_code == 200 and r.json().get("app") == "recruiting-desk"
    except Exception:
        return False


def main():
    import uvicorn
    port = int(os.environ.get("RECRUITING_DESK_PORT", "8770"))
    url = f"http://127.0.0.1:{port}"
    if _already_running(port):
        webbrowser.open(url)
        return
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    # log_config=None: a windowed build has no stdout, and uvicorn's default
    # logging config writes to it and crashes on startup.
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning", log_config=None)


if __name__ == "__main__":
    main()
