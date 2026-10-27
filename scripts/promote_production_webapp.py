#!/usr/bin/env python3
"""Promote only a browser-verified production app; restore its predecessor on failure."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend/scripts"))
import debug_vercel
from verify_production_webapp import verify

import httpx


class Vercel:
    def __init__(self):
        config = debug_vercel._get_project_config()
        if not config:
            # Vercel's local project binding stays in the canonical checkout.
            root = Path(__file__).resolve().parents[1]
            common = subprocess.check_output(
                ['git', 'rev-parse', '--path-format=absolute', '--git-common-dir'], cwd=root, text=True,
            ).strip()
            config = json.loads((Path(common).parent / 'frontend/apps/web_app/.vercel/project.json').read_text())
        self.project = config["projectId"]
        self.client = httpx.Client(
            base_url=debug_vercel.VERCEL_API, timeout=30,
            headers={"Authorization": "Bearer " + debug_vercel._get_token()},
            params={"teamId": config["orgId"]},
        )

    def get(self, path):
        response = self.client.get(path)
        response.raise_for_status()
        return response.json()

    def alias(self, deployment):
        response = self.client.post(f"/v2/deployments/{deployment}/aliases", json={"alias": "app.openmates.org"})
        response.raise_for_status()

    def current(self):
        return self.get("/v4/aliases/app.openmates.org")["deployment"]["id"]


def promote(api, deployment, version, output, checker=verify):
    output.mkdir(parents=True, exist_ok=False)
    receipt = {"deployment": deployment, "expected_version": version,
               "started_at": datetime.now(timezone.utc).isoformat(), "result": "failed"}
    previous = None
    changed = False
    try:
        if not version.strip():
            raise ValueError("An exact reviewed build version is required")
        project = api.get(f"/v9/projects/{api.project}")
        if project.get("autoAssignCustomDomains") is not False:
            raise RuntimeError("Disable automatic production domain assignment before staged promotion")
        target = api.get(f"/v13/deployments/{deployment}")
        if target.get("projectId") != api.project or target.get("target") != "production" or target.get("readyState") != "READY":
            raise RuntimeError("Expected a Ready production deployment in the existing web app project")
        previous = api.current()
        receipt["previous_deployment"] = previous
        staged = checker("https://" + target["url"], output / "before", version)
        if staged["result"] != "passed":
            raise RuntimeError("Candidate failed its browser check; production was not changed")
        if api.current() != previous:
            raise RuntimeError("Production changed during verification; refusing a stale promotion")
        # A lost response may follow a successful alias write. Reconcile the
        # actual alias in the failure path even when this call raises.
        changed = True
        api.alias(deployment)
        if api.current() != deployment:
            raise RuntimeError("Production alias does not identify the reviewed deployment")
        live = checker("https://app.openmates.org", output / "after", version)
        if live["result"] != "passed":
            raise RuntimeError("Live production browser check failed")
        receipt["result"] = "passed"
    except Exception as error:
        receipt["failure"] = str(error)
        # Never overwrite a concurrent operator's new alias.
        if changed and previous:
            try:
                if api.current() == deployment:
                    api.alias(previous)
                    receipt["rollback"] = "restored" if api.current() == previous else "failed"
            except Exception as rollback_error:
                receipt["rollback"] = "failed"
                receipt["rollback_failure"] = str(rollback_error)
        raise
    finally:
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment", required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    promote(Vercel(), args.deployment, args.expected_version, args.out)
    print(f"Production promotion passed both browser checks: {args.out / 'receipt.json'}")


if __name__ == "__main__":
    main()
