/*
 * OpenMates CLI model benchmark runner.
 *
 * Purpose: exercise real chat inference through the CLI product path.
 * Architecture: small command handler over OpenMatesClient.sendMessage().
 * Billing: live runs spend the logged-in user's credits and tag usage as benchmark.
 * Security: benchmark metadata is non-sensitive labels only.
 * Tests: covered by CLI command tests and backend usage-source tests.
 */

import { randomUUID } from "node:crypto";
import { writeFileSync } from "node:fs";

import type { BenchmarkMetadata, OpenMatesClient } from "./client.js";

type BenchmarkFlags = Record<string, string | boolean>;

type BenchmarkCase = {
  id: string;
  suite: "smoke" | "tools" | "quality";
  prompt: string;
  expectedIncludes?: string;
  needsJudge?: boolean;
};

type BenchmarkCaseResult = {
  id: string;
  suite: string;
  run: number;
  prompt: string;
  assistant: string;
  modelName: string | null;
  passed: boolean;
  durationMs: number;
  expectedIncludes?: string;
  judge?: {
    model: string;
    score: number | null;
    reason: string | null;
    raw: string;
  };
};

type BenchmarkResult = {
  command: "benchmark model";
  status: "planned" | "completed";
  runId: string;
  targetModel: string;
  judgeModel: string;
  suites: string[];
  runs: number;
  spendsCredits: boolean;
  cases: BenchmarkCaseResult[];
  summary: {
    total: number;
    passed: number;
    failed: number;
  };
};

const DEFAULT_JUDGE_MODEL = "google/gemini-3-flash-preview";

const BENCHMARK_CASES: BenchmarkCase[] = [
  {
    id: "smoke-exact-token",
    suite: "smoke",
    prompt: "Reply with exactly this token and no extra text: BENCHMARK_SMOKE_OK",
    expectedIncludes: "BENCHMARK_SMOKE_OK",
  },
  {
    id: "arithmetic-direct",
    suite: "tools",
    prompt: "Compute 19 * 23. Reply with only the integer result.",
    expectedIncludes: "437",
  },
  {
    id: "quality-concise-explanation",
    suite: "quality",
    prompt: "In four concise sentences, explain why deterministic benchmarks still need human-readable evaluation notes.",
    needsJudge: true,
  },
];

export async function handleBenchmark(
  client: OpenMatesClient,
  subcommand: string | undefined,
  rest: string[],
  flags: BenchmarkFlags,
): Promise<void> {
  if (!subcommand || subcommand === "help" || flags.help === true) {
    printBenchmarkHelp();
    return;
  }

  if (subcommand !== "model") {
    throw new Error(`Unknown benchmark command '${subcommand}'. Run 'openmates benchmark --help'.`);
  }

  const targetModel = rest[0];
  if (!targetModel) {
    throw new Error("Missing target model. Usage: openmates benchmark model <provider/model> --confirm-spend-credits");
  }

  const judgeModel = typeof flags["judge-model"] === "string"
    ? flags["judge-model"]
    : DEFAULT_JUDGE_MODEL;
  const suites = parseSuites(flags.suite);
  const runs = parseRuns(flags.runs);
  const dryRun = flags["dry-run"] === true;
  const output = typeof flags.output === "string" ? flags.output : undefined;
  const runId = typeof flags["run-id"] === "string" ? flags["run-id"] : randomUUID();

  if (!dryRun && flags["confirm-spend-credits"] !== true) {
    throw new Error(
      "Benchmark runs spend real credits from the logged-in account. " +
      "Rerun with --confirm-spend-credits, or use --dry-run to preview the plan.",
    );
  }

  const cases = expandCases(suites, runs);
  const baseResult: BenchmarkResult = {
    command: "benchmark model",
    status: dryRun ? "planned" : "completed",
    runId,
    targetModel,
    judgeModel,
    suites,
    runs,
    spendsCredits: !dryRun,
    cases: [],
    summary: { total: cases.length, passed: 0, failed: 0 },
  };

  if (dryRun) {
    writeBenchmarkResult(baseResult, flags, output);
    return;
  }

  if (!client.hasSession()) {
    throw new Error("Benchmark runs require login. Run 'openmates login' first.");
  }

  for (const benchmarkCase of cases) {
    const startedAt = Date.now();
    const targetResponse = await client.sendMessage({
      message: `${modelMention(targetModel)} ${benchmarkCase.prompt}`,
      incognito: true,
      autoApproveSubChats: true,
      benchmarkMetadata: benchmarkMetadata({
        runId,
        suite: benchmarkCase.suite,
        caseId: benchmarkCase.id,
        targetModel,
        judgeModel,
      }),
      precollectResponse: true,
    });

    const caseResult: BenchmarkCaseResult = {
      id: benchmarkCase.id,
      suite: benchmarkCase.suite,
      run: benchmarkCase.run,
      prompt: benchmarkCase.prompt,
      assistant: targetResponse.assistant,
      modelName: targetResponse.modelName,
      passed: benchmarkCase.expectedIncludes
        ? targetResponse.assistant.includes(benchmarkCase.expectedIncludes)
        : true,
      durationMs: Date.now() - startedAt,
      expectedIncludes: benchmarkCase.expectedIncludes,
    };

    if (benchmarkCase.needsJudge) {
      const judgeResponse = await client.sendMessage({
        message: `${modelMention(judgeModel)} ${judgePrompt(benchmarkCase.prompt, targetResponse.assistant)}`,
        incognito: true,
        autoApproveSubChats: true,
        benchmarkMetadata: benchmarkMetadata({
          runId,
          suite: benchmarkCase.suite,
          caseId: `${benchmarkCase.id}:judge`,
          targetModel,
          judgeModel,
        }),
        precollectResponse: true,
      });
      const judgment = parseJudgment(judgeResponse.assistant);
      caseResult.judge = {
        model: judgeModel,
        score: judgment.score,
        reason: judgment.reason,
        raw: judgeResponse.assistant,
      };
      caseResult.passed = judgment.score !== null && judgment.score >= 4;
    }

    baseResult.cases.push(caseResult);
  }

  baseResult.summary.passed = baseResult.cases.filter((result) => result.passed).length;
  baseResult.summary.failed = baseResult.cases.length - baseResult.summary.passed;
  writeBenchmarkResult(baseResult, flags, output);
}

export function printBenchmarkHelp(): void {
  console.log(`Benchmark commands:
  openmates benchmark model <provider/model> --confirm-spend-credits [--suite smoke|tools|quality|all] [--runs <n>] [--json]

Runs real incognito chat requests through the OpenMates product path. Live runs
spend the logged-in user's credits and usage entries are grouped as benchmark spend.

Options:
  --confirm-spend-credits       Required for live benchmark runs
  --dry-run                     Preview the benchmark plan without login or spend
  --suite <list>                Comma-separated suites: smoke, tools, quality, all (default: smoke)
  --runs <n>                    Repeat each selected case (default: 1)
  --judge-model <provider/model> Judge for quality cases (default: ${DEFAULT_JUDGE_MODEL})
  --run-id <id>                 Reuse a benchmark run id for grouping
  --output <path>               Save JSON result to a file
  --json                        Print JSON result`);
}

function parseSuites(value: string | boolean | undefined): string[] {
  if (value === undefined || value === false) return ["smoke"];
  if (value === true) throw new Error("--suite requires a value");
  const suites = value.split(",").map((suite) => suite.trim()).filter(Boolean);
  if (suites.includes("all")) return ["smoke", "tools", "quality"];
  const allowed = new Set(["smoke", "tools", "quality"]);
  const invalid = suites.filter((suite) => !allowed.has(suite));
  if (invalid.length > 0 || suites.length === 0) {
    throw new Error("Invalid --suite. Use smoke, tools, quality, or all.");
  }
  return [...new Set(suites)];
}

function parseRuns(value: string | boolean | undefined): number {
  if (value === undefined || value === false) return 1;
  if (value === true) throw new Error("--runs requires a value");
  const parsed = Number.parseInt(value, 10);
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > 20) {
    throw new Error("--runs must be an integer from 1 to 20");
  }
  return parsed;
}

function expandCases(suites: string[], runs: number): Array<BenchmarkCase & { run: number }> {
  const selected = BENCHMARK_CASES.filter((benchmarkCase) => suites.includes(benchmarkCase.suite));
  const expanded: Array<BenchmarkCase & { run: number }> = [];
  for (let run = 1; run <= runs; run += 1) {
    for (const benchmarkCase of selected) expanded.push({ ...benchmarkCase, run });
  }
  return expanded;
}

function modelMention(model: string): string {
  const separator = model.indexOf("/");
  if (separator === -1) return `@ai-model:${model}`;
  const provider = model.slice(0, separator);
  const modelId = model.slice(separator + 1);
  if (!provider || !modelId) return `@ai-model:${model}`;
  return `@ai-model:${modelId}:${provider}`;
}

function benchmarkMetadata(params: {
  runId: string;
  suite: string;
  caseId: string;
  targetModel: string;
  judgeModel: string;
}): BenchmarkMetadata {
  return {
    source: "benchmark",
    benchmark_run_id: params.runId,
    benchmark_suite: params.suite,
    benchmark_case: params.caseId,
    benchmark_target_model: params.targetModel,
    benchmark_judge_model: params.judgeModel,
  };
}

function judgePrompt(prompt: string, answer: string): string {
  return [
    "You are judging a model benchmark response.",
    "Return only JSON with shape {\"score\": number, \"reason\": string}.",
    "Score from 1 to 5 for correctness, clarity, and following instructions.",
    `Benchmark prompt: ${JSON.stringify(prompt)}`,
    `Candidate answer: ${JSON.stringify(answer)}`,
  ].join("\n");
}

function parseJudgment(answer: string): { score: number | null; reason: string | null } {
  const jsonText = extractJsonObject(answer);
  if (!jsonText) return { score: null, reason: null };
  try {
    const parsed = JSON.parse(jsonText) as Record<string, unknown>;
    const score = typeof parsed.score === "number" && Number.isFinite(parsed.score)
      ? parsed.score
      : null;
    const reason = typeof parsed.reason === "string" ? parsed.reason : null;
    return { score, reason };
  } catch {
    return { score: null, reason: null };
  }
}

function extractJsonObject(text: string): string | null {
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)\s*```/i);
  if (fenced) return fenced[1];
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start === -1 || end === -1 || end <= start) return null;
  return text.slice(start, end + 1);
}

function writeBenchmarkResult(result: BenchmarkResult, flags: BenchmarkFlags, output?: string): void {
  const json = `${JSON.stringify(result, null, 2)}\n`;
  if (output) writeFileSync(output, json, "utf-8");
  if (flags.json === true || output) {
    process.stdout.write(json);
    return;
  }

  console.log(`Benchmark ${result.status}: ${result.targetModel}`);
  console.log(`Run ID: ${result.runId}`);
  console.log(`Suites: ${result.suites.join(", ")}`);
  console.log(`Judge: ${result.judgeModel}`);
  console.log(`Spend credits: ${result.spendsCredits ? "yes" : "no"}`);
  if (result.status === "completed") {
    console.log(`Passed: ${result.summary.passed}/${result.summary.total}`);
    for (const benchmarkCase of result.cases) {
      const mark = benchmarkCase.passed ? "PASS" : "FAIL";
      const judge = benchmarkCase.judge?.score !== undefined
        ? ` judge=${benchmarkCase.judge.score ?? "unparsed"}`
        : "";
      console.log(`${mark} ${benchmarkCase.suite}/${benchmarkCase.id} (${benchmarkCase.durationMs}ms)${judge}`);
    }
  }
}
