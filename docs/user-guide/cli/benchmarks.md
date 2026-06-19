---
status: active
doc_type: reference
audience:
  - technical-users
  - contributors
last_verified: 2026-06-19
claims:
  - id: cli-benchmark-docs-cover-help
    type: unit
    claim: Benchmark command reference lists the public benchmark options exposed by CLI help.
    source:
      - frontend/packages/openmates-cli/src/benchmark.ts
    test:
      file: frontend/packages/openmates-cli/tests/cli.test.ts
      command: cd frontend/packages/openmates-cli && npm run build && npm run test:unit:cli
      assertion: cli-benchmark-docs-cover-help
    verified: '2026-06-19'
---

# Benchmark Commands

Run model benchmarks through the real OpenMates CLI chat path. Live benchmark runs spend real credits from the logged-in account and tag usage as `source: "benchmark"` for billing grouping.

## Help

```
openmates benchmark --help
openmates benchmark model <provider/model> [provider/model...] --confirm-spend-credits [--compare]
```

Shows the benchmark command syntax, available suites, spend confirmation flag, comparison mode, judge model option, image fixture option, and JSON output options.

## Dry Run

```
openmates benchmark model google/gemini-3.5-flash --dry-run --json
```

Plans the selected benchmark cases and estimates target plus judge credits without running inference or requiring login.

## Live Run

```
openmates benchmark model google/gemini-3.5-flash --confirm-spend-credits
```

Runs the default quick suite against one target model. `--confirm-spend-credits` is required for any live run.

## Compare Models

```
openmates benchmark model google/gemini-3.5-flash google/gemini-3.1-pro-preview --compare --confirm-spend-credits
```

Runs the same selected cases for each target model and includes per-model summaries and a ranking in JSON output.

## Suites And Case Selection

```
openmates benchmark model anthropic/claude-haiku-4-5-20251001 --suite quick --case quick-image-brandenburger-tor --confirm-spend-credits
openmates benchmark model google/gemini-3.5-flash --suite extensive --extensive-size 10 --confirm-spend-credits
```

Use `--suite quick`, `--suite extensive`, or `--suite all`. Use `--case <id[,id...]>` to run only specific cases from the selected suite. Extensive suite size supports `5`, `10`, or `20` cases.

## Judge Scoring

The default judge is `google/gemini-3-flash-preview`. Override it with `--judge-model <provider/model>`. Judged cases receive a score from `1` to `5`; scores `4` and `5` pass. Some cases also require an `expectedIncludes` text match in the target model response.

## Options

| Option | Purpose |
|--------|---------|
| `--confirm-spend-credits` | Required for live runs because benchmarks spend real credits. |
| `--dry-run` | Estimate cases and credits without inference or login. |
| `--compare` | Compare two or more target models on the same selected cases. |
| `--suite <list>` | Select `quick`, `extensive`, or `all`. |
| `--case <id[,id...]>` | Run only specific case IDs from the selected suite. |
| `--extensive-size <n>` | Select `5`, `10`, or `20` extensive cases. |
| `--runs <n>` | Repeat each selected case. |
| `--parallel <n>` | Set concurrent target case requests. |
| `--judge-model <provider/model>` | Override the default judge model. |
| `--image <path>` | Override the default Brandenburger Tor image fixture. |
| `--run-id <id>` | Reuse a benchmark run ID for grouping. |
| `--output <path>` | Save JSON result to a file. |
| `--json` | Print JSON result to stdout. |

## Output Options

```
openmates benchmark model google/gemini-3.5-flash --dry-run --json
openmates benchmark model google/gemini-3.5-flash --confirm-spend-credits --output ./benchmark-result.json
```

Use `--json` for machine-readable terminal output and `--output <path>` to save the full benchmark result.

## Key Files

- See [benchmark.ts](../../../frontend/packages/openmates-cli/src/benchmark.ts) for suites, case definitions, judge scoring, and command help.
- See [client.ts](../../../frontend/packages/openmates-cli/src/client.ts) for the real chat send path used by benchmark runs.

## Related Docs

- [CLI Overview](./README.md) -- command categories and global flags
- [Billing Settings](./settings.md) -- usage and credit history commands
- [CLI Package Architecture](../../architecture/platforms/cli-package.md) -- package command surface
