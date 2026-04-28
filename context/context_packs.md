# ai-messager — Context Packs

Preloaded sets for specific task types.
Rule: keep a session to 5-7 documents max.

---

## Debug Pack
*Use when: an ask_* tool hangs, times out, or returns wrong text.*

1. `debug/debug_guide.md`
2. `debug/debug_playbook.md`
3. `debug/system_risks.md`
4. `architecture/architecture.md`

---

## Architecture Pack
*Use when: adding a new provider (Gemini, DeepSeek) or changing MCP/session wiring.*

1. `architecture/architecture.md`
2. `architecture/decision_log.md`
3. `architecture/invariants.md`
4. `general/core_context.md`

---

## Code Pack
*Use when: fixing a bug or adding a feature inside existing code.*

1. `architecture/architecture.md`
2. `architecture/invariants.md`
3. `code/coding_standards.md`
4. `code/anti_patterns.md`

---

## Onboarding Pack
*Use when: you just cloned the repo and have never touched it.*

1. `general/core_context.md`
2. `general/mental_model.md`
3. `architecture/architecture.md`
4. `code/coding_standards.md`

---

## How to use

Start a Claude session with:
> "Load [Pack Name] for ai-messager"

Example:
> "Load Debug Pack for ai-messager. Symptom: stage=generation_start timeout."
