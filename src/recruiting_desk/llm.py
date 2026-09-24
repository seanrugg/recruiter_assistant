"""
Whichever assistant the family already pays for -- or none of them.

Four of the five supported providers speak OpenAI's chat-completions format, so
there are two adapters here, not five. Adding LM Studio, Groq, OpenRouter or
anything else OpenAI-shaped is a line in PROVIDERS, not new code.

Where the data goes differs per provider, and the app says so plainly rather
than burying it: with a cloud provider, her name, school, stats and the field
she will be standing on Saturday are sent to that company. With Ollama nothing
leaves the machine. That is a real choice for a family to make about a sixteen-
year-old, not a technical detail.

API keys live in the app's data folder settings.json on this machine, mode 600.
"""

import os
import json
import pathlib

import httpx

from .paths import data_dir

HOME = data_dir()
SETTINGS = HOME / "settings.json"

PROVIDERS = {
    "anthropic": {
        "label": "Claude",
        "kind": "anthropic",
        "base_url": "https://api.anthropic.com",
        "default_model": "claude-sonnet-4-5",
        "needs_key": True,
        "data_leaves_machine": True,
        "key_hint": "From console.anthropic.com",
    },
    "openai": {
        "label": "ChatGPT",
        "kind": "openai",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o",
        "needs_key": True,
        "data_leaves_machine": True,
        "key_hint": "From platform.openai.com",
    },
    "grok": {
        "label": "Grok",
        "kind": "openai",
        "base_url": "https://api.x.ai/v1",
        "default_model": "grok-4",
        "needs_key": True,
        "data_leaves_machine": True,
        "key_hint": "From console.x.ai",
    },
    "ollama": {
        "label": "Ollama (on this computer)",
        "kind": "openai",
        "base_url": "http://localhost:11434/v1",
        "default_model": "llama3.1:8b",
        "needs_key": False,
        "data_leaves_machine": False,
        "key_hint": "No key needed. Ollama must be running.",
    },
    "openwebui": {
        "label": "Open WebUI",
        "kind": "openai",
        "base_url": "http://localhost:3000/api",
        "default_model": "",
        "needs_key": True,
        "data_leaves_machine": False,
        "key_hint": "API key from Open WebUI, Settings -> Account",
    },
}


def load_settings():
    if not SETTINGS.exists():
        return {"provider": "", "model": "", "api_key": "", "base_url": ""}
    try:
        return json.loads(SETTINGS.read_text())
    except json.JSONDecodeError:
        return {"provider": "", "model": "", "api_key": "", "base_url": ""}


def save_settings(data):
    HOME.mkdir(parents=True, exist_ok=True)
    current = load_settings()
    current.update(data)
    SETTINGS.write_text(json.dumps(current, indent=2))
    try:
        SETTINGS.chmod(0o600)
    except OSError:
        pass
    return public_settings()


def public_settings():
    """Settings safe to hand to the UI -- never the key itself."""
    s = load_settings()
    pid = s.get("provider", "")
    p = PROVIDERS.get(pid, {})
    return {
        "provider": pid,
        "label": p.get("label", ""),
        "model": s.get("model") or p.get("default_model", ""),
        "base_url": s.get("base_url") or p.get("base_url", ""),
        "has_key": bool(s.get("api_key")),
        "needs_key": p.get("needs_key", True),
        "data_leaves_machine": p.get("data_leaves_machine"),
        "configured": bool(pid and (s.get("api_key") or not p.get("needs_key", True))),
        "providers": [dict(v, id=k) for k, v in PROVIDERS.items()],
    }


class NotConfigured(Exception):
    pass


class ProviderError(Exception):
    def __init__(self, message, hint=""):
        super().__init__(message)
        self.hint = hint


def _resolved():
    s = load_settings()
    pid = s.get("provider", "")
    if not pid or pid not in PROVIDERS:
        raise NotConfigured("No AI assistant chosen yet. Pick one in Settings.")
    p = PROVIDERS[pid]
    key = s.get("api_key", "")
    if p["needs_key"] and not key:
        raise NotConfigured(f"{p['label']} needs an API key. {p['key_hint']}")
    return {
        "id": pid,
        "kind": p["kind"],
        "base_url": (s.get("base_url") or p["base_url"]).rstrip("/"),
        "model": s.get("model") or p["default_model"],
        "key": key,
        "label": p["label"],
    }


def complete(prompt, max_tokens=1400, temperature=0.7, timeout=180.0):
    """One turn, one string back. Same contract whichever provider is chosen."""
    cfg = _resolved()
    if not cfg["model"]:
        raise NotConfigured(f"No model set for {cfg['label']}. Name one in Settings.")
    try:
        if cfg["kind"] == "anthropic":
            return _anthropic(cfg, prompt, max_tokens, temperature, timeout)
        return _openai_compatible(cfg, prompt, max_tokens, temperature, timeout)
    except httpx.ConnectError:
        hint = ("Is Ollama running? Start it and try again."
                if cfg["id"] == "ollama" else
                f"Could not reach {cfg['base_url']}. Check the address in Settings.")
        raise ProviderError(f"No answer from {cfg['label']}.", hint)
    except httpx.TimeoutException:
        raise ProviderError(f"{cfg['label']} took too long.",
                            "A local model on a small machine can be very slow. Try a smaller model.")


def _anthropic(cfg, prompt, max_tokens, temperature, timeout):
    r = httpx.post(
        cfg["base_url"] + "/v1/messages",
        headers={"x-api-key": cfg["key"], "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": cfg["model"], "max_tokens": max_tokens, "temperature": temperature,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=timeout,
    )
    _check(r, cfg)
    body = r.json()
    return "".join(b.get("text", "") for b in body.get("content", []) if b.get("type") == "text")


def _openai_compatible(cfg, prompt, max_tokens, temperature, timeout):
    headers = {"content-type": "application/json"}
    if cfg["key"]:
        headers["Authorization"] = "Bearer " + cfg["key"]
    r = httpx.post(
        cfg["base_url"] + "/chat/completions",
        headers=headers,
        json={"model": cfg["model"], "max_tokens": max_tokens, "temperature": temperature,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=timeout,
    )
    _check(r, cfg)
    body = r.json()
    choices = body.get("choices") or []
    if not choices:
        raise ProviderError(f"{cfg['label']} returned nothing usable.", json.dumps(body)[:300])
    return choices[0].get("message", {}).get("content", "") or ""


def _check(response, cfg):
    if response.status_code in (401, 403):
        raise ProviderError(f"{cfg['label']} rejected the API key.", "Check or replace it in Settings.")
    if response.status_code == 404:
        raise ProviderError(f"{cfg['label']} does not know the model '{cfg['model']}'.",
                            "Check the model name in Settings.")
    if response.status_code == 429:
        raise ProviderError(f"{cfg['label']} is rate limiting or out of credit.", "Wait, or check the account.")
    if response.status_code >= 400:
        raise ProviderError(f"{cfg['label']} returned {response.status_code}.", response.text[:300])


def complete_json(prompt, **kwargs):
    """Same call, parsed as JSON. Tolerant of a code fence or a stray sentence.

    Small local models wrap JSON in chatter constantly, so this reads leniently
    rather than failing and making the family think the app is broken."""
    text = complete(prompt, **kwargs)
    return parse_json(text)


def parse_json(text):
    raw = (text or "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    if "```" in raw:
        chunk = raw.split("```", 2)
        if len(chunk) > 1:
            fenced = chunk[1]
            if fenced.startswith("json"):
                fenced = fenced[4:]
            try:
                return json.loads(fenced.strip())
            except json.JSONDecodeError:
                pass
    starts = [i for i in (raw.find("{"), raw.find("[")) if i != -1]
    ends = [i for i in (raw.rfind("}"), raw.rfind("]")) if i != -1]
    if starts and ends:
        try:
            return json.loads(raw[min(starts):max(ends) + 1])
        except json.JSONDecodeError:
            pass
    raise ProviderError("The assistant did not return a usable draft.",
                        "This usually means the model is too small for the task. Try a larger one. "
                        "First 200 characters: " + raw[:200])
