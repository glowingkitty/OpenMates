---
name: start
description: Obtain or reuse an isolated repository workspace before editing.
user-invocable: true
---

Run `python3 scripts/sessions.py start --mode <bug|feature|docs|testing>
--task "<outcome>"` before first mutation. Read-only work needs no session.
Use the returned workspace; subsequent commands infer the current Codex binding.
SSH/manual commands use the returned `--session`. Repeated starts reuse the
binding. Child agents reuse their parent's binding. Use `--full` only for a
deliberate context/diagnostic inspection. Shared policy is in `AGENTS.md`.
