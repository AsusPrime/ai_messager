# System risks

Known fragile surfaces. If you're about to build on top of one, read the entry first.

---

## R-01: ChatGPT DOM churn

**What**: OpenAI ships UI updates weekly. Selectors break. We already watched this happen for `stop-button`, `copy-turn-action-button`, and the Enter-submit behavior.

**Blast radius**: Any ask_* call fails; all endpoints down until fixed.

**Mitigation**:
- All selectors in ONE file: `selectors/chatgpt.py`.
- Prefer structural signals over specific testids (iframe src, role, attribute patterns).
- Prefer text stability over "button appears/disappears" for completion detection.

**If it happens**: Run `dev/ask.py` with a visible browser, open DevTools, update the single selector that broke.

---

## R-02: Cloudflare fingerprinting

**What**: Headless Chrome is flagged ~10× more often than headed. `HeadlessChrome` UA token, `navigator.webdriver`, missing codecs, WebGL vendor strings — any one of them can trigger a Turnstile.

**Blast radius**: Silent `composer_visible` timeouts. Users blame our code.

**Mitigation**:
- `channel="chrome"` (system Chrome, not bundled Chromium).
- UA override stripping `HeadlessChrome`.
- `--disable-blink-features=AutomationControlled`.
- Iframe-based CF detector surfaces the error cleanly instead of hanging.
- `AI_MESSAGER_SERVE_HEADLESS=false` as documented first-line remedy.

**Future options (not yet implemented)**: `patchright` drop-in (driver-level stealth), `tf-playwright-stealth`.

---

## R-03: NextAuth cookie schema

**What**: `__Secure-next-auth.session-token` is chunked (`.0`, `.1`, …) when the JWT exceeds ~4 KB. Naively matching the exact name misses chunks. If OpenAI migrates off NextAuth entirely, the cookie name changes.

**Blast radius**: `is_logged_in` always False → login flow stuck / `NotLoggedIn` on every call.

**Mitigation**: Detector matches both exact name and `<base>.<n>` prefix. Login CLI dumps full cookie snapshot to log so a name change is a one-look diagnosis.

---

## R-04: Per-profile Chrome lock

**What**: Chrome locks `user_data_dir` on boot. Running `ai-messager login` while `ai-messager serve` is active against the same profile fails.

**Blast radius**: Login command errors out; users don't know why.

**Mitigation**: None yet. Documented in `debug_playbook`. Future option: detect running subprocess and emit a friendly error.

---

## R-05: Streaming pauses longer than `_STREAM_STABLE_MS`

**What**: Text-stability polling concludes "done" after 1.5 s of no change. If ChatGPT pauses mid-stream for 1.5+ s (rare but possible on slow generations or tool-use turns), we cut early.

**Blast radius**: Replies truncated without error.

**Mitigation**: Threshold chosen conservatively; so far no reports. If reports come: raise to 2500 ms in `bridges/chatgpt_web.py::_STREAM_STABLE_MS` and re-evaluate.

---

## R-06: MCP host spawn order + env vars

**What**: Claude Desktop / Claude Code spawn our subprocess with whatever env they had when they started. Changing `AI_MESSAGER_*` mid-session does nothing.

**Blast radius**: Users change env, nothing happens, they report "your tool is broken".

**Mitigation**: `debug_guide` documents the restart requirement. Error messages point there. No mitigation in code possible.

---

## R-07: GUI hosts have no PATH

**What**: `claude_desktop_config.json` with `"command": "uv"` fails silently on macOS because the GUI process has a minimal PATH.

**Blast radius**: Tools missing from Claude Desktop. Zero error surfaces to the user; `/mcp` lists the server as failed or absent.

**Mitigation**: Use the absolute path to `uv` in `claude_desktop_config.json` and in project-level `.mcp.json`. Enshrined in `invariants.I-11`.

---

## R-08: Concurrent tool calls on the same provider

**What**: Two endpoints on the same provider → same `BrowserSession` → shared `Page`. If Claude fires two `ask_gpt_*` calls in parallel, they race the Page.

**Blast radius**: Interleaved input, garbled replies, crashes mid-generation.

**Mitigation**: `asyncio.Lock` on `BrowserSession`. Second caller waits.

**Residual risk**: A single lock across many endpoints means tools on the same provider are sequential. Fine for a personal use case; a problem if someone wants parallel "consultations" across different pinned chats. Would require per-session state (multiple Pages, separate locks) — a deliberate future change, not a patch.

---

## R-09: stdout contamination during `serve`

**What**: Anything that writes to stdout kills the MCP JSON-RPC stream. Even a misplaced `console.print` hidden behind an error path is a time bomb.

**Blast radius**: MCP client drops the connection without a clear error on our side.

**Mitigation**: `configure_logging(..., stdio_server=True)` + coding standard forbidding `print` / `console.print` in serve paths. CI linter could enforce; currently only by review.
