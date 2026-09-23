import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = join(packageRoot, "..", "..", "..");
const destination = join(packageRoot, "dist", "remote-command-apparmor");
const files = [
  "setup_remote_command_apparmor.py",
  "openmates_command_apparmor.py",
  "openmates_git_config_mask.c",
];
const check = process.argv.includes("--check");

await mkdir(destination, { recursive: true });
for (const name of files) {
  const source = await readFile(join(repositoryRoot, "scripts", name));
  const target = join(destination, name);
  if (check) {
    let packaged;
    try {
      packaged = await readFile(target);
    } catch {
      throw new Error(`Packaged remote-command setup asset is missing: ${name}`);
    }
    if (!source.equals(packaged)) throw new Error(`Packaged remote-command setup asset differs from canonical source: ${name}`);
  } else {
    await writeFile(target, source, { mode: 0o644 });
  }
}
