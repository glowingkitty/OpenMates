# Git operations on a connected machine: options (open decision)

Status: open, for Marco's decision. Nothing in R5 is built and git is not routed through raw commands until
this is decided. Today one git operation already exists as a structured host operation: the assistant's
"commit these changes" becomes a `git_commit` request that the remote-access host runs in the chat's
worktree (Flow 2, commit 7b311a5).

## The options

**A. Dedicated Code app skills.** `git_status`, `git_diff`, `git_log`, `git_commit`, `git_land` (rebase onto
the target branch and fast-forward locally), `git_push`. Each has typed parameters, its own result embed
(diff view, commit card with message and files, push confirmation) and its own permission rule. The host
runs fixed git invocations it builds itself; the model never writes git argv.

**B. Through the command runtime.** The assistant runs `git status`, `git commit -m ...` and so on as
ordinary remote commands inside the sandbox tier (R3/R9), approved like any command or through a command list.

**C. Mixed.** Read-only git (status, diff, log) as skills with embeds; everything that changes history or
leaves the machine (commit, rebase, land, push) as skills with explicit rules; no git through raw commands.
(The reverse mix, reads through commands and writes as skills, gains little.)

## Comparison

| | A. Skills | B. Command runtime | C. Mixed |
|---|---|---|---|
| Works without sandbox setup (Ubuntu 24.04 before AppArmor setup) | Yes: host runs git itself, like file reads and writes | No: needs a usable sandbox tier | Yes |
| Hooks and repo config (`core.hooksPath`, `core.fsmonitor`, filters, credential helpers run code) | Host controls them: e.g. hooks off or run inside the sandbox by choice | Run inside the sandbox; `.git/config` must stay masked or read-only, still untested (open point R5) | As A |
| Push (network + credentials) | One exact-approval skill; credentials never enter the sandbox | Needs a network and credential profile for the sandbox | As A |
| What the user sees | Diff and commit embeds, readable on web, Apple and CLI | Terminal output text | Embeds for every step |
| Approval UX | Per-skill rules (commit after green tests automatic, push always asks) match the Plan's decisions | Every git call is a command review unless a list allows it; lists must match exact argv | As A |
| Model reliability | Typed fields; no flag mistakes | Free argv; easy to run the wrong flags (`--force`, `-A`) | As A |
| Cross-surface parity | One core operation per skill, reaches every shell | Generic, nothing per surface | As A |
| Build cost | Highest: host module, backend tools, embeds, tests for each op | Lowest: already covered by R3 once the sandbox is proven | Close to A |
| Flexibility (stash, cherry-pick, bisect, submodules) | Only what we build | Anything git can do | Add skills when needed; still no raw git |

## Recommendation for the discussion

C, close to A. It extends what already works (structured `git_commit`), works on machines without the
sandbox setup, keeps push behind one exact approval without giving the sandbox credentials, and gives
the user readable embeds on every surface. Cost: the per-skill build, and less flexibility for rare git
commands, which can be added one skill at a time. B is cheapest but makes every git step a command review,
depends on the sandbox being set up, and still has the open question of `.git/config` inside the sandbox.

Questions for Marco: Should repository hooks run, and if so inside the sandbox? Should rare git operations
(stash, cherry-pick) ever be allowed through commands, or only as skills?
