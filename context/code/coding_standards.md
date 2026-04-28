# Coding standards

## Language

- Python 3.11+. Uses `from __future__ import annotations` everywhere for forward refs.
- All code, comments, log strings, error messages, CLI output in English.
- Tooling: `ruff` (format + lint), `mypy` (strict on `src/`), `pytest` + `pytest-asyncio`.

## Package manager

- `uv` only. Do not commit `pip` or `poetry` artifacts. Lockfile is `uv.lock`.
- Run anything via `uv run <cmd>` so the venv picks up correctly.

## Type hints

- All public functions typed. Private helpers typed when the inference is non-trivial.
- Prefer `Path` over `str` for filesystem paths.
- `Literal` for closed enums (e.g., `ProviderName = Literal["chatgpt_web"]`).
- No `Any` unless there's a third-party lib we can't type (then add a `# type: ignore[...]` with the code, not a blanket ignore).

## Imports

- `from __future__ import annotations` first, blank line, then stdlib, third-party, local — groups separated by a blank line. Enforced by `ruff --select I`.
- Absolute imports from `ai_messager.*`. No relative imports across packages.

## Comments

Default: no comment. Code names describe behavior.

Write a comment only when a reader could look at the code and ask "why this shape and not the obvious one". Explain the constraint:

```python
# ChatGPT's composer is a ProseMirror contenteditable, not a plain textarea.
# Locator.fill() bypasses ProseMirror's input handlers, so React state never
# updates and the Send button never enables. press_sequentially() dispatches
# real per-char input events.
await composer.click()
await composer.press_sequentially(message, delay=10)
```

Do not write:
- "Fills the composer" (code already says that)
- "Added in Phase C" / "Used by call_tool" (belongs in commit msg, rots)
- Mid-sentence ellipses or trailing "TODO" with no ticket

## Error handling

- Domain exceptions in `errors.py` inherit from `AIMessagerError`.
- Raise the typed exception; caller (server / CLI) decides how to surface it.
- Catch `PlaywrightTimeoutError` and re-raise as `LLMResponseTimeout(..., stage=...)` — the stage is the diagnostic.
- Never catch `Exception` at narrow scope. It's acceptable in best-effort utilities like `_capture_debug_artifact` where failing the dump must not cascade.

## Logging

- `structlog` via `get_logger(__name__)`.
- Events are lowercase underscore: `browser_session_started`, `tool_call_done`, `bridge_error`.
- Keys stable across call sites so they're greppable: `provider`, `tool`, `stage`, `url`, `screenshot`.
- Never log cookie values or message bodies verbatim (→ `invariants.I-08`). `reply_preview` capped at 500 chars is allowed and useful for diagnosing "wrong text" reports.

## Async

- Every bridge method is async. Every I/O helper is async.
- Never mix sync `time.sleep` with async flow. Use `asyncio.sleep` or `page.wait_for_timeout`.
- The one `asyncio.Lock` lives on `BrowserSession`. Do not add a second.

## Tests

- Unit tests: no browser, no network. `tests/unit/`.
- Integration tests (optional, manual): real logged-in profile. `tests/integration/`. Mark with `@pytest.mark.integration`.
- Keep unit tests under 1 s each. Sub-second the suite enables "run on save".

## File size

No hard limit, but a file above ~300 lines almost always means two concepts live there. Split.

## Public API surface

- CLI: `ai-messager login | serve | status | doctor`.
- MCP tools: `ask_<endpoint.name>`, input `{"message": str}`.
- Library imports are NOT public; no one should `import ai_messager.bridges.chatgpt_web` from another codebase.
