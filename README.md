# ai-messager

Local MCP server that lets Claude (CLI/Desktop) talk to web-based LLM chats
(ChatGPT, Gemini, DeepSeek, ...) as if they were tools. Uses Playwright with a
persistent browser profile — no API keys, no cookie copying, just a one-time
login per provider.

## Status

MVP. Only the `chatgpt_web` provider is implemented end-to-end. See
`docs/OVERVIEW.md` for the architecture.

## Requirements

- Python 3.11+
- [`uv`](https://github.com/astral-sh/uv)
- Google Chrome installed (default `browser_channel: chrome`). Chromium or
  Edge work too — set `AI_MESSAGER_BROWSER_CHANNEL=chromium` (or `msedge`).

## Quick start

```bash
# install (uv manages the venv)
uv sync

# install the Chromium browser that Playwright will drive
uv run playwright install chromium

# copy the example config and edit it
mkdir -p ~/.ai_messager
cp config.example.yaml ~/.ai_messager/config.yaml
$EDITOR ~/.ai_messager/config.yaml

# one-time login — opens a visible browser, closes itself once you're in
uv run ai-messager login chatgpt_web

# sanity-check the bridge without going through MCP
uv run ai-messager ask gpt_fresh "ping" --show

# start the MCP server (stdio) — wire this into Claude Desktop/Code
uv run ai-messager serve
```

## Commands

| Command | What it does |
|---|---|
| `ai-messager login <provider>` | Open a non-headless browser and wait for the user to sign in. Auto-closes on detected login. |
| `ai-messager ask <endpoint> <message>` | Call a configured endpoint directly — no MCP, no Claude. Use `--show` to watch the browser. |
| `ai-messager serve` | Start the stdio MCP server. Registers one tool per configured endpoint. |
| `ai-messager status` | Show each endpoint plus its login state. |
| `ai-messager doctor` | Verify Playwright is installed, the profiles dir is writable, the config parses. |

## Wiring into Claude Code (project `.mcp.json`)

This repo already ships a project-level `.mcp.json` that registers the server
for Claude Code. Open the project in Claude Code and approve the server when
prompted. Adjust the absolute paths if you cloned to a different location:

```json
{
  "mcpServers": {
    "ai-messager": {
      "command": "/absolute/path/to/uv",
      "args": [
        "--directory",
        "/absolute/path/to/ai_messager",
        "run",
        "ai-messager",
        "serve"
      ]
    }
  }
}
```

## Wiring into Claude Desktop

Add to your Claude Desktop config:

```json
{
  "mcpServers": {
    "ai-messager": {
      "command": "uv",
      "args": ["run", "ai-messager", "serve"],
      "cwd": "/absolute/path/to/ai_messager"
    }
  }
}
```

Restart Claude. Tools are registered as `ask_<endpoint.name>` (e.g.
`ask_gpt_architect`, `ask_gpt_fresh`) based on `~/.ai_messager/config.yaml`.

## Runtime layout

Everything lives under `~/.ai_messager/` (override via `AI_MESSAGER_*` env vars):

| Path | Purpose |
|---|---|
| `config.yaml` | Endpoint definitions. |
| `profiles/<provider>/` | Persistent browser profile (cookies, session). |
| `logs/` | Server + bridge logs. |
| `responses/` | Spilled replies when `AI_MESSAGER_DEBUG=true` and reply exceeds `response_overflow_chars`. |
| `screenshots/` | Diagnostic screenshots on bridge errors. |

See `.env.example` and `src/ai_messager/core/config.py` for the full settings list.

## License

MIT.
