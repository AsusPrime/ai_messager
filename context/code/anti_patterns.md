# Anti-patterns

Traps found the hard way during Phases B-D. Do not repeat.

---

## AP-01: "Log in button invisible → logged in"

**What went wrong**: DOM-based login check returned True before the page finished rendering because the login button wasn't mounted yet. Browser silently closed seconds after opening.

**Fix**: Cookie-based check. `__Secure-next-auth.session-token` (and chunked variants `.0`, `.1`, …) on `.chatgpt.com`. DOM-timing independent.

**Rule**: When the signal you want is auth state, look at auth artifacts (cookies, `/api/auth/session`), not at DOM decor.

---

## AP-02: Navigating inside a poll loop

**What went wrong**: `is_logged_in` called `page.goto(home_url)` when URL wasn't on chatgpt.com. During OAuth the user is on `auth.openai.com` or `accounts.google.com`. Every 2 s the login form got nuked.

**Fix**: `is_logged_in` is a pure read. All nav happens once, in CLI, before polling starts.

**Rule**: Polling predicates never mutate.

---

## AP-03: Matching Cloudflare by English text

**What went wrong**: `page.get_by_text("Verify you are human")` missed the localized (non-English) variant of the same CF prompt. Bridge dropped into `composer.wait_for` with a CF challenge blocking the DOM → 15 s timeout with no useful error.

**Fix**: Match the CF iframe by `src*="challenges.cloudflare.com"` or `title*="Cloudflare"`. URL is language-independent.

**Rule**: Match by structural / URL signal, not by localized user-visible text.

---

## AP-04: Using `stop-button disappears` as "generation done"

**What went wrong**: Stop button flashes in and out during streaming. `wait_for(state="hidden")` fires while tokens still stream, extractor returns partial text like `"Result l"`.

**Fix**: Poll the new turn's `inner_text()`, accept as stable when unchanged for 1500 ms.

**Rule**: Completion signals based on single DOM-attribute transitions are brittle. Text-stability is DOM-shape-independent.

---

## AP-05: Using `copy-turn-action-button` as "generation done"

**What went wrong**: Substituted `copy-turn-action-button` testid for the stop-button. ChatGPT removed/renamed that testid at some point. 120 s timeout every call.

**Fix**: Same as AP-04 — text stability.

**Rule**: Third-party testids are not a contract. Treat them as hints, not invariants.

---

## AP-06: `Locator.fill()` on a contenteditable

**What went wrong**: `composer.fill(message)` set the DOM text but did NOT fire the input events ProseMirror expects. React state stayed empty. Send button stayed disabled. Enter press did nothing. 15 s timeout on `generation_start`.

**Fix**: `composer.click()` (focus) → `composer.press_sequentially(message, delay=10)` (real key events).

**Rule**: Contenteditables and rich text editors (ProseMirror, Slate, Lexical, TinyMCE) need keyboard-level input. `fill` is textarea-semantics only.

---

## AP-07: Relying on `press("Enter")` to submit

**What went wrong**: ChatGPT has a user setting "Send with Enter" vs "Send with Shift+Enter". If user set the latter, Enter only inserts a newline. Message never sent.

**Fix**: Click the Send button. Fall back to Enter only if the Send testid is missing.

**Rule**: UI chrome (send/submit buttons) is more contractual than keyboard shortcuts.

---

## AP-08: Headless Chrome with default UA and viewport

**What went wrong**: Bundled headless Chrome UA contains `HeadlessChrome/<ver>`. CF's Turnstile flagged it almost every request.

**Fix**: Override UA to plain macOS Chrome 131. Add `--disable-blink-features=AutomationControlled`. Use `channel="chrome"`. Ship with `serve_headless=true` default but document `AI_MESSAGER_SERVE_HEADLESS=false` as the first-line CF remedy.

**Rule**: "Headless" leaks into multiple fingerprint surfaces (UA, WebGL vendor, `navigator.webdriver`, font list). Expect CF to catch any one of them.

---

## AP-09: Returning the whole reply inline for long texts

**What went wrong (expected, addressed in D-13)**: A 25 k-char architecture review blows Claude's context window in one shot.

**Fix**: Threshold-based spill to `~/.ai_messager/responses/<ts>_<tool>.md`; return preview + path.

**Rule**: Large tool outputs are usually addressable (Claude has `Read`), not inline-required.

---

## AP-10: Editing `rich.console.Console.print` calls in the serve path

**What went wrong**: `console.print` writes to stdout. stdout during `serve` is the MCP transport. One debug print kills the client's JSON parser.

**Fix**: `cli.serve` calls `configure_logging(..., stdio_server=True)`. Success path has zero `console.print` calls. Errors on config load go via `print(..., file=sys.stderr)`.

**Rule**: Never write to stdout during `serve`. When in doubt, use `log.info` (structlog → file + stderr).
