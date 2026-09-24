"""
Read-only HTTP client for a GameChanger account.

Two deliberate constraints:

1. Every request is a GET. There is no write path in this file, because
   nothing upstream enforces read-only and the tool should not be able to
   change a team's data by accident.

2. No endpoint paths are hardcoded. They live in config.toml under
   [endpoints], because this is an undocumented internal API and a path
   guessed from memory is worse than no path at all -- it returns a 404 that
   looks like "no data" and quietly becomes a missing stat in an email.
   Fill the map from requests you have actually observed on your own account.

Auth is a bearer token, read from GC_TOKEN or the app's data folder token.
Tokens expire and there is no refresh flow, so expiry is reported plainly
rather than retried.
"""

import os
import json
import time
import pathlib
import urllib.parse

import httpx

from .paths import data_dir

CONFIG_DIR = data_dir()
TOKEN_FILE = CONFIG_DIR / "token"


class NotConfigured(Exception):
    """An endpoint template is missing from config.toml."""


class AuthExpired(Exception):
    """The token is absent, rejected, or expired. Re-auth needed."""


class GameChangerClient:
    def __init__(self, base_url, endpoints, timeout=20.0):
        self.base_url = base_url.rstrip("/")
        self.endpoints = endpoints or {}
        self._timeout = timeout
        self._client = None
        self._last_status = None

    # -- token ------------------------------------------------------------

    def token(self):
        tok = os.environ.get("GC_TOKEN", "").strip()
        if tok:
            return tok
        if TOKEN_FILE.exists():
            tok = TOKEN_FILE.read_text().strip()
            if tok:
                return tok
        raise AuthExpired(
            "No GameChanger token found. Put one in GC_TOKEN, or write it to "
            f"{TOKEN_FILE}. Tokens expire and there is no refresh flow, so this "
            "will need doing again periodically."
        )

    def auth_status(self):
        """Cheap local check -- does not spend a request."""
        try:
            tok = self.token()
        except AuthExpired as e:
            return {"ok": False, "reason": str(e)}
        return {
            "ok": True,
            "source": "GC_TOKEN" if os.environ.get("GC_TOKEN") else str(TOKEN_FILE),
            "token_length": len(tok),
            "last_response_status": self._last_status,
        }

    # -- requests ---------------------------------------------------------

    def _http(self):
        if self._client is None:
            self._client = httpx.Client(timeout=self._timeout, follow_redirects=True)
        return self._client

    def path_for(self, name, **params):
        tmpl = self.endpoints.get(name)
        if not tmpl:
            raise NotConfigured(
                f"No endpoint configured for '{name}'. Add it under [endpoints] in "
                "config.toml, using a path you have observed on your own account. "
                "Until then, this data has to be entered by hand."
            )
        try:
            return tmpl.format(**{k: urllib.parse.quote(str(v), safe="") for k, v in params.items()})
        except KeyError as e:
            raise NotConfigured(f"Endpoint '{name}' needs a value for {e}.")

    def get(self, name, **params):
        """GET a configured endpoint. Query params go in params['query'] as a dict."""
        query = params.pop("query", None)
        path = self.path_for(name, **params)
        url = path if path.startswith("http") else self.base_url + "/" + path.lstrip("/")
        headers = {
            "Authorization": "Bearer " + self.token(),
            "gc-token": self.token(),
            "Accept": "application/json",
        }
        r = self._http().get(url, headers=headers, params=query)
        self._last_status = r.status_code
        if r.status_code in (401, 403):
            raise AuthExpired(
                f"GameChanger rejected the token ({r.status_code}). It has most likely "
                "expired -- sign in again and replace it. Nothing was read."
            )
        if r.status_code == 402 or (r.status_code == 200 and _looks_paywalled(r)):
            raise PermissionError(
                "This account can see the team but not this data. Box scores, clips and "
                "streams need Premium on a parent or fan account. Enter these figures by hand."
            )
        if r.status_code == 404:
            raise LookupError(f"Nothing at {url} ({r.status_code}). Check the id, or the endpoint template.")
        r.raise_for_status()
        try:
            return r.json()
        except json.JSONDecodeError:
            raise RuntimeError(f"Expected JSON from {url}, got {r.headers.get('content-type')}.")


def _looks_paywalled(response):
    try:
        body = response.json()
    except Exception:
        return False
    if isinstance(body, dict):
        for key in ("paywalled", "requires_premium", "subscription_required"):
            if body.get(key):
                return True
    return False


def load_config(path=None):
    """Read config.toml. Returns (base_url, endpoints, rules, paths)."""
    try:
        import tomllib
    except ModuleNotFoundError:  # py < 3.11
        import tomli as tomllib

    cfg_path = pathlib.Path(path) if path else (CONFIG_DIR / "config.toml")
    if not cfg_path.exists():
        return ("https://api.team-manager.gc.com", {}, {}, {"config": str(cfg_path), "found": False})
    data = tomllib.loads(cfg_path.read_text())
    gc = data.get("gamechanger", {})
    return (
        gc.get("base_url", "https://api.team-manager.gc.com"),
        data.get("endpoints", {}),
        data.get("contact_rules", {}),
        {"config": str(cfg_path), "found": True, "loaded_at": time.time()},
    )
