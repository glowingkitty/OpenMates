/** Prepare host bind mounts before Docker Compose can create them as root. */
import { chmodSync, lstatSync, mkdirSync } from "node:fs";
import { join } from "node:path";

export function ensureRuntimeMetricsDirectory(installPath: string): void {
  let path = installPath;
  for (const part of [".openmates", "runtime-health", "metrics"]) {
    path = join(path, part);
    try {
      mkdirSync(path, { mode: 0o700 });
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "EEXIST") {
        throw new Error(`Cannot prepare runtime metrics directory ${path}: ${String(error)}`);
      }
    }
    const info = lstatSync(path);
    if (!info.isDirectory() || info.isSymbolicLink() || (process.getuid && info.uid !== process.getuid())) {
      throw new Error(`Runtime metrics path ${path} must be a directory owned by the server installer user. Fix its ownership before starting OpenMates.`);
    }
    chmodSync(path, 0o700);
  }
}
