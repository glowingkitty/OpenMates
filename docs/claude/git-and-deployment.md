# Git and Deployment Rules

Rules for committing, deploying, and creating PRs. For detailed commands and release workflow, run:
`python3 scripts/sessions.py context --doc git-and-deployment-ref`

---

## Commit Messages

Follow Conventional Commits: `<type>: <description>`

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`

- Imperative present tense, no capitalization, no trailing period
- Never `git add .` — only add files modified in this session
- Never add `--trailer` or `Co-authored-by` lines

### Bug Fix Commits (CRITICAL)

Every `fix:` commit body MUST include:
- `Symptom:` — what the user experienced
- `Cause:` — root cause
- `Fix:` — what was changed

For issue-linked fixes, add: `Issue: <id> — <one sentence, no PII>`

## Pre-commit Checklist

- Run linter: `./scripts/lint_changed.sh --path <your_changes>`
- Fix all linter and type errors
- Remove temporary `console.log`/`print` (unless permanent)
- Only add files changed in this session

## Auto-Commit After Every Task

1. Run linter and fix errors
2. `git add <modified_files>` (never `git add .`)
3. `git commit -m "<type>: <description>"`
4. `git push origin dev`

If backend files were modified, rebuild affected Docker containers (check lock first).

## Branch → Server Mapping

| Branch | Server | URL |
|---|---|---|
| `dev` | Development | `https://dev.openmates.org` / `https://api.dev.openmates.org` |
| `main` | Production | `https://openmates.org` / `https://api.openmates.org` |

To inspect production code without switching branches: `git fetch origin main && git show main:<path>`

## PRs — Only When User Asks

Never create a PR on your own initiative. Always use remote refs: `origin/main`, `origin/dev` (never local `main`, `dev`). Always `git fetch origin` first.

## Linting

```bash
./scripts/lint_changed.sh --py --path backend/core/api          # Python
./scripts/lint_changed.sh --ts --svelte --path frontend/packages/ui  # Frontend
```

Pre-existing errors in files you didn't touch: fix if trivial/isolated, report if complex.
