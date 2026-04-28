# Invariants

Rules that must hold at all times. Breaking any of these breaks the product.

---

## I-01: `serve` writes nothing to stdout except MCP frames

`configure_logging(..., stdio_server=True)` routes logs to file + stderr only. No `print(...)`, no `console.print` in the serve path or anything it imports at runtime. stdout stacks up MCP JSON-RPC messages; a stray byte kills the client.

## I-02: `is_logged_in` does not navigate

Pure read. Navigation in a poll loop during login flow would kick the user off the OAuth page every poll cycle. All nav happens in CLI code, before polling starts.

## I-03: One `BrowserSession` per provider, not per endpoint

Chrome locks its `user_data_dir`. Two sessions pointed at the same dir will fight. Registry is keyed by provider name.

## I-04: `BrowserSession.page()` is lock-protected

Playwright's `Page` is not re-entrant. Concurrent MCP tool calls must serialize. `raw_page()` bypasses the lock and is for login only.

## I-05: Chat URL comparison ignores trailing slash

`_ensure_on` compares `page.url.rstrip("/")` to `target.rstrip("/")`. ChatGPT appends / strips the slash inconsistently. Non-matching strings would force a pointless reload that drops composer focus.

## I-06: Endpoint names match `^[a-z][a-z0-9_]*$`

Enforced by Pydantic pattern on `EndpointConfig.name`. Tool name becomes `ask_<name>`; arbitrary strings would break MCP's tool-name constraints.

## I-07: Provider identifier must exist in `registry._REGISTRY`

Config validator enforces `Literal["chatgpt_web"]`. Adding a new provider means: new bridge file + new registry entry + new literal value. Skipping any of the three = config rejected or `ProviderNotRegistered` at runtime.

## I-08: Cookie values are never logged

Only names, domains, value lengths, and HTTP-only/secure flags. Logging a token-bearing cookie value would put auth material in plaintext log files.

## I-09: All user-facing strings in English

Code, comments, log keys, exception messages, CLI output. Project language for PRs and issues. Ukrainian stays in chat with the maintainer.

## I-10: No API keys or secrets in the repo

This service uses browser sessions; it has no legitimate reason to handle tokens. `.env.example` lists path / tuning vars only. Secret-ish settings (e.g., `response_timeout_s`) are not secret.

## I-11: `.mcp.json` path points to the absolute `uv` binary

GUI hosts (Claude Desktop) and bare-shell processes (Claude Code) may launch the server with minimal `PATH`. Using just `"uv"` risks "command not found" silently. The project's `.mcp.json` uses the absolute path.

## I-12: Selectors are a single module

Every DOM lookup for a provider is in `selectors/<provider>.py`. When ChatGPT reshuffles its DOM — which it does — one file changes. No selector strings scattered through bridges or services.
