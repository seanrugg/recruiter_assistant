# Security

Recruiting Desk handles information about minors, and optionally a GameChanger
session and AI provider keys. Please report security problems privately.

**Do not open a public issue for a vulnerability.** Use GitHub's
[private vulnerability reporting](../../security/advisories/new) instead.

## Design commitments

- The app listens on `127.0.0.1` only.
- Secrets (AI keys, GameChanger session) are stored in the user's own profile
  folder and never returned to the browser.
- A GameChanger password is used once to obtain a session and is never written
  to disk.
- There is no Recruiting Desk server and no telemetry.
