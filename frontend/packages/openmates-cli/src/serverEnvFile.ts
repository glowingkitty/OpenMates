/** Private, atomic writes for the server runtime environment file. */
import { randomUUID } from "node:crypto";
import { chmodSync, closeSync, existsSync, fsyncSync, lstatSync, mkdirSync, openSync, readFileSync, realpathSync, renameSync, rmSync, statSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

function targetPath(path: string): string {
  // Replacing the symlink itself would disconnect installations whose runtime
  // .env is linked to another file. Resolve it before creating the temp file.
  if (existsSync(path)) {
    const target = realpathSync(path);
    if (!statSync(target).isFile()) throw new Error(`Runtime env is not a regular file: ${path}`);
    return target;
  }
  // A dangling link must not be silently replaced with a new .env.
  try {
    if (lstatSync(path).isSymbolicLink()) throw new Error(`Runtime env symlink target is missing: ${path}`);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
  }
  return path;
}

function privateTemp(path: string, content: string, write: (fd: number, content: string) => void = writeFileSync): string {
  mkdirSync(dirname(path), { recursive: true });
  const temporary = `${path}.openmates-${randomUUID()}.tmp`;
  const fd = openSync(temporary, "wx", 0o600);
  try {
    write(fd, content);
    fsyncSync(fd);
  } catch (error) {
    try { closeSync(fd); } finally { rmSync(temporary, { force: true }); }
    throw error;
  }
  closeSync(fd);
  return temporary;
}

function syncDirectory(path: string): void {
  const fd = openSync(dirname(path), "r");
  try { fsyncSync(fd); } finally { closeSync(fd); }
}

export function writeServerEnvFile(path: string, content: string, rename = renameSync, write = writeFileSync): void {
  const target = targetPath(path);
  const temporary = privateTemp(target, content, write);
  try {
    rename(temporary, target);
    syncDirectory(target);
  } finally {
    rmSync(temporary, { force: true });
  }
}

export async function editServerEnvFile(
  path: string,
  editor: (temporary: string) => Promise<number>,
  rename = renameSync,
): Promise<number> {
  const target = targetPath(path);
  const temporary = privateTemp(target, existsSync(target) ? readFileSync(target, "utf8") : "");
  try {
    const code = await editor(temporary);
    if (code !== 0) return code;
    if (!lstatSync(temporary).isFile()) throw new Error("Editor did not leave a regular env file");
    chmodSync(temporary, 0o600);
    const fd = openSync(temporary, "r");
    try { fsyncSync(fd); } finally { closeSync(fd); }
    rename(temporary, target);
    syncDirectory(target);
    return code;
  } finally {
    rmSync(temporary, { force: true });
  }
}
