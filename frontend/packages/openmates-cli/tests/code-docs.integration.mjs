/**
 * Live CLI integration pilot for the code/get_docs skill.
 *
 * This intentionally lives outside Playwright so browser specs can cover UI
 * behavior while CLI coverage fails loudly when API-key credentials are absent.
 * The JSON report is shaped like pytest-json-report for scripts/run_tests.py.
 *
 * Architecture: docs/architecture/platforms/cli-package.md
 */

import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const cliDist = process.env.OPENMATES_CLI_DIST
  ? path.resolve(process.env.OPENMATES_CLI_DIST)
  : path.resolve(__dirname, "../dist/cli.js");
const homeDir = mkdtempSync(path.join(tmpdir(), "openmates-cli-integration-"));
const outputPath = getOutputPath(process.argv);
const tests = [];

function getOutputPath(argv) {
  const index = argv.indexOf("--output");
  if (index >= 0 && argv[index + 1]) return path.resolve(argv[index + 1]);
  return path.resolve(process.cwd(), "cli-integration.json");
}

function deriveApiUrl() {
  const explicit = process.env.OPENMATES_CLI_TEST_API_URL?.trim();
  if (explicit) return explicit.replace(/\/+$/, "");

  const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL?.trim();
  if (baseUrl) {
    try {
      const url = new URL(baseUrl);
      if (url.hostname === "openmates.org" || url.hostname === "www.openmates.org") {
        return "https://api.openmates.org";
      }
      if (url.hostname.startsWith("app.")) {
        return `${url.protocol}//api.${url.hostname.slice(4)}`.replace(/\/+$/, "");
      }
      if (url.hostname === "localhost") return "http://localhost:8000";
    } catch {
      // Fall through to the dev default below.
    }
  }

  return "https://api.dev.openmates.org";
}

function truncate(value, maxLength = 2000) {
  if (!value) return "(empty)";
  return value.length > maxLength
    ? `${value.slice(0, maxLength)}\n...(truncated, ${value.length} chars total)`
    : value;
}

function parseJsonOutput(result, label) {
  try {
    return JSON.parse(result.stdout);
  } catch (error) {
    throw new Error(
      `${label} did not emit JSON: ${error instanceof Error ? error.message : String(error)}\n` +
        `stdout:\n${truncate(result.stdout)}\n` +
        `stderr:\n${truncate(result.stderr)}`,
    );
  }
}

function assertCliSuccess(result, label) {
  if (result.code === 0) return;
  throw new Error(
    `${label} exited with code ${result.code}\n` +
      `stderr:\n${truncate(result.stderr)}\n` +
      `stdout:\n${truncate(result.stdout)}`,
  );
}

async function runCli(args, timeoutMs = 30_000) {
  const apiKey = process.env.OPENMATES_TEST_ACCOUNT_API_KEY;
  const apiUrl = deriveApiUrl();
  const allArgs = ["--api-key", apiKey, ...args];

  return await new Promise((resolve) => {
    const child = spawn("node", [cliDist, ...allArgs], {
      env: {
        ...process.env,
        HOME: homeDir,
        OPENMATES_API_URL: apiUrl,
      },
      stdio: ["pipe", "pipe", "pipe"],
    });
    const stdout = [];
    const stderr = [];
    const timeout = setTimeout(() => {
      child.kill("SIGTERM");
      resolve({ code: null, stdout: stdout.join(""), stderr: stderr.join("") });
    }, timeoutMs);

    child.stdout.on("data", (chunk) => stdout.push(chunk.toString()));
    child.stderr.on("data", (chunk) => stderr.push(chunk.toString()));
    child.on("close", (code) => {
      clearTimeout(timeout);
      resolve({ code, stdout: stdout.join(""), stderr: stderr.join("") });
    });
  });
}

async function recordTest(name, fn) {
  const started = Date.now();
  try {
    await fn();
    tests.push({
      nodeid: name,
      outcome: "passed",
      duration: Number(((Date.now() - started) / 1000).toFixed(3)),
    });
  } catch (error) {
    tests.push({
      nodeid: name,
      outcome: "failed",
      duration: Number(((Date.now() - started) / 1000).toFixed(3)),
      call: { longrepr: error instanceof Error ? error.stack ?? error.message : String(error) },
    });
  }
}

function writeReport() {
  const passed = tests.filter((test) => test.outcome === "passed").length;
  const failed = tests.filter((test) => test.outcome === "failed").length;
  writeFileSync(
    outputPath,
    JSON.stringify(
      {
        created: new Date().toISOString(),
        summary: { total: tests.length, passed, failed },
        tests,
      },
      null,
      2,
    ),
  );
}

async function main() {
  await recordTest("cli-integration/code-docs/preflight", async () => {
    if (!existsSync(cliDist)) {
      throw new Error(`Compiled CLI not found at ${cliDist}. Run npm run build first.`);
    }
    if (!process.env.OPENMATES_TEST_ACCOUNT_API_KEY?.trim()) {
      throw new Error("OPENMATES_TEST_ACCOUNT_API_KEY is required for CLI integration tests.");
    }
  });

  if (tests.some((test) => test.outcome === "failed")) return;

  await recordTest("cli-integration/code-docs/apps-code-get-docs", async () => {
    const result = await runCli(
      [
        "apps",
        "code",
        "get_docs",
        "--input",
        JSON.stringify({ library: "React", question: "How do I use the useState hook?" }),
        "--json",
      ],
      45_000,
    );
    assertCliSuccess(result, "openmates apps code get_docs");
    const parsed = parseJsonOutput(result, "openmates apps code get_docs");
    if (parsed?.success !== true || !parsed.data) {
      throw new Error(`Expected success envelope with data, got:\n${truncate(JSON.stringify(parsed, null, 2))}`);
    }
  });

  await recordTest("cli-integration/code-docs/chats-new", async () => {
    let chatId = null;
    try {
      const result = await runCli(
        ["chats", "new", "Show me React useState documentation", "--json"],
        90_000,
      );
      assertCliSuccess(result, "openmates chats new");
      const parsed = parseJsonOutput(result, "openmates chats new");
      chatId = parsed?.chatId ?? parsed?.chat_id ?? null;
      if (parsed?.status !== "completed" || typeof chatId !== "string" || chatId.length === 0) {
        throw new Error(`Expected completed chat response with chatId, got:\n${truncate(JSON.stringify(parsed, null, 2))}`);
      }
      if (typeof parsed.assistant !== "string" || parsed.assistant.trim().length === 0) {
        throw new Error(`Expected assistant response text, got:\n${truncate(JSON.stringify(parsed, null, 2))}`);
      }
    } finally {
      if (chatId) {
        const cleanup = await runCli(["chats", "delete", chatId, "--yes"], 30_000);
        assertCliSuccess(cleanup, "openmates chats delete cleanup");
      }
    }
  });
}

try {
  await main();
} finally {
  writeReport();
  rmSync(homeDir, { recursive: true, force: true });
}

process.exit(tests.some((test) => test.outcome === "failed") ? 1 : 0);
