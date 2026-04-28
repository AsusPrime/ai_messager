# Architecture

## Module layout

```
src/ai_messager/
├── cli.py              # Typer entry: login / serve / status / doctor
├── config.py           # Settings (env) + AppConfig (YAML)
├── server.py           # MCP stdio: list_tools + call_tool
├── errors.py           # Typed domain errors
├── logging_.py         # structlog config (JSON file + stderr)
├── bridges/
│   ├── base.py         # LLMBridge ABC
│   ├── registry.py     # provider_name → bridge class
│   └── chatgpt_web.py  # ChatGPTBridge impl
├── browser/
│   ├── session.py      # BrowserSession: one persistent context, lock, reused Page
│   └── manager.py      # BrowserManager: provider → BrowserSession
└── selectors/
    └── chatgpt.py      # all ChatGPT DOM selectors, in one place
```

## Dependency direction

```
cli.py  →  server.py  →  bridges/  →  browser/  →  selectors/
   │          │             │            │
   └──────────┴─────────────┴────────────┴──→  config.py, errors.py, logging_
```

- Selectors know about Playwright `Page` only. Nothing else.
- Browser knows about Playwright. Nothing about bridges or servers.
- Bridges know about browser + selectors + errors. Nothing about MCP or CLI.
- Server knows about bridges + config. Nothing about Playwright directly.
- CLI knows about config + server + session (for login).

Violating this direction is the #1 way to make a refactor painful.

## Data flow: one MCP tool call

```
Claude ──stdio──▶ server.call_tool(name, args)
                         │
                         ▼ look up endpoint by name
                  endpoint = endpoints["gpt_architect"]
                  bridge   = bridges["chatgpt_web"]
                         │
                         ▼ bridge.ask(message, chat_url)
                  async with session.page():           ← lock acquired here
                      ensure_on(url)
                      guard(cloudflare, login)
                      composer.click + press_sequentially(msg)
                      click send (or Enter fallback)
                      wait_for_new_turn
                      poll text until stable 1.5 s
                         │
                         ▼
                  return reply.strip()
Claude ◀──stdio── TextContent(reply)
```

## Key shared objects

### `BrowserSession`
- Owns one `launch_persistent_context(user_data_dir=...)`.
- Holds exactly one `Page` and one `asyncio.Lock`.
- Exposes `async with session.page()` (locked) and `raw_page()` (unlocked, login flow only).
- Started lazily on first `page()` call. Closed explicitly by `BrowserManager.aclose()`.

### `BrowserManager`
- Lazy registry: provider name → `BrowserSession`.
- Survives the server process. One per MCP run.

### `LLMBridge`
- ABC with three class-level constants (`provider_name`, `home_url`, `default_chat_path`) and two abstract methods (`is_logged_in`, `ask`).
- Constructor takes a `BrowserSession` + `response_timeout_s`.
- Stateless beyond the injected session.

### `AppConfig` + `EndpointConfig`
- YAML file at `~/.ai_messager/config.yaml`.
- Each endpoint becomes one MCP tool: `ask_<endpoint.name>`.
- `chat_url` set → pinned chat; absent → fresh chat per call.

### `Settings`
- Pydantic `BaseSettings` with `AI_MESSAGER_` env prefix.
- Paths for profiles, logs, responses, screenshots.
- Tunables: `response_timeout_s`, `login_poll_interval_s`, `serve_headless`, `browser_channel`.

## Login flow (separate from ask flow)

```
cli.login(provider)
   │
   ▼ BrowserSession(headless=False, channel="chrome")
   ▼ session.start()
   ▼ raw_page.goto(home_url, wait_until="domcontentloaded")
   ▼ initial cookie snapshot → log
   ▼ if is_logged_in: close
   ▼ else: poll every 2 s, require 2 consecutive successes, dump cookie snapshot each tick
   ▼ on success: settle 3 s, close
```

`is_logged_in` is a pure cookie read. It NEVER navigates. The login flow does the single navigation up front. This avoids the "every 2 s we kick the user back to chatgpt.com mid-OAuth" trap.

## MCP surface

One tool per endpoint, generated at server startup:

```json
{
  "name": "ask_<endpoint.name>",
  "description": "<endpoint.description>",
  "inputSchema": {
    "type": "object",
    "properties": { "message": {"type": "string"} },
    "required": ["message"],
    "additionalProperties": false
  }
}
```

Runtime `message` only. Chat URL is config-time. Adding a new chat = new endpoint, not new argument.
