/*
 * Source-install translation preparation for self-hosted OpenMates.
 *
 * Purpose: source-mode installs clone tracked files only, while generated
 *          runtime locale JSON is intentionally gitignored.
 * Architecture: reuses the UI package's canonical build-translations script.
 * Tests: frontend/packages/openmates-cli/tests/server.test.ts
 */

import { execFileSync } from "node:child_process";
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
  rmSync,
  symlinkSync,
} from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";

const UI_PACKAGE_RELATIVE_PATH = join("frontend", "packages", "ui");
const GENERATED_LOCALES_RELATIVE_PATH = join(UI_PACKAGE_RELATIVE_PATH, "src", "i18n", "locales");
const BUILD_TRANSLATIONS_SCRIPT_RELATIVE_PATH = join(UI_PACKAGE_RELATIVE_PATH, "scripts", "build-translations.js");
const REQUIRED_LOCALE_JSON = "en.json";

export type SourceInstallTranslationStatus = "already_present" | "copied" | "built";

export type SourceInstallTranslationResult = {
  status: SourceInstallTranslationStatus;
  localeDir: string;
  copiedFiles: number;
};

export function sourceInstallLocalesPath(rootPath: string): string {
  return join(rootPath, GENERATED_LOCALES_RELATIVE_PATH);
}

export function ensureSourceInstallTranslations(
  installPath: string,
  sourcePath?: string | null,
): SourceInstallTranslationResult {
  const localeDir = sourceInstallLocalesPath(installPath);
  const requiredLocalePath = join(localeDir, REQUIRED_LOCALE_JSON);
  if (existsSync(requiredLocalePath)) {
    return { status: "already_present", localeDir, copiedFiles: 0 };
  }

  const copiedFiles = copyGeneratedLocaleJson(sourcePath, installPath);
  if (existsSync(requiredLocalePath)) {
    return { status: "copied", localeDir, copiedFiles };
  }

  runBuildTranslationsScript(installPath);
  if (!existsSync(requiredLocalePath)) {
    throw new Error(`Generated locale JSON was not created at ${requiredLocalePath}.`);
  }
  return { status: "built", localeDir, copiedFiles };
}

function copyGeneratedLocaleJson(sourcePath: string | null | undefined, installPath: string): number {
  if (!sourcePath) return 0;
  const sourceRoot = resolve(sourcePath);
  const targetRoot = resolve(installPath);
  if (sourceRoot === targetRoot) return 0;

  const sourceLocaleDir = sourceInstallLocalesPath(sourceRoot);
  if (!existsSync(join(sourceLocaleDir, REQUIRED_LOCALE_JSON))) return 0;

  const targetLocaleDir = sourceInstallLocalesPath(targetRoot);
  mkdirSync(targetLocaleDir, { recursive: true });
  let copiedFiles = 0;
  for (const entry of readdirSync(sourceLocaleDir, { withFileTypes: true })) {
    if (!entry.isFile() || !entry.name.endsWith(".json")) continue;
    copyFileSync(join(sourceLocaleDir, entry.name), join(targetLocaleDir, entry.name));
    copiedFiles += 1;
  }
  return copiedFiles;
}

function runBuildTranslationsScript(installPath: string): void {
  const uiPackageDir = join(installPath, UI_PACKAGE_RELATIVE_PATH);
  const buildScript = join(installPath, BUILD_TRANSLATIONS_SCRIPT_RELATIVE_PATH);
  if (!existsSync(buildScript)) {
    throw new Error(`Translation build script not found at ${buildScript}.`);
  }

  const requireFromCli = createRequire(import.meta.url);
  const yamlPackageDir = dirname(requireFromCli.resolve("yaml/package.json"));
  const nodeModulesDir = join(uiPackageDir, "node_modules");
  const yamlLink = join(nodeModulesDir, "yaml");
  const hadNodeModulesDir = existsSync(nodeModulesDir);
  const hadYamlPackage = existsSync(yamlLink);

  if (!hadYamlPackage) {
    mkdirSync(nodeModulesDir, { recursive: true });
    symlinkSync(yamlPackageDir, yamlLink, process.platform === "win32" ? "junction" : "dir");
  }

  try {
    execFileSync(process.execPath, [buildScript], {
      cwd: uiPackageDir,
      stdio: "inherit",
    });
  } finally {
    if (!hadYamlPackage) rmSync(yamlLink, { recursive: true, force: true });
    if (!hadNodeModulesDir && existsSync(nodeModulesDir) && readdirSync(nodeModulesDir).length === 0) {
      rmSync(nodeModulesDir, { recursive: true, force: true });
    }
  }
}
