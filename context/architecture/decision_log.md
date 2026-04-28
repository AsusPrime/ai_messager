# Decision log

Why each non-obvious choice was made. Update when reversing a decision.

---

## D-01: Playwright, not Selenium / Puppeteer / requests

Playwright has: async-first API, persistent contexts out of the box, auto-waiting locators, less boilerplate than Selenium. Node (Puppeteer) would fragment the stack. `requests` cannot drive a JS-heavy SPA like ChatGPT.

## D-02: MCP low-level `Server`, not `FastMCP`

FastMCP registers tools via decorators known at import time. We need tools generated from the user's YAML config at startup. Low-level `Server` supports dynamic `list_tools` and `call_tool` handlers.

## D-03: Cookie-based login detection, not DOM

First attempt checked "is Log in button invisible → logged in". Produced false positives during load — login button not rendered yet. Switched to: look for `__Secure-next-auth.session-token` cookie. DOM-timing independent.

Also: the cookie is chunked for large JWTs (`.session-token.0`, `.1`, …). Detector matches both exact name and `<base>.<n>` prefix.

## D-04: Single navigation in login flow, no polling re-nav

`is_logged_in` does not call `page.goto`. The login CLI navigates once before the poll loop. Polling that re-navigates kicks the user off `auth.openai.com` mid-OAuth.

## D-05: `channel="chrome"` (system Chrome), not bundled Chromium

Bundled Chromium has a distinct fingerprint (missing codecs, stock UA, `HeadlessChrome` token). Cloudflare flags it. System Chrome is a real installed browser, updated by Google, less suspicious.

## D-06: User-Agent override to strip `HeadlessChrome`

Even with `channel="chrome"`, headless adds `HeadlessChrome/<ver>` to the UA. CF treats that as automation. We hardcode a plain macOS Chrome UA string regardless of headless flag.

## D-07: `press_sequentially` over `fill` for composer

ChatGPT's composer is a ProseMirror contenteditable. `Locator.fill` sets value directly — ProseMirror's input handlers don't fire → React state doesn't update → Send button stays disabled.

`press_sequentially` dispatches per-character key events, which ProseMirror handles correctly.

## D-08: Click `Send` button, fallback to Enter

Enter-to-submit depends on a ChatGPT user setting ("Send with Enter" vs "with Shift+Enter"). Clicking the Send button sidesteps it. Fall back to Enter only if the Send testid isn't found (older UIs).

## D-09: Text-stability polling, not DOM-attribute completion detection

We tried:
1. `stop-button` disappears → truncated text ("Result l") because it flashes during streaming.
2. `copy-turn-action-button` appears → 120s timeout because testids keep changing.

Now: poll the new turn's `inner_text()` every 300 ms. Consider generation done when text is unchanged for 1500 ms. DOM-attribute independent.

## D-10: One bridge instance per provider, not per endpoint

Two `gpt_*` endpoints share the same ChatGPT profile. If we made a bridge per endpoint, we'd end up with multiple `BrowserSession`s fighting over the same `user_data_dir` (Chrome refuses parallel access to the same profile).

## D-11: `serve_headless` defaults to `true`, overridable via env

Default matches a quiet background server. Users who hit Cloudflare set `AI_MESSAGER_SERVE_HEADLESS=false`, solve the checkbox once, keep Chrome minimized.

## D-12: Debug artifacts (screenshot + HTML) on every Playwright timeout

One-shot dumps to `~/.ai_messager/screenshots/<timestamp>_<stage>.png`. Removes an entire class of "what was on screen?" back-and-forth. Cheap — only writes on failures.

## D-13: Response overflow spill gated by `AI_MESSAGER_DEBUG`

Default behavior: every reply returns inline regardless of length. When `AI_MESSAGER_DEBUG=true`, replies larger than `response_overflow_chars` (10 k default) get written to `~/.ai_messager/responses/<ts>_<tool>.md` and Claude receives a preview + path (via its `Read` tool).

Kept off by default because most replies are short and inline is the friendliest path. Flag gives a one-switch diagnostic mode when long-reply content needs inspection without flooding the main conversation.

## D-14: Stdout is sacred during `serve`

MCP uses stdout for JSON-RPC framing. `cli.serve` passes `stdio_server=True` to `configure_logging`, which disables the stderr/stdout `rich` console output for that mode. Any stray `print` there kills the protocol.
