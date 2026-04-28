# Core context — ai-messager

## What it is

Local MCP server. Exposes web-based LLM chats (ChatGPT first; Gemini/DeepSeek later) to Claude as callable tools.

## Why it exists

Web chats hold per-user memory. Custom GPTs, project instructions, conversation history. Official APIs do not expose any of that. Users want Claude to consult these chats as "expert peers" during its own loop.

## What Claude sees

Tool names derived from config: `ask_<endpoint_name>`. Input: `{"message": str}`. Output: assistant reply text, trimmed. One config entry = one tool.

## What users see

Two CLI paths:
- `ai-messager login <provider>` once per provider. Visible browser, auto-detects successful sign-in, stores persistent profile.
- `ai-messager serve` spawned by Claude Desktop / Claude Code via MCP config. Never runs manually.

## Stack

| Concern | Choice |
|---|---|
| Language | Python 3.11+ |
| Browser | Playwright (async) + `launch_persistent_context` + `channel="chrome"` |
| MCP | `mcp` SDK v1.2+, low-level `Server` (dynamic tools from config) |
| Config | Pydantic v2, PyYAML |
| CLI | Typer + rich |
| Logging | structlog → JSON file + stderr mirror |
| Package mgr | uv |

## Scope (MVP)

In:
- ChatGPT web via Playwright.
- Pinned chat URL (persistent memory) OR fresh chat per call.
- One persistent profile per provider.
- stdio MCP transport.

Out:
- Official API bridges. Web only.
- Streaming partial replies to Claude.
- Concurrent calls to the same profile (serialized via asyncio lock).
- Multi-user / shared state.

## Relationship to other tools

- **Claude Code / Claude Desktop** spawn `ai-messager serve` as a subprocess. MCP stdio in/out.
- **ChatGPT web** is the backend. Playwright drives the UI in the user's persistent Chrome profile.
- **No external services.** No API keys. No cloud. All state on disk under `~/.ai_messager/`.

## Filesystem layout (per user)

```
~/.ai_messager/
├── config.yaml           # user-edited; lists endpoints
├── profiles/
│   └── chatgpt_web/      # Playwright persistent context (cookies, localStorage)
├── logs/
│   └── ai_messager.log   # structlog JSON
├── screenshots/          # debug artifacts from timeouts
└── responses/            # reserved: overflow spills
```

## Version assumptions

- macOS 14+ primary target; Linux untested but plausible.
- Google Chrome installed (system channel). Fallback: bundled Chromium (`browser_channel=""`).
- ChatGPT web circa 2026 Q2 DOM. Selectors WILL break when OpenAI reshuffles — see `code/anti_patterns.md`.
