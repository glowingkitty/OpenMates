/*
 * Atomic publication for self-hosted server backup archives.
 *
 * Keeps temporary secret-bearing archives private and never replaces a prior
 * archive until tar has completed successfully.
 */

import { execFileSync } from "node:child_process";
import { chmodSync, lstatSync, readdirSync, renameSync, rmSync } from "node:fs";
import { randomUUID } from "node:crypto";

function assertRegularBackupTree(path: string): void {
  const stat = lstatSync(path);
  if (stat.isDirectory()) {
    for (const entry of readdirSync(path)) assertRegularBackupTree(`${path}/${entry}`);
    return;
  }
  if (!stat.isFile() || stat.nlink !== 1) {
    throw new Error(`Backup archive refused unsafe entry: ${path}`);
  }
}

export function publishServerBackupArchive(sourceDir: string, archivePath: string, options: { tarCommand?: string } = {}): void {
  assertRegularBackupTree(sourceDir);
  const temporaryArchivePath = `${archivePath}.tmp-${randomUUID()}`;
  const previousUmask = process.umask(0o077);
  try {
    execFileSync(options.tarCommand ?? "tar", ["-czf", temporaryArchivePath, "-C", sourceDir, "."], { stdio: "pipe" });
    chmodSync(temporaryArchivePath, 0o600);
    renameSync(temporaryArchivePath, archivePath);
    chmodSync(archivePath, 0o600);
  } finally {
    process.umask(previousUmask);
    rmSync(temporaryArchivePath, { force: true });
  }
}
