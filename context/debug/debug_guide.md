# Debug guide

Where to look and what to turn on when something breaks.

---

## Log file

```
~/.ai_messager/logs/ai_messager.log
```

structlog JSON, one event per line. Key events:

| Event | Where | Why it matters |
|-------|-------|---------------|
| `browser_session_started` | `browser/session.py` | Chrome booted with these flags |
| `browser_session_closed` | same | Chrome released; profile is safe to reopen |
| `cookie_snapshot` | `cli.py` (login) | Auth-cookie diagnostic; only on `login` |
| `tool_call_start` | `server.py` | MCP received a call |
| `tool_call_done` | `server.py` | Reply returned; includes `reply_preview` (first 500 chars) and `reply_chars` |
| `bridge_error` | `server.py` | Call failed; `error_type` + `error` explain |
| `debug_artifact_captured` | `bridges/chatgpt_web.py` | Screenshot saved on a timeout |

Quick follow-along:

```bash
tail -f ~/.ai_messager/logs/ai_messager.log | jq
```

---

## Screenshot directory

```
~/.ai_messager/screenshots/<timestamp>_<stage>.png
~/.ai_messager/screenshots/<timestamp>_<stage>.html
```

Dropped automatically on any `PlaywrightTimeoutError` in `ask`. Filename encodes the stage:

| Stage | Meaning |
|-------|---------|
| `composer_visible` | Composer did not render in 15 s → CF, login wall, or network |
| `generation_start` | No new assistant turn appeared 15 s after submit → message not sent (composer input / send button broken) |
| `generation_end` | Text never stabilized in `response_timeout_s` → ChatGPT hung, or stability threshold too tight |
| `cloudflare` | CF iframe detected before `composer_visible` wait |

Open the `.png`; read the `.html` if you need to know what selector to try.

---

## Environment switches

| Variable | Default | Effect |
|----------|---------|--------|
| `AI_MESSAGER_SERVE_HEADLESS` | `true` | `false` opens a visible Chrome — first remedy for CF challenges |
| `AI_MESSAGER_RESPONSE_TIMEOUT_S` | `120` | Per-call max wait for generation to stabilize |
| `AI_MESSAGER_BROWSER_CHANNEL` | `chrome` | `chromium` to use Playwright's bundled build; empty string for the same |
| `AI_MESSAGER_LOG_LEVEL` | `INFO` | `DEBUG` for very chatty structlog output |
| `AI_MESSAGER_PROFILES_DIR` | `~/.ai_messager/profiles` | Move the entire per-provider persistent state |
| `AI_MESSAGER_DEBUG` | `false` | `true` enables spill-to-file for replies over `response_overflow_chars` |
| `AI_MESSAGER_RESPONSE_OVERFLOW_CHARS` | `10000` | Threshold for spill-to-file when debug flag is on |

Env vars must be set BEFORE the MCP host spawns the server. For Claude Code:

```bash
/exit
export AI_MESSAGER_SERVE_HEADLESS=false
claude
```

Restarting the Claude session is mandatory — the old subprocess inherits old env.

---

## Faster iteration: `dev/ask.py`

Skip Claude entirely when debugging the bridge:

```bash
uv run python dev/ask.py chatgpt_web "What is 2+2?"
uv run python dev/ask.py chatgpt_web "..." --chat-url https://chatgpt.com/c/<id>
uv run python dev/ask.py chatgpt_web "..." --headless
```

Uses the exact same bridge code path as MCP. Visible browser by default. 10 s per cycle vs ~2 min of Claude restart dance.

---

## Checking login from the outside

Re-login refreshes cookies AND exposes the cookie snapshot in the log:

```bash
uv run ai-messager login chatgpt_web
```

If `is_logged_in` returns True immediately → cookie valid.
If it keeps polling → session expired.

---

## Reading `reply_preview`

When a tool "returned wrong text":

```bash
tail -n 1 ~/.ai_messager/logs/ai_messager.log | jq '.reply_preview'
```

Three buckets:
1. `reply_preview` matches what you saw in the browser → we extracted correctly; issue is the pinned chat's custom instructions (make GPT more verbose).
2. `reply_preview` is a different / shorter string → we read the wrong turn. Check `debug_playbook` entry "wrong turn extraction".
3. `reply_preview` is empty or contains only button labels → extractor failure. Open a selector issue.

---

## When the graph / tools seem wrong

Not applicable here — this service has no code-review-graph integration. Stick to `rg` / `grep` for source search.
