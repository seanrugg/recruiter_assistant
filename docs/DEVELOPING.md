# Developing

## Run from source

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pip install -e .

python -m recruiting_desk          # the app, opens a browser at 127.0.0.1:8770
python -m recruiting_desk --mcp    # the MCP server on stdio
pytest -q
```

Set `RECRUITING_DESK_HOME` to point the app at a scratch data folder so you
never touch a real campaign while developing.

## Layout

```
src/recruiting_desk/
  app.py           local web app (FastAPI), serves the UI and its API
  mcp_server.py    the same capabilities as MCP tools
  llm.py           provider adapters: Anthropic, and anything OpenAI-compatible
  profiles.py      link recognition, and reading public profile data
  coach_finder.py  college staff-directory parsing
  campaign.py      player, programs, outreach log, NCAA contact windows
  gc_client.py     authenticated GameChanger reads (optional)
  paths.py         per-OS data and resource locations
  static/          the UI; bridge.js lets it run against the local API
installer/
  recruiting_desk.spec   PyInstaller: builds the app and the MCP program
  recruiting_desk.iss    Inno Setup: builds the Windows installer
tests/                   offline tests; none of them touch the network
```

## Releasing

Push a version tag. GitHub Actions runs the tests, builds with PyInstaller on
Windows, wraps it with Inno Setup, and publishes
`RecruitingDesk-Setup-x.y.z.exe` and its checksum on the Releases page.

```bash
# bump version in pyproject.toml and src/recruiting_desk/__init__.py first
git tag v0.1.0
git push origin v0.1.0
```

To build on your own Windows machine instead:
`scripts\build_windows.ps1 -Version 0.1.0` (needs Inno Setup 6).

## Code signing

Releases are currently unsigned, so Windows SmartScreen warns on first run.
Signing with a code-signing certificate removes that. When a certificate is
available, add a `signtool sign` step after the PyInstaller build (sign both
`.exe` files) and again after Inno Setup (sign the installer).

## Rules the code keeps

These are the product, not style preferences. Please keep them in any change:

- Never state a number in an email that is not in the player's own record.
- Never write a scraped value to the record without the person accepting it.
- Never construct an email address from a naming pattern.
- Every GameChanger call is a GET.
- Nothing sends mail.
- No player data, real names or contact details in the repository, tests or
  issues. Use invented examples.
