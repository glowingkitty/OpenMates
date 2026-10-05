"""Issue exact-release archive eligibility from durable maintainer-reviewed proof.

Maintainers seal once after reviewing actual evidence:
  python3 scripts/storage_release_eligibility.py seal-review --source <tested-sha>
    --checks /private/checks.json --reviewer <maintainer> --review-id <review-id>
    --signing-key-file /private/release-key.pem --output config/storage-release-evidence.json

Each checks.json entry maps a storage check to either a github-actions run_id,
spec and optional exact report/harness digests, or explicit apple_reader native
proof with source_commit, outcome, synthetic=false, evidence_id/evidence_sha256.
p7_capacity_target additionally names paced_evidence using the same CI shape.
The tool verifies actual CI provenance, captures original report bytes, derives
the complete protected code/harness digests and signs the reviewed bundle. Publish
that registry through ordinary repository review. Installations never sign proof.
The image workflow publishes a permanent exact-source certificate automatically;
all existing live runtime, authorization, generation and durability fences apply.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.parse
import urllib.request
import zipfile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

try:
    from scripts.storage_rollout import CERTIFICATE_SCHEMA, READ_CHECKS, PRUNE_CHECKS, _canonical_json
except ModuleNotFoundError:
    from storage_rollout import CERTIFICATE_SCHEMA, READ_CHECKS, PRUNE_CHECKS, _canonical_json

REPOSITORY = "glowingkitty/OpenMates"
REVIEW_SCHEMA = "storage-release-evidence-review-v1"
REGISTRY_PATH = "config/storage-release-evidence.json"
TRUST_PATH = "backend/shared/config/storage_rollout_release_public_key.json"
SOURCE_PATTERN = re.compile(r"[a-f0-9]{40}\Z")
DIGEST_PATTERN = re.compile(r"[a-f0-9]{64}\Z")
PROTECTED_ROOTS = {"apple", "backend", "frontend", "packages", "scripts", "shared", "config", "specifications", ".github"}
MAX_ARTIFACT_BYTES = 16 * 1024**2


def protected_tree_digest(root: Path, source: str, *, harness_only: bool = False) -> str:
    """Hash all tracked runtime, build, contract and harness files, never a caller list."""
    if not SOURCE_PATTERN.fullmatch(source):
        raise ValueError("An exact release source is required")
    tree = subprocess.check_output(["git", "ls-tree", "-rz", source], cwd=root)
    files = []
    for entry in tree.split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        path = raw_path.decode("utf-8")
        if path == REGISTRY_PATH:
            continue
        if "/" not in path and Path(path).suffix.lower() in {".md", ".rst"}:
            continue
        if harness_only and path.split("/", 1)[0] not in {"scripts", ".github"}:
            continue
        if "/" not in path or path.split("/", 1)[0] in PROTECTED_ROOTS:
            files.append([path, metadata.decode("ascii")])
    if not files:
        raise ValueError("Protected release tree is empty")
    return hashlib.sha256(_canonical_json({"files": sorted(files)})).hexdigest()


def verify_review(registry: dict, public_key: str) -> dict:
    if (not isinstance(registry, dict) or set(registry) != {"schema", "payload", "signature"}
            or registry["schema"] != REVIEW_SCHEMA or not isinstance(registry["payload"], dict)):
        raise ValueError("Reviewed release evidence schema is invalid")
    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key, validate=True))
        key.verify(base64.b64decode(registry["signature"], validate=True), _canonical_json(registry["payload"]))
    except Exception as exc:
        raise ValueError("Reviewed release evidence signature is invalid") from exc
    payload = registry["payload"]
    if (not SOURCE_PATTERN.fullmatch(str(payload.get("approved_source_commit", "")))
            or not DIGEST_PATTERN.fullmatch(str(payload.get("protected_tree_sha256", "")))
            or not isinstance(payload.get("checks"), dict)
            or not re.fullmatch(r"[A-Za-z0-9._/-]{8,128}", str(payload.get("review_id", "")))
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(payload.get("reviewer", "")))):
        raise ValueError("Reviewed source, tree or maintainer identity is missing")
    try:
        approved = datetime.fromisoformat(payload["approved_at"].replace("Z", "+00:00"))
    except (KeyError, AttributeError, ValueError) as exc:
        raise ValueError("Reviewed release approval time is invalid") from exc
    if approved.tzinfo is None or approved > datetime.now(timezone.utc):
        raise ValueError("Reviewed release approval time is invalid")
    return payload


def _artifact_bytes(bundle: bytes, name: str) -> bytes:
    if len(bundle) > MAX_ARTIFACT_BYTES or name not in {"ci-results.json", "ci-environment.json"}:
        raise ValueError("Release evidence artifact exceeds its bounds")
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        members = archive.infolist()
        if len(members) > 10000:
            raise ValueError("Release evidence artifact has too many entries")
        matches = [item for item in members if item.filename.split("/")[-1] == name]
        if len(matches) != 1 or matches[0].file_size > 4 * 1024**2:
            raise ValueError("Release evidence report is missing, duplicate or oversized")
        path = Path(matches[0].filename)
        if path.is_absolute() or ".." in path.parts or (matches[0].external_attr >> 16) & 0o170000 == 0o120000:
            raise ValueError("Release evidence report path is unsafe")
        content = archive.read(matches[0])
    return content


def _proof_document(content: bytes) -> tuple[dict, str]:
    if len(content) > 4 * 1024**2:
        raise ValueError("Reviewed proof document exceeds limit")
    document = json.loads(content)
    if not isinstance(document, dict):
        raise ValueError("Release evidence report is malformed")
    return document, hashlib.sha256(content).hexdigest()


def verify_ci(record: dict, *, approved_source: str, github, reviewed_proof: dict | None = None) -> tuple[dict, dict, str]:
    if (record.get("kind") != "github-actions" or type(record.get("run_id")) is not int
            or record["run_id"] <= 0
            or not SOURCE_PATTERN.fullmatch(str(record.get("harness_commit", "")))
            or not DIGEST_PATTERN.fullmatch(str(record.get("report_sha256", "")))
            or not DIGEST_PATTERN.fullmatch(str(record.get("environment_sha256", "")))):
        raise ValueError("CI release evidence provenance is incomplete")
    run = github.run(record["run_id"])
    if (run.get("status") != "completed" or run.get("conclusion") != "success"
            or run.get("event") != "workflow_dispatch"
            or run.get("path") != ".github/workflows/isolated-tests.yml"
            or run.get("head_repository", {}).get("full_name") != REPOSITORY
            or run.get("head_sha") != record["harness_commit"]):
        raise ValueError("CI evidence is not a successful trusted repository workflow run")
    if reviewed_proof is None:
        bundle = github.artifact(record["run_id"], "isolated-test-results")
        report_bytes = _artifact_bytes(bundle, "ci-results.json")
        environment_bytes = _artifact_bytes(bundle, "ci-environment.json")
    else:
        # These original artifact bytes are covered by the maintainer signature;
        # ordinary seven-day Actions artifact expiry cannot invalidate them.
        report_bytes = base64.b64decode(reviewed_proof["report"], validate=True)
        environment_bytes = base64.b64decode(reviewed_proof["environment"], validate=True)
    report, digest = _proof_document(report_bytes)
    environment, environment_digest = _proof_document(environment_bytes)
    if digest != record["report_sha256"] or environment_digest != record["environment_sha256"]:
        raise ValueError("Reviewed CI report digest differs")
    for document in (report, environment):
        if (document.get("source_commit") != approved_source
                or document.get("harness_commit") != record["harness_commit"]
                or str(document.get("run_id")) != str(record["run_id"])):
            raise ValueError("CI proof source or harness does not match reviewed evidence")
    if report.get("success") is not True or report.get("error") or report.get("runtime_profile") != "e2e":
        raise ValueError("CI release evidence did not pass real application checks")
    results = report.get("results")
    selected = [item for item in results or [] if item.get("spec") == record.get("spec")]
    if not record.get("spec") or len(selected) != 1 or selected[0].get("exit_code") != 0:
        raise ValueError("Reviewed application spec did not pass")
    stats = selected[0].get("stats", {})
    if (type(stats.get("expected")) is not int or stats["expected"] <= 0
            or any(stats.get(name) != 0 for name in ("unexpected", "flaky", "skipped"))):
        raise ValueError("Reviewed application spec has failed, skipped or flaky coverage")
    if any(item.get("exit_code") != 0 for item in results):
        raise ValueError("CI release evidence contains a failed supporting check")
    return report, environment, f"github-actions:{record['run_id']}:{digest}"


def _workload(report: dict) -> dict:
    workloads = [entry["report"] for entry in report["results"]
                 if str(entry.get("suite", "")).startswith("storage-capacity-") and isinstance(entry.get("report"), dict)]
    if len(workloads) != 1 or workloads[0].get("passed") is not True or workloads[0].get("failures"):
        raise ValueError("P-7 workload proof is missing or failed")
    return workloads[0]


def prepare_payload(registry: dict, *, source: str, tree_digest: str,
                    harness_digest: str, harness_digest_for_source,
                    public_key: str, github, now: datetime | None = None,
                    allow_pending_readers: bool = False, strict_provided: bool = False) -> dict:
    reviewed = verify_review(registry, public_key)
    if reviewed["protected_tree_sha256"] != tree_digest:
        raise ValueError("Protected runtime and harness tree differs from reviewed proof")
    if (not SOURCE_PATTERN.fullmatch(source) or not DIGEST_PATTERN.fullmatch(harness_digest)
            or reviewed.get("protected_harness_sha256") != harness_digest):
        raise ValueError("Protected release harness differs from reviewed proof")
    missing = [name for name in READ_CHECKS if name not in reviewed["checks"]]
    if missing and not allow_pending_readers:
        raise ValueError("Required storage reader evidence is pending: " + ", ".join(missing))
    checks = {}
    ci_cache = {}
    approved = reviewed["approved_source_commit"]
    for name in PRUNE_CHECKS:
        if name not in reviewed["checks"]:
            continue
        try:
            record = reviewed["checks"][name]
            if not isinstance(record, dict):
                raise ValueError("Reviewed storage evidence is malformed")
            if record.get("kind") == "maintainer-reviewed":
                if (name != "apple_reader" or record.get("source_commit") != approved
                        or record.get("outcome") != "passed" or record.get("synthetic") is not False
                        or not DIGEST_PATTERN.fullmatch(str(record.get("evidence_sha256", "")))
                        or not re.fullmatch(r"[A-Za-z0-9._/-]{8,128}", str(record.get("evidence_id", "")))):
                    raise ValueError("Explicit maintainer-reviewed native proof is incomplete")
                evidence_id = "maintainer-reviewed:" + record["evidence_id"] + ":" + record["evidence_sha256"]
                report = environment = None
            else:
                cache_key = _canonical_json(record)
                if cache_key not in ci_cache:
                    ci_cache[cache_key] = verify_ci(record, approved_source=approved, github=github,
                        reviewed_proof=reviewed.get("ci_reports", {}).get(str(record.get("run_id"))))
                    if harness_digest_for_source(record["harness_commit"]) != harness_digest:
                        raise ValueError("Actual CI harness tree differs from release harness")
                report, environment, evidence_id = ci_cache[cache_key]
            checks[name] = {"passed": True, "source_commit": source, "evidence_id": evidence_id}
            if name in {"p7_zero_provider_calls", "p7_capacity_target"}:
                workload = _workload(report)
                provider = workload.get("provider", {})
                isolation = environment.get("storage_capacity", {})
                if (any(type(provider.get(key)) is not int or provider[key] != 0 for key in
                        ("real_provider_calls", "blocked_provider_calls", "cache_misses"))
                        or type(provider.get("cache_hits")) is not int or provider["cache_hits"] <= 0
                        or isolation.get("provider_credentials") != "absent"
                        or isolation.get("provider_network") != "internal"):
                    raise ValueError("P-7 zero-provider boundary is incomplete")
                if name == "p7_zero_provider_calls":
                    checks[name].update(real_provider_requests=0, provider_credentials="absent", provider_network="internal")
                else:
                    counts = workload.get("counts", {})
                    minimums = {"round": 500000, "embed": 200000, "version": 1000000}
                    if (record.get("spec") != "storage-capacity-target.spec.ts"
                            or workload.get("validation_level") != "target" or workload.get("workload_target_met") is not True
                            or workload.get("profile") not in {"accelerated", "burst"}
                            or any(type(counts.get(key)) is not int or counts[key] < value for key, value in minimums.items())
                            or type(workload.get("server_task_peak_concurrency")) is not int
                            or workload["server_task_peak_concurrency"] < 500
                            or type(workload.get("uncached_page_samples")) is not int or workload["uncached_page_samples"] <= 0
                            or type(workload.get("uncached_page_p95_ms")) not in (int, float)
                            or not 0 <= workload["uncached_page_p95_ms"] <= 1000):
                        raise ValueError("P-7 measured target thresholds are incomplete")
                    paced, _, paced_id = verify_ci(record.get("paced_evidence", {}), approved_source=approved, github=github,
                        reviewed_proof=reviewed.get("ci_reports", {}).get(str(record.get("paced_evidence", {}).get("run_id"))))
                    if harness_digest_for_source(record["paced_evidence"]["harness_commit"]) != harness_digest:
                        raise ValueError("Actual paced CI harness tree differs from release harness")
                    traffic = _workload(paced)
                    duration, measured = traffic.get("duration_seconds"), traffic.get("measured_duration_seconds")
                    if (traffic.get("profile") != "sustained" or type(duration) not in (int, float) or not 0 < duration <= 86400
                            or type(measured) not in (int, float) or not 0.95 * duration <= measured <= 1.05 * duration):
                        raise ValueError("P-7 paced representative traffic proof is incomplete")
                    checks[name].update(user_days=1000, simultaneous_executions=workload["server_task_peak_concurrency"],
                                        rounds=counts["round"], new_embeds=counts["embed"], file_versions=counts["version"],
                                        paced_evidence_id=paced_id)
        except (ValueError, KeyError, TypeError):
            checks.pop(name, None)
            if name in READ_CHECKS or strict_provided:
                raise
    current = now or datetime.now(timezone.utc)
    return {"source_commit": source, "profile": "real", "issued_at": current.isoformat(),
            "expires_at": None, "validity": "exact-source",
            "client_compatibility_verified": all(name in checks for name in READ_CHECKS),
            "reader_ready": all(name in checks for name in READ_CHECKS),
            "prune_ready": all(name in checks for name in PRUNE_CHECKS),
            "pending_checks": [name for name in PRUNE_CHECKS if name not in checks],
            "checks": checks, "approved_source_commit": approved,
            "protected_tree_sha256": tree_digest, "protected_harness_sha256": harness_digest,
            "review_id": reviewed["review_id"]}


def sign_certificate(payload: dict, private_pem: str, public_key: str) -> dict:
    key = serialization.load_pem_private_key(private_pem.encode(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Storage release issuer requires an Ed25519 key")
    actual = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    if actual != base64.b64decode(public_key, validate=True):
        raise ValueError("Storage release signing key does not match installed trust")
    return {"schema": CERTIFICATE_SCHEMA, "payload": payload,
            "signature": base64.b64encode(key.sign(_canonical_json(payload))).decode()}


class GitHub:
    def __init__(self, token: str):
        self.token = token
        self.cache = {}

    def request(self, endpoint: str, *, binary=False):
        class Redirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, request, fp, code, message, headers, url):
                if urllib.parse.urlsplit(url).scheme != "https":
                    raise ValueError("Release evidence redirect must use HTTPS")
                redirected = super().redirect_request(request, fp, code, message, headers, url)
                if redirected:
                    redirected.remove_header("Authorization")
                return redirected
        request = urllib.request.Request("https://api.github.com/repos/" + REPOSITORY + "/" + endpoint,
                                         headers={"Authorization": "Bearer " + self.token,
                                                  "Accept": "application/vnd.github+json"})
        with urllib.request.build_opener(Redirect()).open(request, timeout=60) as response:
            raw = response.read(MAX_ARTIFACT_BYTES + 1)
        if len(raw) > MAX_ARTIFACT_BYTES:
            raise ValueError("Release evidence response exceeds limit")
        return raw if binary else json.loads(raw)

    def run(self, run_id):
        key = ("run", run_id)
        if key not in self.cache:
            self.cache[key] = self.request(f"actions/runs/{run_id}")
        return self.cache[key]

    def artifact(self, run_id, name):
        key = (run_id, name)
        if key not in self.cache:
            entries = self.request(f"actions/runs/{run_id}/artifacts?per_page=100")["artifacts"]
            selected = [item for item in entries if item["name"] == name and not item["expired"]]
            if len(selected) != 1 or selected[0]["size_in_bytes"] > MAX_ARTIFACT_BYTES:
                raise ValueError("Exact reviewed CI artifact is unavailable")
            self.cache[key] = self.request(f"actions/artifacts/{selected[0]['id']}/zip", binary=True)
        return self.cache[key]


def seal_review(*, root: Path, source: str, checks: dict, reviewer: str,
                review_id: str, private_pem: str, public_key: str, github) -> dict:
    """Capture verified CI report bytes once, then sign a durable reviewed bundle.

    This maintainer command runs once per reviewed code/proof set. Installations
    only consume the public signed certificate and require no operator receipt.
    """
    payload = {
        "approved_source_commit": source,
        "protected_tree_sha256": protected_tree_digest(root, source),
        "protected_harness_sha256": protected_tree_digest(root, source, harness_only=True),
        "reviewer": reviewer, "review_id": review_id,
        "approved_at": datetime.now(timezone.utc).isoformat(), "checks": checks,
        "ci_reports": {},
    }
    records = list(checks.values())
    records.extend(record["paced_evidence"] for record in checks.values()
                   if isinstance(record, dict) and isinstance(record.get("paced_evidence"), dict))
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Reviewed storage evidence is malformed")
        if record.get("kind") != "github-actions":
            continue
        bundle = github.artifact(record["run_id"], "isolated-test-results")
        report_bytes = _artifact_bytes(bundle, "ci-results.json")
        environment_bytes = _artifact_bytes(bundle, "ci-environment.json")
        record.setdefault("harness_commit", github.run(record["run_id"])["head_sha"])
        record.setdefault("report_sha256", hashlib.sha256(report_bytes).hexdigest())
        record.setdefault("environment_sha256", hashlib.sha256(environment_bytes).hexdigest())
        verify_ci(record, approved_source=source, github=github)
        payload["ci_reports"][str(record["run_id"])] = {
            "report": base64.b64encode(report_bytes).decode(),
            "environment": base64.b64encode(environment_bytes).decode(),
        }
    signature = sign_certificate(payload, private_pem, public_key)["signature"]
    registry = {"schema": REVIEW_SCHEMA, "payload": payload, "signature": signature}
    prepare_payload(registry, source=source, tree_digest=payload["protected_tree_sha256"],
                    harness_digest=payload["protected_harness_sha256"],
                    harness_digest_for_source=lambda ref: protected_tree_digest(root, ref, harness_only=True),
                    public_key=public_key, github=github, allow_pending_readers=True, strict_provided=True)
    if len(_canonical_json(registry)) > 2 * 1024**2:
        raise ValueError("Reviewed release proof bundle exceeds limit")
    return registry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", choices=["issue", "seal-review"], default="issue")
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checks", type=Path)
    parser.add_argument("--reviewer")
    parser.add_argument("--review-id")
    parser.add_argument("--signing-key-file", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.command == "seal-review":
        try:
            if not all((args.checks, args.reviewer, args.review_id, args.signing_key_file)):
                raise ValueError("Maintainer sealing requires checks, reviewer, review ID and private key file")
            if (args.signing_key_file.is_symlink() or args.signing_key_file.stat().st_mode & 0o077
                    or args.checks.stat().st_size > 65536):
                raise ValueError("Maintainer review input or private key permissions are unsafe")
            trust = json.loads((root / TRUST_PATH).read_text())
            registry = seal_review(root=root, source=args.source, checks=json.loads(args.checks.read_text()),
                                   reviewer=args.reviewer, review_id=args.review_id,
                                   private_pem=args.signing_key_file.read_text(), public_key=trust["public_key"],
                                   github=GitHub(os.environ["GH_TOKEN"]))
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(_canonical_json(registry) + b"\n")
        except Exception:
            print("Maintainer release proof was not sealed; verified evidence and private signing authority are required")
            return 1
        print("Maintainer release proof sealed for " + args.source)
        return 0
    try:
        if (os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("GITHUB_REPOSITORY") != REPOSITORY
                or os.environ.get("GITHUB_REF") not in {"refs/heads/dev", "refs/heads/main"}
                or os.environ.get("GITHUB_EVENT_NAME") not in {"push", "workflow_dispatch"}
                or os.environ.get("GITHUB_SHA") != args.source):
            raise ValueError("Eligibility publication requires the trusted exact-source release workflow")
        source = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        if source != args.source:
            raise ValueError("Eligibility release checkout differs from installed image source")
        registry_path = root / REGISTRY_PATH
        if not registry_path.is_file() or registry_path.stat().st_size > 2 * 1024**2:
            raise ValueError("Reviewed P-7 and reader proof registry is pending")
        trust = json.loads((root / TRUST_PATH).read_text())
        if trust.get("schema") != "agentic-storage-release-trust-v1" or trust.get("algorithm") != "Ed25519":
            raise ValueError("Installed storage release trust is invalid")
        public_key = trust["public_key"]
        github = GitHub(os.environ["GH_TOKEN"])
        publication = github.run(int(os.environ["GITHUB_RUN_ID"]))
        if (publication.get("path") != ".github/workflows/publish-selfhost-images.yml"
                or publication.get("head_sha") != source
                or publication.get("head_repository", {}).get("full_name") != REPOSITORY):
            raise ValueError("Certificate issuer is outside the trusted image workflow")
        runs = github.request("actions/workflows/publish-selfhost-images.yml/runs?event=push&head_sha=" + source + "&per_page=100")["workflow_runs"]
        # Current push is in progress while this post-build job runs; query its
        # actual jobs. Manual renewal instead requires a completed image push.
        eligible_runs = ([publication] if publication.get("event") == "push" else []) + [
            run for run in runs if run.get("status") == "completed" and run.get("conclusion") == "success" and run.get("head_sha") == source]
        image_ready = False
        for run in eligible_runs:
            jobs = github.request(f"actions/runs/{run['id']}/jobs?per_page=100")["jobs"]
            builds = [job for job in jobs if job.get("name") in {"build-api", "build-docs-worker", "build-ci-schema"}
                      or str(job.get("name", "")).startswith("build-image (")]
            if len(builds) == 11 and all(job.get("conclusion") == "success" for job in builds):
                image_ready = True
                break
        if not image_ready:
            raise ValueError("Exact-source image publication proof is pending")
        payload = prepare_payload(json.loads(registry_path.read_text()), source=source,
                                  tree_digest=protected_tree_digest(root, source),
                                  harness_digest=protected_tree_digest(root, source, harness_only=True),
                                  harness_digest_for_source=lambda ref: protected_tree_digest(root, ref, harness_only=True),
                                  public_key=public_key, github=github)
        if not payload["prune_ready"]:
            print("Storage migration reader eligibility verified; pruning proof remains pending")
        certificate = sign_certificate(payload, os.environ["STORAGE_MIGRATION_RELEASE_SIGNING_KEY"], public_key)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(_canonical_json(certificate) + b"\n")
    except Exception as exc:
        args.output.unlink(missing_ok=True)
        reason = str(exc) if isinstance(exc, ValueError) else "Release proof verification is unavailable"
        print("Storage migration eligibility pending: " + reason)
        return 0
    print("Storage migration eligibility certificate verified for " + args.source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
