<p align="center"><img src="docs/icon-256.png" width="96" alt=""></p>

# Recruiting Desk

Help a high school softball or baseball player write to college coaches — using
their own stats, their own schedule, and their own voice.

Recruiting Desk runs on your own computer. Nothing is uploaded to us, there is no
account to create, and no one else can see your player's information.

**[⬇ Download for Windows](../../releases/latest)** — then see the
[Windows install guide](docs/INSTALL-WINDOWS.md).

---

## What it does

1. **Paste your player's profile links** — GameChanger, FieldLevel,
   SportsRecruits, Hudl, YouTube. Their name, sport, class year, positions,
   height and hometown fill in from those pages.
2. **Add the coaches you want to write to.** It shows which ones NCAA rules let
   reply yet, based on class year and division.
3. **Pick the kind of email:**
   - **First email** — introduce the player to a coach who has never heard of them
   - **Coming up** — tell a coach where to find them at the next tournament
   - **Follow up** — nudge a coach who hasn't answered, with what's new
   - **Thank you** — for a coach who came and watched
4. **Read it, change what doesn't sound right, and send it** from the player's
   own email. Recruiting Desk writes drafts. The player sends them.

## What it will not do

- **Make up a number.** Every stat in an email has to come from the player's
  own record, with a source. A coach who checks one and finds it wrong stops
  reading.
- **Send anything on its own.** Coaches can tell when an email wasn't written
  by the athlete, and they delete those.
- **Guess.** Anything it reads off a web page is shown as a suggestion with
  where it came from. Nothing goes into the record until you accept it.

## Choosing the AI that writes the drafts

Recruiting Desk works with Claude, ChatGPT, Grok, or a model running on your
own computer through Ollama or Open WebUI. You choose in **Settings**.

**Where your player's information goes depends on that choice.** With Claude,
ChatGPT or Grok, the player's name, school, stats and schedule are sent to that
company each time a draft is written. With Ollama, nothing leaves your computer.
See [Privacy](docs/PRIVACY.md).

## Using it from Claude Desktop or another AI assistant

The installer also includes an MCP server, so an assistant you already use can
read the same player record and help draft. See
[Using with AI assistants](docs/USING-WITH-AI-ASSISTANTS.md).

## Where things are

| | Location |
|---|---|
| The app | `%LOCALAPPDATA%\Programs\RecruitingDesk` |
| Your player's data | `%APPDATA%\RecruitingDesk` |

Uninstalling removes the app and **keeps** the data, so reinstalling or
upgrading never loses a coach list. Delete that folder to remove it completely.

## For developers

See [Developing](docs/DEVELOPING.md) — running from source, tests, and how the
Windows installer is built and released.

## License

[MIT](LICENSE). Not affiliated with GameChanger, FieldLevel, SportsRecruits,
Hudl, the NCAA, or any AI provider.
