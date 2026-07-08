/*
 * OpenMates VS Code web app bundle preparer.
 *
 * Purpose: copy the static SvelteKit web app build into the VSIX media folder.
 * Architecture: GitHub Actions builds frontend/apps/web_app with the VS Code
 * target, then this script makes those files available to extension.ts.
 * Security: the extension rewrites these files to VS Code webview URIs at run time.
 */

import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const extensionRoot = path.resolve(__dirname, "..");
const repoRoot = path.resolve(extensionRoot, "../../..");
const sourceDir = path.join(repoRoot, "frontend", "apps", "web_app", "build");
const targetDir = path.join(extensionRoot, "media", "app");
const allowMissing = process.env.OPENMATES_VSCODE_ALLOW_BOOTSTRAP === "1";

async function main() {
  if (!(await exists(path.join(sourceDir, "index.html")))) {
    if (allowMissing) {
      console.warn("OpenMates web app build missing; keeping bootstrap shell because OPENMATES_VSCODE_ALLOW_BOOTSTRAP=1.");
      return;
    }
    throw new Error(
      `Missing ${path.join(sourceDir, "index.html")}. Build the web app with OPENMATES_BUILD_TARGET=vscode before packaging the VSIX.`,
    );
  }

  await fs.rm(targetDir, { recursive: true, force: true });
  await fs.cp(sourceDir, targetDir, { recursive: true });
  console.log(`Copied OpenMates web app bundle to ${targetDir}`);
}

async function exists(filePath) {
  try {
    await fs.access(filePath);
    return true;
  } catch (error) {
    if (error && typeof error === "object" && "code" in error && error.code === "ENOENT") {
      return false;
    }
    throw error;
  }
}

await main();
