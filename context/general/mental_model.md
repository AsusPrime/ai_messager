# Mental model

## One-sentence summary

Claude talks to `ai-messager` via MCP; `ai-messager` talks to ChatGPT via a real Chrome window.

## Four layers, top to bottom

```
┌──────────────────────────────────────────────┐
│ Claude Desktop / Claude Code                 │  ← MCP client
└──────────────────────────────────────────────┘
                  │  JSON-RPC over stdio
┌──────────────────────────────────────────────┐
│ MCP server (src/ai_messager/server.py)       │  ← our code, entrypoint
└──────────────────────────────────────────────┘
                  │  in-process Python call
┌──────────────────────────────────────────────┐
│ LLMBridge (src/ai_messager/bridges/*.py)     │  ← per-provider driver
└──────────────────────────────────────────────┘
                  │  Playwright API
┌──────────────────────────────────────────────┐
│ Chrome + chatgpt.com                         │  ← the actual LLM
└──────────────────────────────────────────────┘
```

Each layer knows nothing about the one two levels up or down.
- `server.py` does not know what a `composer` or a `cf_clearance` cookie is.
- `ChatGPTBridge` does not know what MCP is.
- Selectors (`selectors/chatgpt.py`) do not know what a config endpoint is.

## Three primary nouns

**Provider.** Short string like `chatgpt_web`. Identifies which bridge class and which persistent profile directory.

**Endpoint.** A user-defined entry in `config.yaml`. Has: a name (becomes the MCP tool name), a provider, optionally a `chat_url`. Two endpoints pointing at the same provider share one browser profile.

**Session.** One `BrowserSession` = one Playwright persistent context = one reused `Page`. Serialized by an `asyncio.Lock`. Lives for the lifetime of the MCP server process.

## One ask_* call, end to end

1. Claude sends `tools/call` with `name="ask_gpt_architect"`.
2. `server.call_tool` strips the `ask_` prefix, looks up the endpoint, finds the provider, gets the bridge.
3. `bridge.ask(message, chat_url)` acquires the session lock, navigates if needed, submits message, waits for stream end, returns text.
4. Server wraps text in `TextContent` and returns to Claude.

## What persists vs what doesn't

**Persists on disk** (survives restart):
- Login cookies (via Playwright persistent context).
- Chat history (belongs to ChatGPT, not us).
- User config (`~/.ai_messager/config.yaml`).

**Lives only in server process memory:**
- Session locks, Playwright handles, bridge instances.

**Rebuilt on every call:**
- No caching of replies. Every `ask_*` re-runs the full flow.

## Why this shape

- Persistent profile + `channel="chrome"` keeps us looking like a human to Cloudflare.
- One bridge per provider (not per endpoint) means one login covers many tools.
- One lock per session prevents two concurrent calls from racing the shared Page.
- MCP stdio keeps us dead-simple — no ports, no auth, no lifecycle beyond parent process.
