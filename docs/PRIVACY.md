# Privacy

Recruiting Desk is used for teenagers. This page says plainly what happens to
their information.

## What stays on your computer

Everything the app stores: the player record, the coach list, the record of what
was sent, your AI key, and any GameChanger session. It lives in
`%APPDATA%\RecruitingDesk` as ordinary files. There is no Recruiting Desk
server, no account, no analytics, and no telemetry. We never see any of it.

## What leaves your computer, and to whom

| When | Sent to | What |
|---|---|---|
| A draft is written with Claude, ChatGPT or Grok | Anthropic, OpenAI or xAI | The player's name, school, stats, schedule, the coach's name, and the writing sample |
| A draft is written with Ollama or a local Open WebUI | Nobody | Nothing leaves the computer |
| A profile link is pasted | That site (GameChanger, FieldLevel, etc.) | A request for that one public page |
| School search | The NCAA | One download of the public member directory, refreshed monthly |
| Coach lookup | That college's athletics website | A request for its public coaching staff page |

AI providers each have their own policies about what they keep and for how long.
If that matters to you, choose a local model.

## Things worth deciding deliberately

- **Social accounts.** Anything ticked "In emails" goes to adults the player has
  never met, alongside their name, school and where they will be playing. Social
  accounts start unticked.
- **Where they'll be playing.** "Coming up" emails name a field and a time. That
  is the point of them — and worth a moment's thought about who receives it.

## Deleting everything

Uninstall the app, then delete `%APPDATA%\RecruitingDesk`.
