# Git and Deployment Workflow

Load this document when committing code, creating PRs, or deploying changes.

---

## Git Commit Best Practices

### Commit Message Format

Follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

**Format:** `<type>: <description>`

**Types:**

- `feat`: A new feature
- `fix`: A bug fix
- `docs`: Documentation only changes
- `style`: Formatting changes (no code meaning change)
- `refactor`: Code change that neither fixes a bug nor adds a feature
- `perf`: Performance improvement
- `test`: Adding or correcting tests
- `build`: Build system or dependency changes
- `ci`: CI configuration changes
- `chore`: Other changes that don't modify src or test files
- `revert`: Reverts a previous commit

**Rules:**

- **Scope**: NEVER add all files (`git add .`). Only add files modified in the current session.
- **No Co-authors**: NEVER add `--trailer` flags or `Co-authored-by` lines.
- Use imperative present tense: "change" not "changed"
- Don't capitalize the first letter of the description
- No dot (.) at the end of the title

**Example:**

```bash
feat: add user authentication flow

- Implement JWT token generation and validation
- Add login and registration endpoints
- Secure existing API routes with auth middleware
```

### Pre-commit Checklist

- [ ] Run linter: `./scripts/lint_changed.sh --path <your_changes>`
- [ ] Fix all linter and type errors
- [ ] Remove temporary `console.log` or `print` statements (unless permanent)
- [ ] Only add files changed/created in this chat (no `git add .`)

---

## Auto-Commit and Deployment Workflow

**After completing any task**, automatically commit and push to `dev`:

1. Run linter and fix errors
2. `git add <modified_files>` (never `git add .`)
3. `git commit -m "<type>: <description>"`
4. `git push origin dev`
5. **If frontend files were modified**, verify the Vercel deployment succeeded (see below)

### Vercel Deployment Check (Frontend)

**CRITICAL:** After pushing frontend changes (`frontend/` files), ALWAYS verify the Vercel build passes. Do NOT assume a push means a successful deployment. Vercel deployments take **up to 200 seconds** (typically 2-3 minutes) to build and go live.

**Step-by-step procedure:**

```bash
# 1. WAIT for Vercel to pick up the push and build (~150 seconds)
#    Do NOT try to check immediately — the build needs time.
sleep 150

# 2. Check the latest deployment status:
vercel ls open-mates-webapp 2>&1 | head -5

# 3. Verify the latest entry shows "● Ready" (not "● Building" or "● Error")
#    - If "● Ready": Deployment succeeded. Proceed with testing.
#    - If "● Building": Wait another 30-60 seconds and re-check.
#    - If "● Error": Get the build logs and fix:
vercel inspect --logs <deployment-url> 2>&1 | tail -80
```

**Key rules:**
- **Always wait ~150 seconds** before checking — checking too early wastes time and gives misleading results
- **Never curl the site** to check if deployment is ready — use `vercel ls` which shows the actual build status
- **If the status is "● Error"**, fix the build error, commit, push, and repeat the full wait-and-check cycle
- **Only run E2E tests** (Playwright) after confirming "● Ready" status

See `docs/claude/debugging.md` → "Vercel Deployment Verification" for full details and common error patterns.

**If backend files were modified** (`.py`, `Dockerfile`, `docker-compose.yml`, config `.yml`), rebuild affected services:

```bash
# Rebuild specific services
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml build <services> && \
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml up -d <services>
```

| Files Modified                | Services to Rebuild                         |
| ----------------------------- | ------------------------------------------- |
| `backend/core/api/`           | `api`                                       |
| `backend/core/api/app/tasks/` | `api`, `task-worker`, `task-scheduler`      |
| `backend/apps/<app>/`         | `app-<app>`, `app-<app>-worker` (if exists) |
| `backend/shared/`             | All services using shared code              |
| Directus schema files         | `cms`, `cms-setup`                          |

---

## Branch and Server Mapping

### Branch → Server Mapping

| Branch | Server      | URL                                                           |
| ------ | ----------- | ------------------------------------------------------------- |
| `dev`  | Development | `https://dev.openmates.org` / `https://api.dev.openmates.org` |
| `main` | Production  | `https://openmates.org` / `https://api.openmates.org`         |

- The **development server** runs the `dev` branch — this is where we work and push changes.
- The **production server** runs the `main` branch — this is the live server that users interact with.

### Debugging Production Issues

When debugging issues that occur on the **production server**, the code running there may differ from the `dev` branch. To inspect the production code without switching branches, use `git show`.

**IMPORTANT: Always update the local `main` ref from remote first** before inspecting production code. The local `main` ref can be stale since we never switch to it — run `git fetch origin main` to ensure you're viewing the actual production code:

```bash
# ✅ ALWAYS run this first to update local main ref
git fetch origin main

# View a specific file as it exists on the main (production) branch
git show main:backend/core/api/app/routes/settings.py

# View a specific file at a specific line range (pipe through head/tail)
git show main:backend/core/api/app/routes/settings.py | head -200

# Compare a file between dev and main
git diff main..dev -- backend/core/api/app/routes/settings.py

# Check what's different between dev and main overall
git diff main..dev --stat

# View the last few commits on main
git log main --oneline -10
```

**Key rules:**

- Always use `git show main:<path>` to check production code — **do NOT switch branches** on the dev server
- Use the Admin Debug API with the **production base URL** (`https://api.openmates.org`) to inspect production data and logs
- When a user reports a production issue, first check if the relevant code differs between `dev` and `main`

---

## Creating Pull Requests

### Branch Comparison (CRITICAL)

When comparing branches (e.g., for a PR from `dev` to `main`), **ALWAYS use remote refs** (`origin/main`, `origin/dev`) — never local branch refs (`main`, `dev`). Local refs can be stale and produce wildly incorrect commit counts.

```bash
# ✅ CORRECT - uses remote refs (matches what GitHub sees)
git rev-list --left-right --count origin/main...origin/dev
git log origin/main..origin/dev --oneline

# ❌ WRONG - local refs may be stale, inflating commit count
git log main..dev --oneline
```

**Always run `git fetch origin` before comparing branches** to ensure remote refs are up to date.

### PR Workflow

1. Run `git fetch origin` to update remote refs
2. Use `git rev-list --left-right --count origin/main...origin/dev` to verify commit count
3. Use `git log origin/main..origin/dev` (with `origin/` prefix) for full commit history
4. Categorize commits and create a comprehensive PR summary
5. Create the PR via `gh pr create --base main --head dev`

---

## Linting and Code Quality

**ALWAYS run the lint script after making code changes** to verify that your changes haven't introduced any errors.

### Lint Script Usage

The `scripts/lint_changed.sh` script checks uncommitted changes for linting and type errors.

**File type options:**

- `--py` - Python files (.py)
- `--ts` - TypeScript files (.ts, .tsx)
- `--svelte` - Svelte files (.svelte)
- `--css` - CSS files (.css)
- `--html` - HTML files (.html)

**Targeting options (always use these):**

- `--path <file|dir>` - Limit checks to a specific file or directory (repeatable)
- `-- <file|dir> ...` - Treat remaining args as target paths

**Examples:**

```bash
./scripts/lint_changed.sh --py --path backend/core/api              # Only Python changes in API
./scripts/lint_changed.sh --ts --svelte --path frontend/packages/ui # Only UI frontend changes
./scripts/lint_changed.sh --py --ts --path backend --path frontend/apps/web_app # Mixed changes
```

### Best Practices

- Always limit checks to the specific files or folders you touched
- Limit checks to changed file types (don't check TypeScript if you only modified Python)
- **CRITICAL**: Before every git commit, run the linter on all modified files and fix all errors
- **CRITICAL**: Only commit when the linter shows NO errors for modified files