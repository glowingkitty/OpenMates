/** Bounded public status projection for the unattended archive coordinator. */
export type StorageMigrationOutcome = {
  status: "pending" | "paused" | "reader_enabled" | "prune_enabled" | "not_applicable";
  reason?: string;
  source_commit?: string;
  retry_seconds?: number;
};

export type StorageMigrationProgress = {
  automatic: StorageMigrationOutcome;
  legacy_full_graph?: StorageMigrationOutcome;
  message_segments?: Record<string, number>;
  message_pages?: Record<string, number>;
  version_rows?: Record<string, number>;
};

export function parseStorageMigrationOutcome(value: unknown): StorageMigrationOutcome {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return { status: "paused", reason: "migration_coordinator_response_invalid" };
  }
  const row = value as Record<string, unknown>;
  if (!["pending", "paused", "reader_enabled", "prune_enabled", "not_applicable"].includes(String(row.status))) {
    return { status: "paused", reason: "migration_coordinator_response_invalid" };
  }
  const result: StorageMigrationOutcome = { status: row.status as StorageMigrationOutcome["status"] };
  if (typeof row.reason === "string" && /^[a-z_]{1,80}$/.test(row.reason)) result.reason = row.reason;
  if (typeof row.source_commit === "string" && /^[a-f0-9]{40}$/.test(row.source_commit)) result.source_commit = row.source_commit;
  if (Number.isInteger(row.retry_seconds) && Number(row.retry_seconds) > 0 && Number(row.retry_seconds) <= 86400) {
    result.retry_seconds = Number(row.retry_seconds);
  }
  return result;
}

export function parseStorageMigrationProgress(value: unknown): StorageMigrationProgress {
  const row = value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : {};
  const result: StorageMigrationProgress = { automatic: parseStorageMigrationOutcome(row.automatic) };
  if (row.legacy_full_graph !== undefined) result.legacy_full_graph = parseStorageMigrationOutcome(row.legacy_full_graph);
  const fields = {
    message_segments: ["copying", "verified", "reader_active"],
    message_pages: ["read_enabled", "pruned"],
    version_rows: ["copied", "reader_active", "pruned", "stale"],
  } as const;
  for (const [name, names] of Object.entries(fields)) {
    const counts = row[name];
    if (!counts || typeof counts !== "object" || Array.isArray(counts)) continue;
    const selected: Record<string, number> = {};
    for (const key of names) {
      const count = (counts as Record<string, unknown>)[key];
      if (typeof count === "number" && Number.isSafeInteger(count) && count >= 0) selected[key] = count;
    }
    result[name as keyof typeof fields] = selected;
  }
  return result;
}

export function storageMigrationCommand(
  composePrefix: string[], operation: "auto" | "status", sourceRevision?: string,
): string[] {
  if (sourceRevision !== undefined && !/^[a-f0-9]{40}$/i.test(sourceRevision)) {
    throw new Error("source_revision_unavailable");
  }
  return [...composePrefix, "exec", "-T",
    ...(sourceRevision ? ["-e", `BUILD_COMMIT_SHA=${sourceRevision.toLowerCase()}`] : []),
    "api", "python", "/app/scripts/storage_rollout.py", operation];
}
