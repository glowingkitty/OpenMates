"""Durable, deterministic security scan reporting state.

This host-local SQLite ledger stores every structured scan observation rather
than deriving history from latest-only scanner state.  It performs no network,
email, remediation, or AI work.  Scanner callers own collection and pass only
sanitized structured metadata to ``ReportingStore``.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import sys
from typing import Any
from uuid import uuid4


SCHEMA_VERSION = 1
SEVERITIES = {"critical", "high", "medium", "low", "unknown"}
OUTCOMES = {"findings", "no_new_findings", "incomplete", "failed", "skipped"}
REPORT_SOURCES = ("dependabot", "eu_vulns", "security_audit", "redteam")
SUCCESSFUL_OUTCOMES = {"findings", "no_new_findings"}
SOURCE_FRESHNESS_HOURS = {"security_audit": 96, "redteam": 96}
DEPENDENCY_FRESHNESS_HOURS = 2


def _utc_timestamp(value: str | datetime | None = None) -> str:
    if value is None:
        parsed = datetime.now(timezone.utc)
    elif isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalized_aliases(finding: dict[str, Any]) -> list[str]:
    aliases = [finding.get("vuln_id"), *(finding.get("aliases") or [])]
    return sorted({str(alias).strip().upper() for alias in aliases if alias is not None and str(alias).strip()})


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def read_reporting_config(directory: Path) -> dict[str, Any]:
    """Read opt-in configuration; corrupt state is disabled with a visible warning."""
    try:
        value = json.loads((directory / "enabled.json").read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("configuration must be an object")
        return value
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        print("[security-reporting] Invalid or unreadable configuration; reporting disabled", file=sys.stderr)
        return {}


class ReportingStore:
    """A small transactional ledger for deterministic security reporting."""

    def __init__(
        self,
        path: str | Path,
        environment: str = "development",
        *,
        dry_run: bool = False,
        read_only: bool = False,
        enabled_at: str | datetime | None = None,
    ) -> None:
        if not environment.strip():
            raise ValueError("environment is required")
        self.path = Path(path)
        self.environment = environment.strip()
        self.dry_run = dry_run or read_only
        if self.dry_run and not self.path.exists():
            return
        self._ensure_private_path()
        if not self.dry_run:
            connection = self._connection()
            try:
                self._initialize(connection)
                activation = _utc_timestamp(enabled_at)
                connection.execute(
                    "INSERT OR IGNORE INTO source_activation VALUES (?, ?)", (self.environment, activation)
                )
            finally:
                connection.close()

    def _ensure_private_path(self) -> None:
        if not self.dry_run:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(self.path.parent, 0o700)
        if not self.path.exists() and not self.dry_run:
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(descriptor)
        if self.path.exists() and self.path.stat().st_mode & 0o077:
            raise PermissionError(f"security reporting database must be private: {self.path}")

    def _connection(self) -> sqlite3.Connection:
        if self.dry_run:
            if not self.path.exists():
                raise FileNotFoundError(self.path)
            connection = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True)
        else:
            connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
            os.chmod(self.path, 0o600)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _initialize(connection: sqlite3.Connection) -> None:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY, environment TEXT NOT NULL, source TEXT NOT NULL,
                subject_commit TEXT NOT NULL, completed_at TEXT NOT NULL, outcome TEXT NOT NULL,
                coverage_json TEXT NOT NULL, inventory_json TEXT NOT NULL, findings_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS findings (
                finding_id TEXT PRIMARY KEY, environment TEXT NOT NULL, ecosystem TEXT NOT NULL,
                package TEXT NOT NULL, severity TEXT NOT NULL, state TEXT NOT NULL,
                first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
                remediation_json TEXT NOT NULL, resolution_json TEXT,
                UNIQUE(environment, ecosystem, package, finding_id)
            );
            CREATE TABLE IF NOT EXISTS finding_aliases (
                environment TEXT NOT NULL, ecosystem TEXT NOT NULL, package TEXT NOT NULL,
                alias TEXT NOT NULL, finding_id TEXT NOT NULL REFERENCES findings(finding_id),
                PRIMARY KEY(environment, ecosystem, package, alias)
            );
            CREATE TABLE IF NOT EXISTS finding_alias_observations (
                run_id TEXT NOT NULL REFERENCES runs(run_id), finding_id TEXT NOT NULL REFERENCES findings(finding_id),
                alias TEXT NOT NULL, PRIMARY KEY(run_id, finding_id, alias)
            );
            CREATE TABLE IF NOT EXISTS finding_observations (
                run_id TEXT NOT NULL REFERENCES runs(run_id), finding_id TEXT NOT NULL REFERENCES findings(finding_id),
                source TEXT NOT NULL, observed_at TEXT NOT NULL, version TEXT, severity TEXT NOT NULL,
                state TEXT NOT NULL, resolution_json TEXT, PRIMARY KEY(run_id, finding_id)
            );
            CREATE TABLE IF NOT EXISTS critical_incidents (
                incident_id TEXT PRIMARY KEY, finding_id TEXT NOT NULL REFERENCES findings(finding_id),
                opened_at TEXT NOT NULL, resolved_at TEXT, notified_at TEXT,
                UNIQUE(finding_id, opened_at)
            );
            CREATE TABLE IF NOT EXISTS schedule_changes (
                environment TEXT NOT NULL, source TEXT NOT NULL, effective_at TEXT NOT NULL,
                enabled INTEGER NOT NULL, PRIMARY KEY(environment, source, effective_at)
            );
            CREATE TABLE IF NOT EXISTS source_activation (
                environment TEXT PRIMARY KEY, enabled_at TEXT NOT NULL
            );
            """
        )
        if connection.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == 0:
            connection.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
        versions = [row[0] for row in connection.execute("SELECT version FROM schema_version")]
        if versions != [SCHEMA_VERSION]:
            raise ValueError(f"unsupported security reporting schema version: {versions}")

    def set_schedule(self, source: str, *, enabled: bool, effective_at: str) -> None:
        """Record coordinator-approved monitoring intervals, without changing timers."""
        if source not in REPORT_SOURCES:
            raise ValueError("unknown reporting source")
        if self.dry_run:
            return
        connection = self._connection()
        try:
            connection.execute(
                "INSERT INTO schedule_changes VALUES (?, ?, ?, ?) ON CONFLICT(environment,source,effective_at) DO UPDATE SET enabled=excluded.enabled",
                (self.environment, source, _utc_timestamp(effective_at), int(enabled)),
            )
        finally:
            connection.close()

    def _schedule_changes(self, source: str, end: str) -> list[sqlite3.Row]:
        connection = self._connection()
        try:
            # Old ledgers remain readable before their next writer initializes the table.
            if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='schedule_changes'").fetchone():
                return []
            return connection.execute(
                "SELECT effective_at, enabled FROM schedule_changes WHERE environment=? AND source=? AND effective_at<? ORDER BY effective_at",
                (self.environment, source, end),
            ).fetchall()
        finally:
            connection.close()

    def record_run(
        self,
        source: str,
        findings: list[dict[str, Any]],
        outcome: str,
        subject_commit: str,
        completed_at: str | datetime | None = None,
        coverage: dict[str, Any] | None = None,
        run_id: str | None = None,
        inventory: dict[str, Any] | None = None,
    ) -> str:
        """Persist one scan event and its observations, atomically and idempotently."""
        if not source.strip() or not subject_commit.strip():
            raise ValueError("source and subject_commit are required")
        if outcome not in OUTCOMES:
            raise ValueError(f"unsupported outcome: {outcome}")
        event_id = run_id or str(uuid4())
        observed_at = _utc_timestamp(completed_at)
        if self.dry_run:
            return event_id
        coverage = coverage or {"expected_and_completed_stages": {}, "sanitized_failure_codes": []}
        inventory = inventory or {}
        connection = self._connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = connection.execute("SELECT 1 FROM runs WHERE run_id=?", (event_id,)).fetchone()
                if existing:
                    stored = connection.execute("SELECT * FROM runs WHERE run_id=?", (event_id,)).fetchone()
                    payload = (self.environment, source, subject_commit, observed_at, outcome, _json(coverage), _json(inventory), _json(findings))
                    if tuple(stored[key] for key in ("environment", "source", "subject_commit", "completed_at", "outcome", "coverage_json", "inventory_json", "findings_json")) != payload:
                        raise ValueError(f"run ID payload conflict: {event_id}")
                    connection.execute("COMMIT")
                    return event_id
                connection.execute(
                    "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (event_id, self.environment, source, subject_commit, observed_at, outcome,
                     _json(coverage), _json(inventory), _json(findings)),
                )
                for ordinal, finding in enumerate(findings):
                    self._record_finding(connection, event_id, source, finding, observed_at, subject_commit, ordinal)
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        finally:
            connection.close()
        return event_id

    def _record_finding(
        self, connection: sqlite3.Connection, run_id: str, source: str, finding: dict[str, Any], observed_at: str,
        subject_commit: str, ordinal: int,
    ) -> None:
        ecosystem = str(finding.get("ecosystem") or "unknown").strip().lower()
        package = str(finding.get("package") or "unknown").strip().lower()
        aliases = _normalized_aliases(finding)
        rows = []
        if aliases:
            placeholders = ",".join("?" for _ in aliases)
            rows = connection.execute(
                f"SELECT DISTINCT finding_id FROM finding_aliases WHERE environment=? AND ecosystem=? AND package=? AND alias IN ({placeholders})",
                (self.environment, ecosystem, package, *aliases),
            ).fetchall()
        matched_ids = sorted(row["finding_id"] for row in rows)
        identity = "\0".join(aliases) if aliases else f"unidentified\0{run_id}\0{ordinal}"
        finding_id = matched_ids[0] if matched_ids else hashlib.sha256(
            f"{self.environment}\0{ecosystem}\0{package}\0{identity}".encode()
        ).hexdigest()[:32]
        for duplicate_id in matched_ids[1:]:
            self._merge_findings(connection, finding_id, duplicate_id)

        severity = str(finding.get("severity") or "unknown").strip().lower()
        if severity not in SEVERITIES:
            severity = "unknown"
        resolution = finding.get("resolution_evidence")
        resolved = finding.get("state") == "resolved" and self._valid_resolution(resolution, subject_commit)
        current = connection.execute("SELECT * FROM findings WHERE finding_id=?", (finding_id,)).fetchone()
        remediation = finding.get("remediation") if isinstance(finding.get("remediation"), dict) else None
        if current is None:
            state = "resolved" if resolved else ("unknown" if finding.get("state") == "unknown" else "open")
            connection.execute(
                "INSERT INTO findings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (finding_id, self.environment, ecosystem, package, severity, state, observed_at, observed_at,
                 _json(remediation or {}), _json(resolution) if resolved else None),
            )
        else:
            prior_state, prior_severity = current["state"], current["severity"]
            state = "resolved" if resolved else ("open" if finding.get("state") != "resolved" else prior_state)
            merged_remediation = remediation if remediation is not None else json.loads(current["remediation_json"])
            connection.execute(
                "UPDATE findings SET severity=?, state=?, last_seen_at=?, remediation_json=?, resolution_json=? WHERE finding_id=?",
                (severity if severity != "unknown" else prior_severity, state,
                 max(current["last_seen_at"], observed_at), _json(merged_remediation),
                 _json(resolution) if resolved else current["resolution_json"], finding_id),
            )
            connection.execute(
                "UPDATE findings SET first_seen_at=? WHERE finding_id=?",
                (min(current["first_seen_at"], observed_at), finding_id),
            )
        for alias in aliases:
            connection.execute(
                "INSERT OR REPLACE INTO finding_aliases VALUES (?, ?, ?, ?, ?)",
                (self.environment, ecosystem, package, alias, finding_id),
            )
            connection.execute(
                "INSERT OR IGNORE INTO finding_alias_observations VALUES (?, ?, ?)", (run_id, finding_id, alias)
            )
        state = "resolved" if resolved else connection.execute("SELECT state FROM findings WHERE finding_id=?", (finding_id,)).fetchone()[0]
        version = finding.get("current_version")
        connection.execute(
            "INSERT INTO finding_observations VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(run_id, finding_id) DO UPDATE SET "
            "severity=excluded.severity, state=excluded.state, resolution_json=excluded.resolution_json",
            (run_id, finding_id, source, observed_at, str(version) if version is not None else None, severity, state,
             _json(resolution) if resolved else None),
        )
        if resolved:
            connection.execute("UPDATE critical_incidents SET resolved_at=? WHERE finding_id=? AND resolved_at IS NULL", (observed_at, finding_id))
        elif severity == "critical":
            active = connection.execute("SELECT 1 FROM critical_incidents WHERE finding_id=? AND resolved_at IS NULL", (finding_id,)).fetchone()
            if not active:
                incident_id = hashlib.sha256(f"{finding_id}\0{run_id}\0{observed_at}".encode()).hexdigest()[:32]
                connection.execute("INSERT INTO critical_incidents VALUES (?, ?, ?, NULL, NULL)", (incident_id, finding_id, observed_at))

    @staticmethod
    def _valid_resolution(resolution: Any, subject_commit: str) -> bool:
        if not isinstance(resolution, dict) or resolution.get("subject_commit") != subject_commit:
            return False
        try:
            _utc_timestamp(resolution.get("verified_at"))
        except (TypeError, ValueError):
            return False
        if resolution.get("type") == "current_inventory":
            return resolution.get("complete") is True and resolution.get("all_instances_outside_affected_ranges") is True
        return resolution.get("type") == "deterministic_check" and bool(resolution.get("check_id")) and resolution.get("passed") is True

    @staticmethod
    def _merge_findings(connection: sqlite3.Connection, target_id: str, duplicate_id: str) -> None:
        target = connection.execute("SELECT first_seen_at, last_seen_at FROM findings WHERE finding_id=?", (target_id,)).fetchone()
        duplicate = connection.execute("SELECT first_seen_at, last_seen_at FROM findings WHERE finding_id=?", (duplicate_id,)).fetchone()
        if target and duplicate:
            connection.execute(
                "UPDATE findings SET first_seen_at=?, last_seen_at=? WHERE finding_id=?",
                (min(target["first_seen_at"], duplicate["first_seen_at"]), max(target["last_seen_at"], duplicate["last_seen_at"]), target_id),
            )
        connection.execute("UPDATE finding_aliases SET finding_id=? WHERE finding_id=?", (target_id, duplicate_id))
        # A later scanner can bridge two previously disjoint alias sets.  Keep
        # one observation when both identities appeared in the same run.
        connection.execute(
            "DELETE FROM finding_observations WHERE finding_id=? AND run_id IN "
            "(SELECT run_id FROM finding_observations WHERE finding_id=?)",
            (duplicate_id, target_id),
        )
        connection.execute(
            "DELETE FROM finding_alias_observations WHERE finding_id=? AND (run_id, alias) IN "
            "(SELECT run_id, alias FROM finding_alias_observations WHERE finding_id=?)",
            (duplicate_id, target_id),
        )
        connection.execute("UPDATE finding_alias_observations SET finding_id=? WHERE finding_id=?", (target_id, duplicate_id))
        connection.execute("UPDATE finding_observations SET finding_id=? WHERE finding_id=?", (target_id, duplicate_id))
        connection.execute("UPDATE critical_incidents SET finding_id=? WHERE finding_id=?", (target_id, duplicate_id))
        connection.execute("DELETE FROM findings WHERE finding_id=?", (duplicate_id,))

    def pending_critical(self) -> list[dict[str, Any]]:
        if self.dry_run and not self.path.exists():
            return []
        connection = self._connection()
        try:
            rows = connection.execute(
                "SELECT i.incident_id, i.opened_at, f.finding_id, f.package, f.ecosystem, f.severity "
                "FROM critical_incidents i JOIN findings f ON f.finding_id=i.finding_id "
                "WHERE i.resolved_at IS NULL AND i.notified_at IS NULL ORDER BY i.opened_at, i.incident_id"
            ).fetchall()
        finally:
            connection.close()
        return [dict(row) for row in rows]

    def mark_critical_notified(self, incident_id: str, notified_at: str | datetime | None = None) -> bool:
        if self.dry_run:
            return False
        connection = self._connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            changed = connection.execute(
                "UPDATE critical_incidents SET notified_at=? WHERE incident_id=? AND notified_at IS NULL AND resolved_at IS NULL",
                (_utc_timestamp(notified_at), incident_id),
            ).rowcount
            connection.execute("COMMIT")
        finally:
            connection.close()
        return changed == 1

    def prune_completed_history(self, now: str | datetime | None = None) -> int:
        """Prune only records older than 30 days with no open or pending incident."""
        if self.dry_run:
            return 0
        cutoff = _utc_timestamp(datetime.fromisoformat(_utc_timestamp(now).replace("Z", "+00:00")) - timedelta(days=30))
        connection = self._connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            runs = connection.execute(
                "SELECT r.run_id FROM runs r WHERE r.environment=? AND r.completed_at<? "
                "AND NOT EXISTS (SELECT 1 FROM finding_observations o JOIN findings f ON f.finding_id=o.finding_id "
                "WHERE o.run_id=r.run_id AND f.state!='resolved') "
                "AND NOT EXISTS (SELECT 1 FROM finding_observations o JOIN critical_incidents i ON i.finding_id=o.finding_id "
                "WHERE o.run_id=r.run_id AND i.resolved_at IS NULL) "
                "AND NOT (r.source IN ('security_audit', 'redteam') AND NOT EXISTS "
                "(SELECT 1 FROM runs newer WHERE newer.environment=r.environment AND newer.source=r.source "
                "AND newer.completed_at>r.completed_at))",
                (self.environment, cutoff),
            ).fetchall()
            run_ids = [row["run_id"] for row in runs]
            if run_ids:
                placeholders = ",".join("?" for _ in run_ids)
                connection.execute(f"DELETE FROM finding_observations WHERE run_id IN ({placeholders})", run_ids)
                connection.execute(f"DELETE FROM runs WHERE run_id IN ({placeholders})", run_ids)
            connection.execute("COMMIT")
            return len(run_ids)
        except Exception:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def snapshot(self, window_end: str | datetime | None = None) -> dict[str, Any]:
        end = _utc_timestamp(window_end)
        start = _utc_timestamp(datetime.fromisoformat(end.replace("Z", "+00:00")) - timedelta(days=1))
        if self.dry_run and not self.path.exists():
            return self._empty_snapshot(start, end)
        connection = self._connection()
        try:
            runs = connection.execute(
                "SELECT * FROM runs WHERE environment=? AND completed_at>=? AND completed_at<? ORDER BY completed_at, run_id",
                (self.environment, start, end),
            ).fetchall()
            historical_runs = connection.execute(
                "SELECT * FROM runs WHERE environment=? AND completed_at<? ORDER BY completed_at, run_id",
                (self.environment, end),
            ).fetchall()
            findings = connection.execute(
                "SELECT * FROM findings WHERE environment=? ORDER BY ecosystem, package, finding_id", (self.environment,)
            ).fetchall()
            aliases = connection.execute(
                "SELECT a.finding_id, a.alias FROM finding_alias_observations a JOIN runs r ON r.run_id=a.run_id "
                "WHERE r.environment=? AND r.completed_at<? ORDER BY a.alias", (self.environment, end)
            ).fetchall()
            observations = connection.execute(
                "SELECT o.finding_id, o.source, o.version, o.observed_at, o.severity, o.state, o.resolution_json FROM finding_observations o "
                "JOIN findings f ON f.finding_id=o.finding_id WHERE f.environment=? ORDER BY o.observed_at",
                (self.environment,),
            ).fetchall()
            activation = connection.execute(
                "SELECT enabled_at FROM source_activation WHERE environment=?", (self.environment,)
            ).fetchone()
        finally:
            connection.close()
        alias_map: dict[str, set[str]] = {}
        for row in aliases:
            alias_map.setdefault(row["finding_id"], set()).add(row["alias"])
        observation_map: dict[str, dict[str, Any]] = {}
        for row in observations:
            if row["observed_at"] >= end:
                continue
            values = observation_map.setdefault(row["finding_id"], {"sources": set(), "versions": set(), "events": []})
            values["sources"].add(row["source"])
            if row["version"] is not None:
                values["versions"].add(row["version"])
            values["events"].append(dict(row))
        output_findings = []
        for row in findings:
            observed = observation_map.get(row["finding_id"])
            if not observed:
                continue
            events = observed["events"]
            latest = events[-1]
            output_findings.append({
                "finding_id": row["finding_id"], "ecosystem": row["ecosystem"], "package": row["package"],
                "severity": latest["severity"] if latest["severity"] != "unknown" else row["severity"], "state": latest["state"],
                "first_seen_at": min(event["observed_at"] for event in events), "last_seen_at": max(event["observed_at"] for event in events),
                "aliases": sorted(alias_map.get(row["finding_id"], set())), "sources": sorted(observed["sources"]),
                "current_versions": sorted(observed["versions"]), "remediation": json.loads(row["remediation_json"]),
                "resolution_evidence": json.loads(latest["resolution_json"]) if latest["resolution_json"] else None,
                "_events": events,
            })
        run_counts: dict[str, int] = {}
        output_runs = []
        for row in runs:
            run_counts[row["outcome"]] = run_counts.get(row["outcome"], 0) + 1
            parsed_coverage = json.loads(row["coverage_json"])
            output_runs.append({
                "run_id": row["run_id"], "source": row["source"], "subject_commit": row["subject_commit"],
                "completed_at": row["completed_at"], "outcome": row["outcome"], "coverage": parsed_coverage,
            })
        activation_at = activation["enabled_at"] if activation else None
        coverage = self._coverage(historical_runs, start, end, activation_at)
        sources = self._sources(historical_runs, end)
        renderer_groups = {"new": [], "open": [], "resolved": []}
        for item in output_findings:
            rendered = {key: item[key] for key in ("package", "severity", "current_versions", "remediation")}
            rendered["advisory"] = item["aliases"][0] if item["aliases"] else "unknown"
            if start <= item["first_seen_at"] < end:
                renderer_groups["new"].append(rendered)
            if item["state"] == "open":
                renderer_groups["open"].append(rendered)
            if any(start <= event["observed_at"] < end and event["state"] == "resolved" for event in item["_events"]):
                renderer_groups["resolved"].append(rendered)
            item.pop("_events")
        for group in renderer_groups.values():
            group.sort(key=lambda item: (item["severity"], item["package"], item["advisory"]))
        finding_counts = {"open": 0, "resolved": 0, "unknown": 0, "by_severity": {severity: 0 for severity in sorted(SEVERITIES)}}
        for item in output_findings:
            finding_counts[item["state"]] += 1
            finding_counts["by_severity"][item["severity"]] += 1
        latest_run = historical_runs[-1] if historical_runs else None
        history_status = "complete" if activation_at and activation_at <= start else "partial"
        return {"environment": self.environment, "window_start": start, "window_end": end, "runs": output_runs,
                "run_counts": run_counts, "coverage": coverage, "findings": output_findings, "finding_counts": finding_counts,
                "new": renderer_groups["new"], "open": renderer_groups["open"], "resolved": renderer_groups["resolved"],
                "sources": sources, "subject_commit": latest_run["subject_commit"] if latest_run else "unavailable",
                "history": {"status": history_status, "available_from": activation_at}}

    def _coverage(self, runs: list[sqlite3.Row], start: str, end: str, activation_at: str | None) -> dict[str, dict[str, Any]]:
        coverage = {}
        active_from = max(start, activation_at) if activation_at else end
        for source in REPORT_SOURCES:
            slots = self._scheduled_slots(source, active_from, end)
            changes = self._schedule_changes(source, end)
            slots = [slot for slot in slots if next((bool(change["enabled"]) for change in reversed(changes) if change["effective_at"] <= slot), True)]
            outcomes: dict[str, list[sqlite3.Row]] = {slot: [] for slot in slots}
            for row in runs:
                if row["source"] != source:
                    continue
                metadata = json.loads(row["coverage_json"])
                slot = metadata.get("scheduled_slot") or row["completed_at"]
                if slot in outcomes:
                    outcomes[slot].append(row)
            completed = sum(any(row["outcome"] in SUCCESSFUL_OUTCOMES for row in rows) for rows in outcomes.values())
            failures = sorted({code for rows in outcomes.values() if not any(row["outcome"] in SUCCESSFUL_OUTCOMES for row in rows)
                               for row in rows for code in json.loads(row["coverage_json"]).get("sanitized_failure_codes", [])})
            # Manual/no-agent collection still contributes failures while scheduled
            # monitoring is paused; it must never masquerade as a clean 0/0 day.
            manual_failures = {
                code for row in runs if row["source"] == source and start <= row["completed_at"] < end
                and (json.loads(row["coverage_json"]).get("scheduled_slot") or row["completed_at"]) not in outcomes
                for code in json.loads(row["coverage_json"]).get("sanitized_failure_codes", [])
            }
            optional_failures = {
                code for row in runs if row["source"] == source and start <= row["completed_at"] < end
                for code in json.loads(row["coverage_json"]).get("optional_enrichment_failures", [])
            }
            failures = sorted(set(failures) | manual_failures | optional_failures)
            coverage[source] = {"expected": len(slots), "completed": completed, "missing": len(slots) - completed, "failure_codes": failures}
            if changes:
                coverage[source]["schedule_status"] = "enabled" if changes[-1]["enabled"] else "disabled"
        return coverage

    @staticmethod
    def _scheduled_slots(source: str, start: str, end: str) -> list[str]:
        if start >= end:
            return []
        start_at = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_at = datetime.fromisoformat(end.replace("Z", "+00:00"))
        slots = []
        cursor = start_at.replace(minute=0, second=0, microsecond=0)
        while cursor < end_at:
            if source in {"dependabot", "eu_vulns"}:
                minute = 30 if source == "dependabot" else 35
                slot = cursor.replace(minute=minute)
                if start_at <= slot < end_at:
                    slots.append(_utc_timestamp(slot))
            elif source == "security_audit" and cursor.hour == 2 and cursor.weekday() in {1, 4}:
                slot = cursor.replace(hour=2, minute=30)
                if start_at <= slot < end_at:
                    slots.append(_utc_timestamp(slot))
            elif source == "redteam" and cursor.hour == 2 and cursor.weekday() in {2, 5}:
                slot = cursor.replace(hour=2, minute=30)
                if start_at <= slot < end_at:
                    slots.append(_utc_timestamp(slot))
            cursor += timedelta(hours=1)
        return slots

    def _sources(self, runs: list[sqlite3.Row], end: str) -> dict[str, dict[str, str | None]]:
        result = {}
        end_at = datetime.fromisoformat(end.replace("Z", "+00:00"))
        for source in REPORT_SOURCES:
            relevant = [row for row in runs if row["source"] == source]
            if not relevant:
                result[source] = {"status": "unavailable", "observed_at": None}
                continue
            latest = relevant[-1]
            inventory = json.loads(latest["inventory_json"])
            structured = source not in SOURCE_FRESHNESS_HOURS or inventory.get("structured") is True
            status = "available" if structured and latest["outcome"] in SUCCESSFUL_OUTCOMES else "unavailable"
            if status == "available":
                observed = datetime.fromisoformat(latest["completed_at"].replace("Z", "+00:00"))
                if observed + timedelta(hours=SOURCE_FRESHNESS_HOURS.get(source, DEPENDENCY_FRESHNESS_HOURS)) < end_at:
                    status = "stale"
            result[source] = {"status": status, "observed_at": latest["completed_at"]}
        return result

    def _empty_snapshot(self, start: str, end: str) -> dict[str, Any]:
        return {"environment": self.environment, "window_start": start, "window_end": end, "runs": [], "run_counts": {},
                "coverage": {}, "findings": [], "finding_counts": {"open": 0, "resolved": 0, "unknown": 0,
                "by_severity": {severity: 0 for severity in sorted(SEVERITIES)}}, "new": [], "open": [], "resolved": [],
                "sources": {source: {"status": "unavailable", "observed_at": None} for source in REPORT_SOURCES},
                "subject_commit": "unavailable", "history": {"status": "partial", "available_from": None}}
