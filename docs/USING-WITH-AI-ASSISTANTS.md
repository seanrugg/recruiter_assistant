# Using Recruiting Desk with an AI assistant

The installer includes `recruiting-desk-mcp.exe`, an MCP server. An assistant
that speaks MCP can use it to read the same player record, coach list and
GameChanger profile that the app uses, and help draft emails.

It runs on your computer, reads the same data folder as the app, and every
GameChanger call it makes is read-only.

## Claude Desktop

**Settings → Connectors → Add → Local command** (if your version offers it), and
enter:

```
%LOCALAPPDATA%\Programs\RecruitingDesk\recruiting-desk-mcp.exe
```

Or edit `claude_desktop_config.json` directly
(**Settings → Developer → Edit Config**):

```json
{
  "mcpServers": {
    "recruiting-desk": {
      "command": "C:\\Users\\YOUR-NAME\\AppData\\Local\\Programs\\RecruitingDesk\\recruiting-desk-mcp.exe"
    }
  }
}
```

Restart Claude Desktop. Start a conversation with the **recruiting_session**
prompt — it carries the drafting rules.

### Why not the "Add custom connector" URL box?

That box connects Claude to a server on the internet, reached from Anthropic's
cloud. Recruiting Desk runs on your own computer and is not reachable from the
internet, on purpose. Use the local command option above.

## Open WebUI (with Ollama)

Open WebUI uses OpenAPI tool servers. Put `mcpo` in front of the MCP server:

```powershell
uvx mcpo --port 8000 -- "%LOCALAPPDATA%\Programs\RecruitingDesk\recruiting-desk-mcp.exe"
```

Then add `http://localhost:8000` under **Settings → Tools**.

Use a model of at least 8B parameters. Smaller models follow the "never invent a
statistic" rule unreliably, and that rule is the point of the whole tool.

## ChatGPT

ChatGPT's developer-mode connectors need an HTTP address:

```powershell
& "$env:LOCALAPPDATA\Programs\RecruitingDesk\recruiting-desk-mcp.exe" --http --port 8756
```

This is a network service on your computer while it runs. Keep it on
`localhost`, and stop it when you are done.

## What the assistant can do

| Tool | What it does |
|---|---|
| `athlete_get`, `athlete_save` | Read and update the player record |
| `profile_link_inspect` | Read a GameChanger, FieldLevel, SportsRecruits, Hudl or YouTube link. For GameChanger this includes season-by-season stats. |
| `program_list`, `program_save` | The coach list, with NCAA contact windows resolved |
| `coach_directory_find`, `coach_directory_read` | Pull coaching staff from a college athletics site |
| `draft_brief` | Everything needed to write one email, with sources |
| `outreach_log_entry`, `follow_ups_due` | What was sent, and who hasn't answered |

There is no tool that sends email. If your assistant has an email connection of
its own, the player record's **delivery** setting tells it whether to leave a
draft in the player's mailbox (the default) or send after approval.
