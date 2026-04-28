# Debug playbook

Symptom → cause → fix. Look for your symptom in the left column.

---

## Login / session

### "Already signed in" closes the browser immediately, but you aren't signed in

**Cause**: Stale cookie from a DOM-based check that has since been replaced, OR you are re-running against a profile that legitimately HAS the session token cached. Hard to tell from outside.

**Fix**: Check the cookie snapshot:

```bash
grep cookie_snapshot ~/.ai_messager/logs/ai_messager.log | tail -1 | jq '.cookies[] | select(.name | startswith("__Secure-next-auth.session-token"))'
```

If the session token is missing or `value_len` < 100 → bug in `is_logged_in`. Open an issue with the snapshot attached.

---

### Login window never closes, even after you sign in

**Cause**: Cookie name schema changed. Detector looks for `__Secure-next-auth.session-token` (and chunked `.0`/`.1`/…). If OpenAI moves to a new scheme, we miss it.

**Fix**: Same cookie snapshot command as above. Look for any new cookie whose value is long (>100 chars), httpOnly, on `.chatgpt.com` — that's the new session token. Update `ChatGPTBridge._SESSION_COOKIE_BASE` accordingly.

---

### `NotLoggedIn` raised on an `ask_*` call

**Cause**: Cookies expired (NextAuth rotates them periodically) or the profile was deleted / moved.

**Fix**:
```bash
uv run ai-messager login chatgpt_web
```

Restart the Claude session after successful login so the MCP subprocess re-reads the profile.

---

## Cloudflare

### `CloudflareChallenge` raised

**Cause**: Turnstile widget detected on the page. Headless fingerprint failed CF's checks.

**Fix**: First try `AI_MESSAGER_SERVE_HEADLESS=false`, restart Claude, click the checkbox when it appears. `cf_clearance` cookie then covers the next 30-60 minutes across headless calls too.

If it still fires: the profile is probably flagged. Try re-login in visible mode and browse chatgpt.com manually for a few turns to warm the profile.

---

### Screenshot shows a localized (non-English) CF challenge prompt but no `CloudflareChallenge` was raised

**Cause**: Old selector was text-based. Fixed in commit that added iframe-based detection. If you still see it, you're on a stale build.

**Fix**: Ensure `selectors/chatgpt.py::cloudflare_prompt` is iframe-based (`challenges.cloudflare.com`). Rebuild and restart.

---

## Timeouts

### `LLMResponseTimeout stage=composer_visible`

**Cause**: The composer textbox didn't render within 15 s after navigation.

**Check in this order**:
1. Open the screenshot at the logged path. What's there?
   - CF iframe → see "Cloudflare challenge"
   - Login screen → see "NotLoggedIn"
   - Empty white page / network error → Chrome couldn't reach chatgpt.com; check connectivity
   - ChatGPT UI but no composer → a new UI variant; update `selectors/chatgpt.py::composer`
2. If no screenshot, verify `_capture_debug_artifact` is actually running — older builds lack it.

---

### `LLMResponseTimeout stage=generation_start`

**Cause**: Message was typed but no new assistant turn appeared within 15 s. Usually: send didn't fire.

**Check**:
- Screenshot composer — is the text still sitting in the input? Then send click failed.
- Is there a visible Send button at all in the screenshot? If not, ChatGPT reshuffled the submit UI.

**Fix**: Update `selectors/chatgpt.py::send_button`. Or extend `ask` to try `page.keyboard.press("Enter")` with a focus first.

---

### `LLMResponseTimeout stage=generation_end`

**Cause**: New turn appeared, text never stabilized for 1.5 s within `response_timeout_s`.

**Possibilities**:
1. ChatGPT is genuinely slow (long generation) — raise `AI_MESSAGER_RESPONSE_TIMEOUT_S`.
2. Stability threshold too tight — extend `_STREAM_STABLE_MS` in `bridges/chatgpt_web.py`.
3. A streaming ghost element keeps mutating (rare) — check the `.html` dump next to the screenshot.

---

## Extraction quality

### Tool returned "wrong" or suspiciously short text

**Step 1**: Check `reply_preview`:
```bash
tail -n 1 ~/.ai_messager/logs/ai_messager.log | jq '.reply_preview'
```

**Step 2**: Compare to what GPT actually wrote in the browser (open the pinned chat in normal Chrome).

Three cases:

| Preview matches browser | Preview differs | Preview empty/garbled |
|-------------------------|-----------------|----------------------|
| Chat's own behavior — custom instructions make it terse | Wrong-turn extraction | Selector matched chrome / toolbar |
| Edit chat's instructions | Use `.last` instead of `.nth(before)` | Tighten selector: `new_turn.locator(".markdown")` first |

---

### Reply includes button labels or UI chrome

**Cause**: `inner_text()` on the whole turn captured action-bar text after generation completed.

**Fix**: In `bridges/chatgpt_web.py`, replace `text = await new_turn.inner_text()` with:

```python
body = new_turn.locator(".markdown")
if await body.count() > 0:
    text = await body.first.inner_text()
else:
    text = await new_turn.inner_text()
```

---

## Claude-side mysteries

### Claude says "the tool is not available"

**Cause**: MCP server not registered or Claude client didn't pick up the config.

**Fix**:
- Claude Code (current directory): ensure `.mcp.json` exists at repo root. `/exit` and restart.
- Claude Desktop: ensure `~/Library/Application Support/Claude/claude_desktop_config.json` has `mcpServers.ai-messager`. Fully quit (⌘Q) and relaunch.
- Both: verify `command` is the ABSOLUTE path to `uv` (GUI hosts may not have it on PATH).

---

### Tool call results in "Tool timed out after Ns"

**Cause**: Claude has its own tool timeout (typically the first error you see is `LLMResponseTimeout` from our side — Claude's timeout only hits if something deeper hangs).

**Fix**: Look in our log first — if there's a `bridge_error` with a stage, fix the underlying issue. If our log has no matching `tool_call_done` OR `bridge_error` after `tool_call_start`, the subprocess hung; restart the Claude session.

---

## Environment

### Changes to code don't take effect

**Cause**: Claude Code / Desktop keeps the MCP subprocess alive across prompts. Your new code is on disk; the running process has the old bytes.

**Fix**: `/exit` then `claude` again (or fully quit Claude Desktop). No partial reload.

---

### New env var (e.g., `AI_MESSAGER_SERVE_HEADLESS`) isn't picked up

**Cause**: Env vars are captured when the subprocess is spawned. Setting them in your shell AFTER Claude started has no effect.

**Fix**: Export before starting Claude:

```bash
/exit
export AI_MESSAGER_SERVE_HEADLESS=false
claude
```
