/** Shared source-root boundary for local Project file and command access. */

import { existsSync, realpathSync, statSync } from "node:fs";
import { basename, dirname, relative, resolve } from "node:path";

import { resolveStateDir } from "./storage.js";

export interface ProjectSourceRootPolicyOptions {
  stateDirectory?: string;
}

/**
 * Resolve a Project source root and reject any overlap with private CLI state.
 * Rejecting the whole source prevents even filenames below the state directory
 * from being exposed by directory listing and search operations.
 */
export function canonicalProjectSourceRoot(
  sourceRoot: string,
  options: ProjectSourceRootPolicyOptions = {},
): string {
  const root = realpathSync(sourceRoot);
  if (!statSync(root).isDirectory()) throw new Error("Project source root is not a directory");
  const stateDirectory = canonicalOpenMatesStateDirectory(options.stateDirectory);
  if (isEqualOrInside(root, stateDirectory) || isEqualOrInside(stateDirectory, root)) {
    throw new Error("Project source root overlaps OpenMates private state");
  }
  return root;
}

/** Resolve state through existing symlinked ancestors without creating it. */
export function canonicalOpenMatesStateDirectory(stateDirectory = resolveStateDir()): string {
  return canonicalizePotentialPath(stateDirectory);
}

function canonicalizePotentialPath(value: string): string {
  let existing = resolve(value);
  const suffix: string[] = [];
  while (!existsSync(existing)) {
    const parent = dirname(existing);
    if (parent === existing) return resolve(value);
    suffix.unshift(basename(existing));
    existing = parent;
  }
  return resolve(realpathSync(existing), ...suffix);
}

function isEqualOrInside(parent: string, candidate: string): boolean {
  const path = relative(parent, candidate);
  return path === "" || (!path.startsWith("..") && !path.startsWith("/") && !path.startsWith("\\"));
}
