---
status: active
last_verified: 2026-06-22
---

# Publish the Python SDK

The Python SDK package lives in `packages/openmates-python` and publishes to the
PyPI project `openmates`.

## First-Time PyPI Setup

Use PyPI Trusted Publishing so GitHub Actions can publish with OIDC instead of a
long-lived API token.

1. Log in to PyPI as a maintainer for the `openmates` project, or create a pending publisher if the project does not exist yet.
2. Open PyPI Account settings > Publishing > Add pending publisher.
3. Set Project name to `openmates`.
4. Set Owner to `glowingkitty`.
5. Set Repository name to `OpenMates`.
6. Set Workflow filename to `publish-python-sdk.yml`.
7. Leave Environment name empty unless the GitHub workflow is later changed to use an environment.
8. Save the publisher before triggering the first workflow run.

No `PYPI_API_TOKEN` secret is needed.

## Versioning

Python versions come from `shared/config/product_version.json` under the `python`
key:

```json
{
  "python": {
    "stableBase": "0.13.0",
    "prereleaseBase": "0.13.0a",
    "prereleaseSeed": "0.13.0a0"
  }
}
```

The checked-in `packages/openmates-python/pyproject.toml` version should match
`python.stableBase`. The publish workflow rewrites that version in CI only:

- `dev` publishes the next alpha prerelease, for example `0.13.0a0`, `0.13.0a1`, and so on.
- `main` publishes `python.stableBase` if it is not already on PyPI; otherwise it patch-bumps from the latest stable PyPI version.

Use alpha releases for dev testing:

```bash
pip install --pre openmates
```

Stable installs continue to use the latest non-prerelease:

```bash
pip install openmates
```

## Manual Preflight

Run these before triggering or merging a publish change:

```bash
python3 scripts/prepare_python_publish_version.py --channel=check
python3 -m pytest packages/openmates-python/tests scripts/tests/test_prepare_python_publish_version.py
cd packages/openmates-python && python3 -m build
```

To see the next version without modifying files:

```bash
python3 scripts/prepare_python_publish_version.py --channel=dev --dry-run
python3 scripts/prepare_python_publish_version.py --channel=main --dry-run
```

## Automated Publish Flow

The `.github/workflows/publish-python-sdk.yml` workflow runs on pushes to `dev`
or `main` when Python SDK package files, version config, or the publish workflow
change. It also supports manual `workflow_dispatch` runs.

1. Merge SDK changes into `dev`.
2. Wait for `Publish Python SDK` to pass and publish the alpha prerelease.
3. Install the alpha locally with `pip install --pre --upgrade openmates` and run a small API-key smoke test.
4. Merge `dev` to `main` when ready for a stable release.
5. Wait for the same workflow to publish the stable package.

If publishing fails with a trusted-publisher error, verify the PyPI pending
publisher fields exactly match the GitHub owner, repository, and workflow file.
