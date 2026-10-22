<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
-->

# Session handoffs

A handoff is a short, dated snapshot that lets a **new chat** pick up the work without the old
conversation. Write one whenever the owner asks (`/handoff` in Claude Code), and before a long
context is compacted.

**Rule: only the newest file here is live.** Everything older is history. Never act on the open items
of a superseded handoff without checking them against the newest one and the code.

| Handoff | Status |
|---------|--------|
| [`HANDOFF_2026-10-22.md`](HANDOFF_2026-10-22.md) | **LIVE.** Phase 1 (set 1) run and scored, agreed units only, no adjudication; runners committed locally in signalguard and unigue; nothing pushed |

## Template

Name the file `HANDOFF_YYYY-MM-DD.md` (add `-b`, `-c` for a second one on the same day), add it at
the top of the table above, and mark the previous LIVE row "Superseded".

1. **State of `main`.** Last merged PR, anything uncommitted, anything still running.
2. **What was done this session.** Files and PRs, one line each.
3. **Open decisions for the owner.** Numbered. Say what each one blocks.
4. **Next steps.** Ordered. Give the exact command where there is one. Mark which ones the owner
   runs (long pipelines are never launched by Claude).
5. **Traps.** Things a fresh session would get wrong.
6. **Pointers.** The 3–6 files to read first.

Every number must come from a file in the repo or under `out/`. Name the file.
