# ai-messager — Context Map

Navigation for this service's context files.
**For preloaded sets → use `context_packs.md`.**

---

## Quick start by task type

| Task | Pack to load |
|------|-------------|
| Something is broken | **Debug Pack** |
| Adding a new LLM provider / bridge | **Architecture Pack** |
| Feature or bug fix inside existing code | **Code Pack** |
| First time touching this repo | **Onboarding Pack** |

→ Full file lists in `context_packs.md`

---

## Folder structure

| Folder | Contents |
|--------|---------|
| `general/` | core_context, mental_model |
| `architecture/` | architecture, decision_log, invariants |
| `code/` | coding_standards, anti_patterns |
| `debug/` | debug_guide, debug_playbook, system_risks |

---

## One-line per file

| File | Purpose |
|------|---------|
| `general/core_context.md` | What ai-messager is, stack, scope |
| `general/mental_model.md` | How to think about bridges, sessions, MCP flow |
| `architecture/architecture.md` | Layers, data flow, file map |
| `architecture/decision_log.md` | Why each non-obvious choice was made |
| `architecture/invariants.md` | Rules that must never break |
| `code/coding_standards.md` | Language, style, comment policy |
| `code/anti_patterns.md` | Traps found the hard way, do-not-repeat list |
| `debug/debug_guide.md` | Where logs/screenshots live, env knobs, repro tools |
| `debug/debug_playbook.md` | Symptom → cause → fix table |
| `debug/system_risks.md` | Known fragility: CF, DOM churn, fingerprinting |
