/*
 * OpenMates CLI model benchmark runner.
 *
 * Purpose: exercise real chat inference through the CLI product path.
 * Architecture: suite/case runner over OpenMatesClient.sendMessage().
 * Billing: live runs spend the logged-in user's credits and tag usage as benchmark.
 * Security: benchmark metadata is non-sensitive labels only.
 * Tests: covered by CLI command tests and backend usage-source tests.
 */

import { randomUUID } from "node:crypto";
import { existsSync, mkdtempSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import type { BenchmarkMetadata, OpenMatesClient, BenchmarkHistoryMessage } from "./client.js";
import { processFiles, type ProcessedFileEmbed } from "./fileEmbed.js";
import { createEmbedReferenceBlock, toonEncodeContent, type PreparedEmbed } from "./embedCreator.js";
import { uploadFile } from "./uploadService.js";

type BenchmarkFlags = Record<string, string | boolean>;

type SuiteName = "quick" | "extensive";
type ComplexityLevel = "basic" | "medium" | "advanced";

type BenchmarkTurn = {
  prompt: string;
  expectedIncludes?: string;
};

type BenchmarkCase = {
  id: string;
  suite: SuiteName;
  title: string;
  prompt: string;
  complexity: ComplexityLevel;
  category: "smoke" | "math" | "reasoning" | "coding" | "image" | "multi_turn" | "long_context" | "synthesis";
  expectedIncludes?: string;
  judge: boolean;
  estimatedInputTokens: number;
  estimatedOutputTokens: number;
  followUps?: BenchmarkTurn[];
  image?: "default";
  longContext?: boolean;
};

type ModelPricing = {
  provider: string;
  modelId: string;
  inputTokensPerCredit: number;
  outputTokensPerCredit: number;
};

type Estimate = {
  targetCredits: number;
  judgeCredits: number;
  totalCredits: number;
  assumptions: {
    targetInputTokens: number;
    targetOutputTokens: number;
    judgeInputTokens: number;
    judgeOutputTokens: number;
  };
};

type TurnResult = {
  prompt: string;
  assistant: string;
  modelName: string | null;
  durationMs: number;
};

type BenchmarkCaseResult = {
  id: string;
  suite: string;
  title: string;
  model: string;
  run: number;
  complexity: ComplexityLevel;
  category: string;
  prompt: string;
  assistant: string;
  modelName: string | null;
  passed: boolean;
  durationMs: number;
  expectedIncludes?: string;
  turns: TurnResult[];
  error?: string;
  judge?: {
    model: string;
    score: number | null;
    reason: string | null;
    raw: string;
    durationMs: number;
  };
};

type ModelSummary = {
  model: string;
  total: number;
  passed: number;
  failed: number;
  averageJudgeScore: number | null;
  averageDurationMs: number | null;
};

type BenchmarkResult = {
  command: "benchmark model";
  status: "planned" | "completed" | "partial";
  runId: string;
  targetModel: string;
  targetModels: string[];
  judgeModel: string;
  suites: string[];
  runs: number;
  compare: boolean;
  parallel: number;
  extensiveSize: number;
  spendsCredits: boolean;
  estimatedCredits: Estimate;
  cases: BenchmarkCaseResult[];
  modelSummaries: ModelSummary[];
  comparison?: {
    ranking: Array<{ model: string; averageJudgeScore: number | null; passed: number; total: number }>;
    notes: string[];
  };
  summary: {
    total: number;
    completed: number;
    passed: number;
    failed: number;
    skipped: number;
    interrupted: boolean;
  };
};

type CaseJob = {
  model: string;
  benchmarkCase: BenchmarkCase & { run: number };
};

type PreparedImageAttachment = {
  messageSuffix: string;
  embeds: PreparedEmbed[];
};

const DEFAULT_JUDGE_MODEL = "google/gemini-3-flash-preview";
const DEFAULT_EXTENSIVE_SIZE = 10;
const DEFAULT_PARALLEL = 4;
const FIXTURE_IMAGE_SVG = `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="800" viewBox="0 0 1200 800">
  <rect width="1200" height="800" fill="#d8ecff"/>
  <rect y="560" width="1200" height="240" fill="#d7c39a"/>
  <text x="600" y="88" text-anchor="middle" font-family="Arial, sans-serif" font-size="44" font-weight="700" fill="#23344d">Brandenburger Tor, Berlin</text>
  <g transform="translate(160 170)" fill="#c9aa6a" stroke="#5d4522" stroke-width="8">
    <rect x="80" y="160" width="800" height="58"/>
    <rect x="120" y="218" width="720" height="48"/>
    <rect x="150" y="266" width="660" height="42"/>
    <g fill="#d9bd7d">
      <rect x="170" y="308" width="54" height="250"/>
      <rect x="285" y="308" width="54" height="250"/>
      <rect x="400" y="308" width="54" height="250"/>
      <rect x="515" y="308" width="54" height="250"/>
      <rect x="630" y="308" width="54" height="250"/>
      <rect x="745" y="308" width="54" height="250"/>
    </g>
    <rect x="130" y="558" width="700" height="50"/>
    <path d="M480 30 C530 72 620 88 682 48 L720 84 C652 142 530 124 456 78 Z" fill="#3e6f5f"/>
    <circle cx="510" cy="92" r="22" fill="#3e6f5f"/>
    <circle cx="625" cy="92" r="22" fill="#3e6f5f"/>
    <path d="M565 38 l26 78 h-52 z" fill="#3e6f5f"/>
  </g>
  <text x="600" y="740" text-anchor="middle" font-family="Arial, sans-serif" font-size="32" fill="#23344d">Neoclassical gate with Quadriga on top</text>
</svg>
`;

const QUICK_CASES: BenchmarkCase[] = [
  {
    id: "quick-exact-token",
    suite: "quick",
    title: "Exact token smoke test",
    prompt: "Reply with exactly this token and no extra text: BENCHMARK_SMOKE_OK",
    complexity: "basic",
    category: "smoke",
    expectedIncludes: "BENCHMARK_SMOKE_OK",
    judge: true,
    estimatedInputTokens: 12000,
    estimatedOutputTokens: 64,
  },
  {
    id: "quick-arithmetic",
    suite: "quick",
    title: "Arithmetic direct answer",
    prompt: "Compute 19 * 23. Reply with only the integer result.",
    complexity: "basic",
    category: "math",
    expectedIncludes: "437",
    judge: true,
    estimatedInputTokens: 12000,
    estimatedOutputTokens: 64,
  },
  {
    id: "quick-code",
    suite: "quick",
    title: "Small code generation",
    prompt: "Write a TypeScript function isPalindrome(input: string): boolean that ignores spaces, punctuation, and case. Include only the function and one short usage example.",
    complexity: "medium",
    category: "coding",
    judge: true,
    estimatedInputTokens: 12200,
    estimatedOutputTokens: 650,
  },
  {
    id: "quick-image-brandenburger-tor",
    suite: "quick",
    title: "Default image understanding",
    prompt: "Look at the attached image. What landmark is shown, when was it built, and who designed it? Answer in three concise bullet points.",
    complexity: "medium",
    category: "image",
    image: "default",
    expectedIncludes: "Brandenburg",
    judge: true,
    estimatedInputTokens: 13500,
    estimatedOutputTokens: 350,
  },
  {
    id: "quick-followup-continuity",
    suite: "quick",
    title: "Short multi-turn continuity",
    prompt: "Create a three-step plan for evaluating whether a new AI model is ready for production use.",
    complexity: "medium",
    category: "multi_turn",
    judge: true,
    estimatedInputTokens: 14000,
    estimatedOutputTokens: 900,
    followUps: [
      { prompt: "Now make step 2 more concrete with two measurable checks." },
      { prompt: "Summarize the final plan in one sentence." },
    ],
  },
];

const EXTENSIVE_CASES: BenchmarkCase[] = [
  ...QUICK_CASES,
  {
    id: "extensive-coding-debug",
    suite: "extensive",
    title: "Debug a JavaScript bug",
    prompt: "A JavaScript function returns NaN when summing prices from [{price: '12.50'}, {price: undefined}]. Explain the bug and write a corrected function.",
    complexity: "medium",
    category: "coding",
    judge: true,
    estimatedInputTokens: 12300,
    estimatedOutputTokens: 850,
  },
  {
    id: "extensive-coding-api-design",
    suite: "extensive",
    title: "Design a small API contract",
    prompt: "Design a minimal JSON API for creating and listing benchmark runs. Include request/response examples and one validation error.",
    complexity: "advanced",
    category: "coding",
    judge: true,
    estimatedInputTokens: 12300,
    estimatedOutputTokens: 1000,
  },
  {
    id: "extensive-reasoning-tradeoffs",
    suite: "extensive",
    title: "Reason about benchmark tradeoffs",
    prompt: "Compare deterministic assertions and LLM-as-judge evaluation for model benchmarks. Give two strengths and two risks for each.",
    complexity: "medium",
    category: "reasoning",
    judge: true,
    estimatedInputTokens: 12200,
    estimatedOutputTokens: 800,
  },
  {
    id: "extensive-planning",
    suite: "extensive",
    title: "Operational rollout plan",
    prompt: "Create a rollout checklist for switching a production chatbot from one model to another. Include monitoring, rollback, and user-visible risk checks.",
    complexity: "advanced",
    category: "synthesis",
    judge: true,
    estimatedInputTokens: 12300,
    estimatedOutputTokens: 950,
  },
  {
    id: "extensive-long-context-followup",
    suite: "extensive",
    title: "Prebuilt 20-message long chat follow-up",
    prompt: "Based on the earlier discussion, choose the best launch strategy and explain why in five bullets.",
    complexity: "advanced",
    category: "long_context",
    longContext: true,
    judge: true,
    estimatedInputTokens: 18500,
    estimatedOutputTokens: 900,
  },
  {
    id: "extensive-policy-summary",
    suite: "extensive",
    title: "Policy summarization",
    prompt: "Summarize why privacy-preserving benchmark logs should avoid raw user prompts. Include a concrete safer alternative.",
    complexity: "medium",
    category: "reasoning",
    judge: true,
    estimatedInputTokens: 12200,
    estimatedOutputTokens: 650,
  },
  {
    id: "extensive-structured-output",
    suite: "extensive",
    title: "Structured JSON output",
    prompt: "Return only JSON with keys risk, mitigation, and confidence for the risk: benchmark results are biased by prompt wording.",
    complexity: "medium",
    category: "synthesis",
    judge: true,
    estimatedInputTokens: 12200,
    estimatedOutputTokens: 350,
  },
  {
    id: "extensive-creative-constraint",
    suite: "extensive",
    title: "Creative constrained response",
    prompt: "Write a six-line product note announcing model comparisons. Each line must be under 70 characters and avoid hype words like revolutionary or magical.",
    complexity: "medium",
    category: "synthesis",
    judge: true,
    estimatedInputTokens: 12200,
    estimatedOutputTokens: 500,
  },
  {
    id: "extensive-data-reasoning",
    suite: "extensive",
    title: "Interpret metrics",
    prompt: "A benchmark has pass rates 8/10, 7/10, and 9/10 across three runs. Explain what you can and cannot conclude from this sample.",
    complexity: "medium",
    category: "reasoning",
    judge: true,
    estimatedInputTokens: 12200,
    estimatedOutputTokens: 600,
  },
  {
    id: "extensive-security-review",
    suite: "extensive",
    title: "Security review",
    prompt: "Review this benchmark design for security risks: it logs prompts, outputs, model ids, and usage costs to a shared file. List risks and safer defaults.",
    complexity: "advanced",
    category: "reasoning",
    judge: true,
    estimatedInputTokens: 12300,
    estimatedOutputTokens: 850,
  },
  {
    id: "extensive-followup-requirements",
    suite: "extensive",
    title: "Three-turn requirements refinement",
    prompt: "Draft acceptance criteria for a CLI benchmark comparison feature.",
    complexity: "advanced",
    category: "multi_turn",
    judge: true,
    estimatedInputTokens: 14500,
    estimatedOutputTokens: 1100,
    followUps: [
      { prompt: "Add one criterion about cost estimation before live runs." },
      { prompt: "Add one criterion about partial results after interruption." },
      { prompt: "Now compress the criteria to five bullets total." },
    ],
  },
  {
    id: "extensive-coding-tests",
    suite: "extensive",
    title: "Write tests for parser behavior",
    prompt: "Write Node.js test cases for a function parseSuites(value) that accepts quick, extensive, all, and comma-separated lists, and rejects unknown suites.",
    complexity: "medium",
    category: "coding",
    judge: true,
    estimatedInputTokens: 12300,
    estimatedOutputTokens: 950,
  },
  {
    id: "extensive-coding-refactor",
    suite: "extensive",
    title: "Refactor duplicated code",
    prompt: "Given two duplicated TypeScript loops that build arrays of result objects, explain when to extract a helper and write the helper signature.",
    complexity: "medium",
    category: "coding",
    judge: true,
    estimatedInputTokens: 12300,
    estimatedOutputTokens: 750,
  },
  {
    id: "extensive-comparison-analysis",
    suite: "extensive",
    title: "Compare two model outputs",
    prompt: "Explain how you would compare two model outputs when one is concise but misses caveats and the other is verbose but complete.",
    complexity: "medium",
    category: "reasoning",
    judge: true,
    estimatedInputTokens: 12200,
    estimatedOutputTokens: 650,
  },
  {
    id: "extensive-failure-mode",
    suite: "extensive",
    title: "Failure-mode analysis",
    prompt: "List five failure modes for image-understanding benchmarks and one mitigation for each.",
    complexity: "advanced",
    category: "image",
    judge: true,
    estimatedInputTokens: 12300,
    estimatedOutputTokens: 900,
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

  const targetModels = rest.filter((arg) => !arg.startsWith("--"));
  if (targetModels.length === 0) {
    throw new Error("Missing target model. Usage: openmates benchmark model <provider/model> [model-b] --confirm-spend-credits");
  }
  const compare = flags.compare === true;
  if (targetModels.length > 1 && !compare) {
    throw new Error("Multiple target models require --compare.");
  }
  if (compare && targetModels.length < 2) {
    throw new Error("--compare requires at least two target models.");
  }

  const judgeModel = typeof flags["judge-model"] === "string"
    ? flags["judge-model"]
    : DEFAULT_JUDGE_MODEL;
  const suites = parseSuites(flags.suite);
  const runs = parseRuns(flags.runs);
  const extensiveSize = parseExtensiveSize(flags["extensive-size"]);
  const parallel = parseParallel(flags.parallel);
  const dryRun = flags["dry-run"] === true;
  const output = typeof flags.output === "string" ? flags.output : undefined;
  const runId = typeof flags["run-id"] === "string" ? flags["run-id"] : randomUUID();
  const imagePath = typeof flags.image === "string" ? resolve(flags.image) : defaultImageFixturePath();

  if (!dryRun && flags["confirm-spend-credits"] !== true) {
    throw new Error(
      "Benchmark runs spend real credits from the logged-in account. " +
      "Rerun with --confirm-spend-credits, or use --dry-run to preview the plan.",
    );
  }

  const cases = expandCases(suites, runs, extensiveSize);
  const pricing = loadPricingForModels([...targetModels, judgeModel]);
  const estimate = estimateCredits(cases, targetModels, judgeModel, pricing);
  const result = makeBaseResult({
    runId,
    targetModels,
    judgeModel,
    suites,
    runs,
    compare,
    parallel,
    extensiveSize,
    dryRun,
    estimate,
    totalJobs: cases.length * targetModels.length,
  });

  if (dryRun) {
    writeBenchmarkResult(result, flags, output);
    return;
  }

  if (!client.hasSession()) {
    throw new Error("Benchmark runs require login. Run 'openmates login' first.");
  }

  let interrupted = false;
  const onInterrupt = () => {
    interrupted = true;
  };
  process.once("SIGINT", onInterrupt);
  try {
    const jobs = cases.flatMap((benchmarkCase) => targetModels.map((model) => ({ model, benchmarkCase })));
    await runPool(jobs, parallel, async (job) => {
      if (interrupted) return;
      const caseResult = await runCaseJob({ client, job, judgeModel, runId, imagePath });
      result.cases.push(caseResult);
      recomputeResult(result, jobs.length, interrupted);
    });
  } finally {
    process.off("SIGINT", onInterrupt);
  }

  recomputeResult(result, cases.length * targetModels.length, interrupted);
  writeBenchmarkResult(result, flags, output);
}

export function printBenchmarkHelp(): void {
  console.log(`Benchmark commands:
  openmates benchmark model <provider/model> [provider/model...] --confirm-spend-credits [--compare] [--suite quick|extensive|all] [--json]

Runs real incognito chat requests through the OpenMates product path. Live runs
spend the logged-in user's credits and usage entries are grouped as benchmark spend.

Options:
  --confirm-spend-credits       Required for live benchmark runs
  --dry-run                     Preview the benchmark plan without inference or spend
  --compare                     Compare two or more target models
  --suite <list>                Comma-separated suites: quick, extensive, all (default: quick)
  --extensive-size <n>          Extensive cases to run: 5, 10, or 20 (default: ${DEFAULT_EXTENSIVE_SIZE})
  --runs <n>                    Repeat each selected case (default: 1)
  --parallel <n>                Concurrent target case requests (default: ${DEFAULT_PARALLEL})
  --judge-model <provider/model> Judge for evaluated cases (default: ${DEFAULT_JUDGE_MODEL})
  --image <path>                Override default Brandenburger Tor image fixture
  --run-id <id>                 Reuse a benchmark run id for grouping
  --output <path>               Save JSON result to a file
  --json                        Print JSON result`);
}

function parseSuites(value: string | boolean | undefined): SuiteName[] {
  if (value === undefined || value === false) return ["quick"];
  if (value === true) throw new Error("--suite requires a value");
  const suites = value.split(",").map((suite) => suite.trim()).filter(Boolean);
  if (suites.includes("all")) return ["quick", "extensive"];
  const allowed = new Set(["quick", "extensive"]);
  const invalid = suites.filter((suite) => !allowed.has(suite));
  if (invalid.length > 0 || suites.length === 0) {
    throw new Error("Invalid --suite. Use quick, extensive, or all.");
  }
  return [...new Set(suites)] as SuiteName[];
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

function parseExtensiveSize(value: string | boolean | undefined): number {
  if (value === undefined || value === false) return DEFAULT_EXTENSIVE_SIZE;
  if (value === true) throw new Error("--extensive-size requires a value");
  const parsed = Number.parseInt(value, 10);
  if (![5, 10, 20].includes(parsed)) {
    throw new Error("--extensive-size must be 5, 10, or 20");
  }
  return parsed;
}

function parseParallel(value: string | boolean | undefined): number {
  if (value === undefined || value === false) return DEFAULT_PARALLEL;
  if (value === true) throw new Error("--parallel requires a value");
  const parsed = Number.parseInt(value, 10);
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > 20) {
    throw new Error("--parallel must be an integer from 1 to 20");
  }
  return parsed;
}

function expandCases(suites: SuiteName[], runs: number, extensiveSize: number): Array<BenchmarkCase & { run: number }> {
  const selected: BenchmarkCase[] = [];
  if (suites.includes("quick")) selected.push(...QUICK_CASES);
  if (suites.includes("extensive")) selected.push(...selectExtensiveCases(extensiveSize));
  const uniqueSelected = dedupeCases(selected);
  const expanded: Array<BenchmarkCase & { run: number }> = [];
  for (let run = 1; run <= runs; run += 1) {
    for (const benchmarkCase of uniqueSelected) expanded.push({ ...benchmarkCase, run });
  }
  return expanded;
}

function selectExtensiveCases(size: number): BenchmarkCase[] {
  const cases = dedupeCases(EXTENSIVE_CASES).slice(0, size);
  const minimumCoding = Math.ceil(size * 0.15);
  const codingCount = cases.filter((benchmarkCase) => benchmarkCase.category === "coding").length;
  if (codingCount >= minimumCoding) return cases;

  const selectedIds = new Set(cases.map((benchmarkCase) => benchmarkCase.id));
  const codingBackfill = EXTENSIVE_CASES.filter(
    (benchmarkCase) => benchmarkCase.category === "coding" && !selectedIds.has(benchmarkCase.id),
  );
  const result = [...cases];
  for (const codingCase of codingBackfill) {
    let replaceIndex = -1;
    for (let index = result.length - 1; index >= 0; index -= 1) {
      if (result[index]?.category !== "coding") {
        replaceIndex = index;
        break;
      }
    }
    if (replaceIndex === -1) break;
    result[replaceIndex] = codingCase;
    if (result.filter((benchmarkCase) => benchmarkCase.category === "coding").length >= minimumCoding) break;
  }
  return result;
}

function dedupeCases(cases: BenchmarkCase[]): BenchmarkCase[] {
  const seen = new Set<string>();
  const result: BenchmarkCase[] = [];
  for (const benchmarkCase of cases) {
    if (seen.has(benchmarkCase.id)) continue;
    seen.add(benchmarkCase.id);
    result.push(benchmarkCase);
  }
  return result;
}

async function runCaseJob(params: {
  client: OpenMatesClient;
  job: CaseJob;
  judgeModel: string;
  runId: string;
  imagePath: string;
}): Promise<BenchmarkCaseResult> {
  const { client, job, judgeModel, runId, imagePath } = params;
  const { model, benchmarkCase } = job;
  const startedAt = Date.now();
  const turns: TurnResult[] = [];
  const history = benchmarkCase.longContext ? buildLongContextHistory() : [];
  let chatId: string | undefined;

  try {
    const initialPrompt = await buildPromptWithAttachments(client, benchmarkCase, model, imagePath);
    const targetResponse = await sendBenchmarkTurn({
      client,
      model,
      judgeModel,
      runId,
      benchmarkCase,
      prompt: initialPrompt.message,
      chatId,
      history,
      preparedEmbeds: initialPrompt.embeds,
      caseId: benchmarkCase.id,
    });
    chatId = targetResponse.chatId;
    turns.push(targetResponse.turn);
    appendHistory(history, "user", initialPrompt.message);
    appendHistory(history, "assistant", targetResponse.turn.assistant);

    for (const [index, followUp] of (benchmarkCase.followUps ?? []).entries()) {
      const response = await sendBenchmarkTurn({
        client,
        model,
        judgeModel,
        runId,
        benchmarkCase,
        prompt: `${modelMention(model)} ${followUp.prompt}`,
        chatId,
        history,
        caseId: `${benchmarkCase.id}:followup-${index + 1}`,
      });
      chatId = response.chatId;
      turns.push(response.turn);
      appendHistory(history, "user", response.rawPrompt);
      appendHistory(history, "assistant", response.turn.assistant);
    }

    const assistant = turns.at(-1)?.assistant ?? "";
    const caseResult: BenchmarkCaseResult = {
      id: benchmarkCase.id,
      suite: benchmarkCase.suite,
      title: benchmarkCase.title,
      model,
      run: benchmarkCase.run,
      complexity: benchmarkCase.complexity,
      category: benchmarkCase.category,
      prompt: benchmarkCase.prompt,
      assistant,
      modelName: turns.at(-1)?.modelName ?? null,
      passed: benchmarkCase.expectedIncludes ? assistant.includes(benchmarkCase.expectedIncludes) : true,
      durationMs: Date.now() - startedAt,
      expectedIncludes: benchmarkCase.expectedIncludes,
      turns,
    };
    if (benchmarkCase.judge) {
      caseResult.judge = await judgeCase({ client, judgeModel, targetModel: model, benchmarkCase, caseResult, runId });
      caseResult.passed = caseResult.judge.score !== null && caseResult.judge.score >= 4 && caseResult.passed;
    }
    return caseResult;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return {
      id: benchmarkCase.id,
      suite: benchmarkCase.suite,
      title: benchmarkCase.title,
      model,
      run: benchmarkCase.run,
      complexity: benchmarkCase.complexity,
      category: benchmarkCase.category,
      prompt: benchmarkCase.prompt,
      assistant: turns.at(-1)?.assistant ?? "",
      modelName: turns.at(-1)?.modelName ?? null,
      passed: false,
      durationMs: Date.now() - startedAt,
      expectedIncludes: benchmarkCase.expectedIncludes,
      turns,
      error: message,
    };
  }
}

async function sendBenchmarkTurn(params: {
  client: OpenMatesClient;
  model: string;
  judgeModel: string;
  runId: string;
  benchmarkCase: BenchmarkCase;
  prompt: string;
  chatId?: string;
  history: BenchmarkHistoryMessage[];
  preparedEmbeds?: PreparedEmbed[];
  caseId: string;
}): Promise<{ chatId: string; turn: TurnResult; rawPrompt: string }> {
  const startedAt = Date.now();
  const response = await params.client.sendMessage({
    message: params.prompt,
    chatId: params.chatId,
    incognito: true,
    autoApproveSubChats: true,
    benchmarkMetadata: benchmarkMetadata({
      runId: params.runId,
      suite: params.benchmarkCase.suite,
      caseId: params.caseId,
      targetModel: params.model,
      judgeModel: params.judgeModel,
    }),
    messageHistory: params.history,
    preparedEmbeds: params.preparedEmbeds,
    precollectResponse: true,
  });
  return {
    chatId: response.chatId,
    rawPrompt: params.prompt,
    turn: {
      prompt: params.prompt,
      assistant: response.assistant,
      modelName: response.modelName,
      durationMs: Date.now() - startedAt,
    },
  };
}

async function buildPromptWithAttachments(
  client: OpenMatesClient,
  benchmarkCase: BenchmarkCase,
  model: string,
  imagePath: string,
): Promise<{ message: string; embeds?: PreparedEmbed[] }> {
  const baseMessage = `${modelMention(model)} ${benchmarkCase.prompt}`;
  if (benchmarkCase.image !== "default") return { message: baseMessage };
  const attachment = await prepareImageAttachment(client, imagePath);
  return { message: `${baseMessage}\n\n${attachment.messageSuffix}`, embeds: attachment.embeds };
}

async function prepareImageAttachment(client: OpenMatesClient, imagePath: string): Promise<PreparedImageAttachment> {
  if (!existsSync(imagePath)) throw new Error(`Benchmark image not found: ${imagePath}`);
  const processed = processFiles([imagePath], null);
  if (processed.blocked.length > 0 || processed.errors.length > 0 || processed.embeds.length === 0) {
    const reason = [...processed.blocked, ...processed.errors].map((entry) => entry.error).join("; ") || "no image embed produced";
    throw new Error(`Failed to prepare benchmark image: ${reason}`);
  }
  const fileEmbed = processed.embeds[0];
  if (!fileEmbed.requiresUpload || !fileEmbed.localPath) {
    return { messageSuffix: fileEmbed.referenceBlock, embeds: [fileEmbed.embed] };
  }
  await uploadBenchmarkImage(client, fileEmbed);
  return { messageSuffix: fileEmbed.referenceBlock, embeds: [fileEmbed.embed] };
}

async function uploadBenchmarkImage(client: OpenMatesClient, fileEmbed: ProcessedFileEmbed): Promise<void> {
  if (!fileEmbed.localPath) return;
  const uploadResult = await uploadFile(fileEmbed.localPath, client.getSession());
  const embedRef = fileEmbed.embed.embedRef ?? `benchmark-image-${uploadResult.embed_id.slice(0, 8)}`;
  fileEmbed.embed.embedRef = embedRef;
  fileEmbed.embed.content = toonEncodeContent({
    type: "image",
    app_id: "images",
    skill_id: "upload",
    status: "finished",
    filename: fileEmbed.displayName,
    embed_ref: embedRef,
    content_hash: uploadResult.content_hash,
    s3_base_url: uploadResult.s3_base_url,
    files: uploadResult.files,
    aes_key: uploadResult.aes_key,
    aes_nonce: uploadResult.aes_nonce,
    vault_wrapped_aes_key: uploadResult.vault_wrapped_aes_key,
    ai_detection: uploadResult.ai_detection,
  });
  fileEmbed.embed.status = "finished";
  fileEmbed.embed.contentHash = uploadResult.content_hash;
  fileEmbed.embed.embedId = uploadResult.embed_id;
  fileEmbed.referenceBlock = createEmbedReferenceBlock(embedRef);
}

async function judgeCase(params: {
  client: OpenMatesClient;
  judgeModel: string;
  targetModel: string;
  benchmarkCase: BenchmarkCase;
  caseResult: BenchmarkCaseResult;
  runId: string;
}): Promise<NonNullable<BenchmarkCaseResult["judge"]>> {
  const startedAt = Date.now();
  const judgeResponse = await params.client.sendMessage({
    message: `${modelMention(params.judgeModel)} ${judgePrompt(params.targetModel, params.benchmarkCase, params.caseResult)}`,
    incognito: true,
    autoApproveSubChats: true,
    benchmarkMetadata: benchmarkMetadata({
      runId: params.runId,
      suite: params.benchmarkCase.suite,
      caseId: `${params.benchmarkCase.id}:judge:${params.targetModel}`,
      targetModel: params.targetModel,
      judgeModel: params.judgeModel,
    }),
    precollectResponse: true,
  });
  const judgment = parseJudgment(judgeResponse.assistant);
  return {
    model: params.judgeModel,
    score: judgment.score,
    reason: judgment.reason,
    raw: judgeResponse.assistant,
    durationMs: Date.now() - startedAt,
  };
}

async function runPool<T>(items: T[], parallel: number, worker: (item: T) => Promise<void>): Promise<void> {
  let index = 0;
  const workers = Array.from({ length: Math.min(parallel, items.length) }, async () => {
    while (index < items.length) {
      const item = items[index];
      index += 1;
      await worker(item);
    }
  });
  await Promise.all(workers);
}

function buildLongContextHistory(): BenchmarkHistoryMessage[] {
  const now = Math.floor(Date.now() / 1000) - 2_000;
  const topics = [
    ["user", "We need to launch a CLI benchmark for model comparisons."],
    ["assistant", "The first goal should be a quick suite with deterministic checks."],
    ["user", "The benchmark also needs image inference."],
    ["assistant", "Use a public fixture image and ask a factual visual question."],
    ["user", "We should avoid wasting credits."],
    ["assistant", "Run a pricing preflight and require explicit spend confirmation."],
    ["user", "What about longer conversations?"],
    ["assistant", "Add a 20-message predefined history and a dependent follow-up."],
    ["user", "The extensive suite should not be too small."],
    ["assistant", "Default to 10 cases and allow 5 or 20 as alternatives."],
    ["user", "Coding quality matters."],
    ["assistant", "Reserve at least 15 percent of extensive cases for coding prompts."],
    ["user", "We also need comparison mode."],
    ["assistant", "Accept multiple models with --compare and run target jobs in parallel."],
    ["user", "How should judging work?"],
    ["assistant", "Judge each completed case immediately with Gemini so partial results remain useful."],
    ["user", "What if the process is interrupted?"],
    ["assistant", "Print or write a partial summary with completed judgments and skipped counts."],
    ["user", "What is the best launch strategy?"],
    ["assistant", "Ship quick and comparison first, then use extensive for slower releases."],
  ];
  return topics.map(([role, content], index) => ({
    message_id: `benchmark-history-${index + 1}`,
    role: role as "user" | "assistant",
    sender_name: role === "user" ? "User" : "Assistant",
    content,
    created_at: now + index * 30,
  }));
}

function appendHistory(history: BenchmarkHistoryMessage[], role: "user" | "assistant", content: string): void {
  history.push({
    message_id: randomUUID(),
    role,
    sender_name: role === "user" ? "User" : "Assistant",
    content,
    created_at: Math.floor(Date.now() / 1000),
  });
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

function judgePrompt(targetModel: string, benchmarkCase: BenchmarkCase, result: BenchmarkCaseResult): string {
  return [
    "You are judging a real OpenMates model benchmark response.",
    "Return exactly two plain-text lines, with no markdown, no code block, and no tool use.",
    "Line 1 format: BENCHMARK_SCORE=<integer from 1 to 5>",
    "Line 2 format: BENCHMARK_REASON=<one short sentence>",
    "Score for correctness, instruction-following, usefulness, and continuity where relevant.",
    `Target model: ${targetModel}`,
    `Benchmark case: ${benchmarkCase.id} (${benchmarkCase.category}, ${benchmarkCase.complexity})`,
    `Initial prompt: ${JSON.stringify(benchmarkCase.prompt)}`,
    `Turns: ${JSON.stringify(result.turns.map((turn) => ({ prompt: turn.prompt, assistant: turn.assistant })))}`,
  ].join("\n");
}

function parseJudgment(answer: string): { score: number | null; reason: string | null } {
  const markerScore = answer.match(/BENCHMARK_SCORE\s*=\s*([1-5])/i);
  if (markerScore) {
    const reasonMatch = answer.match(/BENCHMARK_REASON\s*=\s*(.+)/i);
    return {
      score: Number.parseInt(markerScore[1], 10),
      reason: reasonMatch?.[1]?.trim() ?? null,
    };
  }
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

function loadPricingForModels(models: string[]): Map<string, ModelPricing> {
  const availablePricing = loadProviderPricing();
  const pricing = new Map<string, ModelPricing>();
  const missing: string[] = [];
  for (const model of [...new Set(models)]) {
    const key = normalizeModelKey(model);
    const modelPricing = availablePricing.get(key);
    if (!modelPricing) {
      missing.push(model);
      continue;
    }
    pricing.set(model, modelPricing);
  }
  if (missing.length > 0) {
    throw new Error(
      `Cannot estimate benchmark cost because pricing metadata is unavailable for: ${missing.join(", ")}. ` +
      "Use provider/model ids with backend provider pricing metadata.",
    );
  }
  return pricing;
}

function loadProviderPricing(): Map<string, ModelPricing> {
  const providersDir = findProvidersDir();
  const pricing = new Map<string, ModelPricing>();
  if (!providersDir) return pricing;
  for (const fileName of readdirSync(providersDir)) {
    if (!fileName.endsWith(".yml")) continue;
    const filePath = join(providersDir, fileName);
    const text = readFileSync(filePath, "utf-8");
    const provider = parseProviderId(text) ?? fileName.replace(/\.yml$/, "");
    for (const modelPricing of parseModelPricing(text, provider)) {
      pricing.set(`${modelPricing.provider}/${modelPricing.modelId}`, modelPricing);
      pricing.set(modelPricing.modelId, modelPricing);
    }
  }
  return pricing;
}

function parseProviderId(text: string): string | null {
  const match = text.match(/^provider_id:\s*["']?([^"'\n]+)["']?/m);
  return match?.[1]?.trim() ?? null;
}

function parseModelPricing(text: string, provider: string): ModelPricing[] {
  const lines = text.split("\n");
  const results: ModelPricing[] = [];
  let modelId: string | null = null;
  let inModel = false;
  let inputTokensPerCredit: number | null = null;
  let outputTokensPerCredit: number | null = null;
  for (const line of lines) {
    const modelMatch = line.match(/^\s{2}-\s+id:\s*["']?([^"'\n#]+)["']?/);
    if (modelMatch) {
      if (inModel && modelId && inputTokensPerCredit && outputTokensPerCredit) {
        results.push({ provider, modelId, inputTokensPerCredit, outputTokensPerCredit });
      }
      inModel = true;
      modelId = modelMatch[1].trim();
      inputTokensPerCredit = null;
      outputTokensPerCredit = null;
      continue;
    }
    if (!inModel) continue;
    const inputMatch = line.match(/^\s{10}per_credit_unit:\s*(\d+)/);
    if (inputMatch && inputTokensPerCredit === null) {
      inputTokensPerCredit = Number.parseInt(inputMatch[1], 10);
      continue;
    }
    if (inputMatch && inputTokensPerCredit !== null && outputTokensPerCredit === null) {
      outputTokensPerCredit = Number.parseInt(inputMatch[1], 10);
    }
  }
  if (inModel && modelId && inputTokensPerCredit && outputTokensPerCredit) {
    results.push({ provider, modelId, inputTokensPerCredit, outputTokensPerCredit });
  }
  return results;
}

function normalizeModelKey(model: string): string {
  return model.includes("/") ? model : model;
}

function findProvidersDir(): string | null {
  const currentFile = fileURLToPath(import.meta.url);
  let current = dirname(currentFile);
  for (let index = 0; index < 8; index += 1) {
    const candidate = join(current, "backend", "providers");
    if (existsSync(candidate)) return candidate;
    const parentCandidate = join(current, "..", "..", "backend", "providers");
    if (existsSync(parentCandidate)) return resolve(parentCandidate);
    const next = dirname(current);
    if (next === current) break;
    current = next;
  }
  return null;
}

function estimateCredits(
  cases: Array<BenchmarkCase & { run: number }>,
  targetModels: string[],
  judgeModel: string,
  pricing: Map<string, ModelPricing>,
): Estimate {
  let targetCredits = 0;
  let judgeCredits = 0;
  let targetInputTokens = 0;
  let targetOutputTokens = 0;
  let judgeInputTokens = 0;
  let judgeOutputTokens = 0;
  for (const benchmarkCase of cases) {
    const turnCount = 1 + (benchmarkCase.followUps?.length ?? 0);
    for (const model of targetModels) {
      const modelPricing = pricing.get(model);
      if (!modelPricing) continue;
      const input = benchmarkCase.estimatedInputTokens * turnCount;
      const output = benchmarkCase.estimatedOutputTokens * turnCount;
      targetInputTokens += input;
      targetOutputTokens += output;
      targetCredits += creditsFor(modelPricing, input, output);
      if (benchmarkCase.judge) {
        const judgePricing = pricing.get(judgeModel);
        if (!judgePricing) continue;
        const judgeInput = Math.max(2000, Math.ceil(output * 1.5));
        const judgeOutput = 350;
        judgeInputTokens += judgeInput;
        judgeOutputTokens += judgeOutput;
        judgeCredits += creditsFor(judgePricing, judgeInput, judgeOutput);
      }
    }
  }
  return {
    targetCredits,
    judgeCredits,
    totalCredits: targetCredits + judgeCredits,
    assumptions: { targetInputTokens, targetOutputTokens, judgeInputTokens, judgeOutputTokens },
  };
}

function creditsFor(pricing: ModelPricing, inputTokens: number, outputTokens: number): number {
  return Math.ceil(inputTokens / pricing.inputTokensPerCredit) + Math.ceil(outputTokens / pricing.outputTokensPerCredit);
}

function makeBaseResult(params: {
  runId: string;
  targetModels: string[];
  judgeModel: string;
  suites: SuiteName[];
  runs: number;
  compare: boolean;
  parallel: number;
  extensiveSize: number;
  dryRun: boolean;
  estimate: Estimate;
  totalJobs: number;
}): BenchmarkResult {
  return {
    command: "benchmark model",
    status: params.dryRun ? "planned" : "completed",
    runId: params.runId,
    targetModel: params.targetModels[0],
    targetModels: params.targetModels,
    judgeModel: params.judgeModel,
    suites: params.suites,
    runs: params.runs,
    compare: params.compare,
    parallel: params.parallel,
    extensiveSize: params.extensiveSize,
    spendsCredits: !params.dryRun,
    estimatedCredits: params.estimate,
    cases: [],
    modelSummaries: params.targetModels.map((model) => ({
      model,
      total: 0,
      passed: 0,
      failed: 0,
      averageJudgeScore: null,
      averageDurationMs: null,
    })),
    summary: {
      total: params.totalJobs,
      completed: 0,
      passed: 0,
      failed: 0,
      skipped: params.dryRun ? params.totalJobs : 0,
      interrupted: false,
    },
  };
}

function recomputeResult(result: BenchmarkResult, totalJobs: number, interrupted: boolean): void {
  const completed = result.cases.length;
  const passed = result.cases.filter((caseResult) => caseResult.passed).length;
  const failed = result.cases.filter((caseResult) => !caseResult.passed).length;
  result.summary = {
    total: totalJobs,
    completed,
    passed,
    failed,
    skipped: Math.max(0, totalJobs - completed),
    interrupted,
  };
  result.status = interrupted || completed < totalJobs ? "partial" : "completed";
  result.modelSummaries = result.targetModels.map((model) => summarizeModel(model, result.cases));
  if (result.compare) result.comparison = buildComparison(result.modelSummaries);
}

function summarizeModel(model: string, cases: BenchmarkCaseResult[]): ModelSummary {
  const modelCases = cases.filter((caseResult) => caseResult.model === model);
  const scores = modelCases
    .map((caseResult) => caseResult.judge?.score)
    .filter((score): score is number => typeof score === "number" && Number.isFinite(score));
  const durations = modelCases.map((caseResult) => caseResult.durationMs).filter((value) => value > 0);
  return {
    model,
    total: modelCases.length,
    passed: modelCases.filter((caseResult) => caseResult.passed).length,
    failed: modelCases.filter((caseResult) => !caseResult.passed).length,
    averageJudgeScore: scores.length > 0 ? round2(scores.reduce((sum, score) => sum + score, 0) / scores.length) : null,
    averageDurationMs: durations.length > 0 ? Math.round(durations.reduce((sum, value) => sum + value, 0) / durations.length) : null,
  };
}

function buildComparison(summaries: ModelSummary[]): NonNullable<BenchmarkResult["comparison"]> {
  const ranking = [...summaries]
    .sort((a, b) => (b.averageJudgeScore ?? -1) - (a.averageJudgeScore ?? -1) || b.passed - a.passed)
    .map((summary) => ({
      model: summary.model,
      averageJudgeScore: summary.averageJudgeScore,
      passed: summary.passed,
      total: summary.total,
    }));
  const notes = ranking.length > 0
    ? [`Top model so far: ${ranking[0].model} (${ranking[0].passed}/${ranking[0].total} passed).`]
    : [];
  return { ranking, notes };
}

function round2(value: number): number {
  return Math.round(value * 100) / 100;
}

function defaultImageFixturePath(): string {
  const fixtureDir = join(dirname(fileURLToPath(import.meta.url)), "..", "fixtures");
  const fixturePath = join(fixtureDir, "brandenburger-tor.png");
  if (existsSync(fixturePath)) return fixturePath;
  const tempDir = mkdtempSync(join(tmpdir(), "openmates-benchmark-"));
  const tempPath = join(tempDir, "brandenburger-tor.svg");
  writeFileSync(tempPath, FIXTURE_IMAGE_SVG, "utf-8");
  return tempPath;
}

function writeBenchmarkResult(result: BenchmarkResult, flags: BenchmarkFlags, output?: string): void {
  const json = `${JSON.stringify(result, null, 2)}\n`;
  if (output) writeFileSync(output, json, "utf-8");
  if (flags.json === true || output) {
    process.stdout.write(json);
    return;
  }

  console.log(`Benchmark ${result.status}: ${result.targetModels.join(", ")}`);
  console.log(`Run ID: ${result.runId}`);
  console.log(`Suites: ${result.suites.join(", ")}`);
  console.log(`Judge: ${result.judgeModel}`);
  console.log(`Estimated credits: ${result.estimatedCredits.totalCredits}`);
  console.log(`Spend credits: ${result.spendsCredits ? "yes" : "no"}`);
  if (result.status !== "planned") {
    console.log(`Passed: ${result.summary.passed}/${result.summary.completed} completed (${result.summary.skipped} skipped)`);
    for (const benchmarkCase of result.cases) {
      const mark = benchmarkCase.passed ? "PASS" : "FAIL";
      const judge = benchmarkCase.judge ? ` judge=${benchmarkCase.judge.score ?? "unparsed"}` : "";
      const error = benchmarkCase.error ? ` error=${benchmarkCase.error}` : "";
      console.log(`${mark} ${benchmarkCase.model} ${benchmarkCase.suite}/${benchmarkCase.id} (${benchmarkCase.durationMs}ms)${judge}${error}`);
    }
  }
}
