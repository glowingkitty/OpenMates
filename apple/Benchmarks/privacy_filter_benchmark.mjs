#!/usr/bin/env node
// Mac benchmark for OpenAI Privacy Filter via Transformers.js.
// Uses synthetic OpenMates-style fixtures and avoids printing raw PII values.
// Measures detection quality against expected spans plus a simple regex baseline.
// Records wall-clock latency, process memory, CPU usage, and selected runtime.
// Intended for Apple Remote runs on real Mac hardware before product integration.

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { performance } from 'node:perf_hooks';
import { fileURLToPath, pathToFileURL } from 'node:url';

const MODEL_ID = 'openai/privacy-filter';
const CURRENT_DIR = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_FIXTURES = path.join(CURRENT_DIR, 'privacy_filter_fixtures.json');

function parseArgs() {
  const args = {
    fixtures: DEFAULT_FIXTURES,
    output: null,
    repeat: 2,
    device: 'auto',
    dtype: 'q4',
  };
  for (let index = 2; index < process.argv.length; index += 1) {
    const value = process.argv[index];
    if (value === '--fixtures') args.fixtures = process.argv[++index];
    else if (value === '--output') args.output = process.argv[++index];
    else if (value === '--repeat') args.repeat = Number(process.argv[++index]);
    else if (value === '--device') args.device = process.argv[++index];
    else if (value === '--dtype') args.dtype = process.argv[++index];
    else throw new Error(`Unknown argument: ${value}`);
  }
  if (!Number.isInteger(args.repeat) || args.repeat < 1) {
    throw new Error('--repeat must be a positive integer');
  }
  return args;
}

async function importTransformers() {
  const override = process.env.TRANSFORMERS_JS_MODULE;
  if (override) {
    const modulePath = override.startsWith('file:') ? override : pathToFileURL(override).href;
    return import(modulePath);
  }
  return import('@huggingface/transformers');
}

function normalizeLabel(label) {
  const normalized = String(label || '').trim().toLowerCase().replace(/^[bies]-/, '');
  const aliases = new Map([
    ['email', 'private_email'],
    ['phone', 'private_phone'],
    ['url', 'private_url'],
    ['date', 'private_date'],
    ['person', 'private_person'],
    ['address', 'private_address'],
    ['account', 'account_number'],
    ['credential', 'secret'],
  ]);
  return aliases.get(normalized) || normalized;
}

function loadFixtures(filePath) {
  const fixtures = JSON.parse(fs.readFileSync(filePath, 'utf8'));
  if (!Array.isArray(fixtures)) throw new Error('Fixture file must contain an array');
  return fixtures;
}

function expectedSpans(fixture) {
  return fixture.expected.map((expected) => {
    const start = fixture.text.indexOf(expected.text);
    if (start < 0) throw new Error(`Expected text not found in fixture ${fixture.id}`);
    return {
      label: normalizeLabel(expected.label),
      start,
      end: start + expected.text.length,
    };
  });
}

function overlaps(aStart, aEnd, bStart, bEnd) {
  return Math.max(aStart, bStart) < Math.min(aEnd, bEnd);
}

function labelCompatible(actual, expected) {
  return actual === expected || (expected === 'secret' && actual === 'account_number');
}

function evaluate(expected, detections) {
  const matched = new Set();
  const missed = [];
  const mismatches = [];
  for (const span of expected) {
    const overlapping = detections
      .map((detection, index) => ({ detection, index }))
      .filter(({ detection }) => overlaps(span.start, span.end, detection.start, detection.end));
    const compatible = overlapping.find(({ detection }) => labelCompatible(detection.label, span.label));
    if (compatible) {
      matched.add(compatible.index);
      continue;
    }
    if (overlapping.length > 0) {
      matched.add(overlapping[0].index);
      mismatches.push({ expected: span.label, detected: overlapping[0].detection.label });
      continue;
    }
    missed.push(span);
  }
  const falsePositives = detections.filter((_, index) => !matched.has(index));
  return {
    expected_count: expected.length,
    detected_count: detections.length,
    hit_count: expected.length - missed.length - mismatches.length,
    miss_count: missed.length,
    label_mismatch_count: mismatches.length,
    false_positive_count: falsePositives.length,
    missed_labels: missed.map((span) => span.label).sort(),
    false_positive_labels: falsePositives.map((detection) => detection.label).sort(),
    label_mismatches: mismatches,
  };
}

function aggregate(items) {
  const expected = items.reduce((sum, item) => sum + item.expected_count, 0);
  const hits = items.reduce((sum, item) => sum + item.hit_count, 0);
  const detected = items.reduce((sum, item) => sum + item.detected_count, 0);
  const misses = items.reduce((sum, item) => sum + item.miss_count, 0);
  const mismatches = items.reduce((sum, item) => sum + item.label_mismatch_count, 0);
  const falsePositives = items.reduce((sum, item) => sum + item.false_positive_count, 0);
  const precisionDenominator = hits + mismatches + falsePositives;
  const precision = precisionDenominator === 0 ? 1 : hits / precisionDenominator;
  const recall = expected === 0 ? 1 : hits / expected;
  const f1 = precision + recall === 0 ? 0 : (2 * precision * recall) / (precision + recall);
  return {
    fixtures: items.length,
    expected_total: expected,
    detected_total: detected,
    hit_total: hits,
    miss_total: misses,
    label_mismatch_total: mismatches,
    false_positive_total: falsePositives,
    precision: round(precision, 4),
    recall: round(recall, 4),
    f1: round(f1, 4),
  };
}

function regexBaseline(text) {
  const patterns = [
    ['private_email', /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi],
    ['private_phone', /(?:\+|00)?\d[\d\s()./-]{7,}\d/g],
    ['private_url', /https?:\/\/[^\s]+/gi],
    ['account_number', /\b(?:\d[ -]?){12,19}\b|\b[A-Z]{2}\d{2}(?:[\s]?[A-Z0-9]{4}){3,7}\b/g],
    ['private_date', /\b(?:\d{4}-\d{2}-\d{2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+\d{4})\b/gi],
    ['secret', /\b(?:sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|password\s*=\s*[^\s.]+|-----BEGIN [A-Z ]*PRIVATE KEY-----)/g],
  ];
  const occupied = [];
  const detections = [];
  for (const [label, pattern] of patterns) {
    for (const match of text.matchAll(pattern)) {
      const start = match.index;
      const end = start + match[0].length;
      if (occupied.some(([aStart, aEnd]) => overlaps(start, end, aStart, aEnd))) continue;
      occupied.push([start, end]);
      detections.push({ label, start, end, score: null });
    }
  }
  return detections.sort((first, second) => first.start - second.start);
}

async function createPipeline(pipeline, args) {
  const attempts = args.device === 'auto' ? ['webgpu', 'wasm'] : [args.device];
  const errors = [];
  for (const device of attempts) {
    try {
      const started = performance.now();
      const classifier = await pipeline('token-classification', MODEL_ID, {
        device,
        dtype: args.dtype,
      });
      return {
        classifier,
        runtime: { device, dtype: args.dtype, load_time_ms: round(performance.now() - started, 2) },
      };
    } catch (error) {
      errors.push(`${device}: ${error.message}`);
    }
  }
  throw new Error(`Unable to load model with Transformers.js: ${errors.join(' | ')}`);
}

async function modelDetections(classifier, text) {
  const raw = await classifier(text, { aggregation_strategy: 'simple' });
  let cursor = 0;
  return raw
    .map((item) => {
      const fallbackWord = String(item.word || '').trim();
      let start = Number(item.start);
      let end = Number(item.end);
      if ((!Number.isInteger(start) || !Number.isInteger(end)) && fallbackWord) {
        const found = text.indexOf(fallbackWord, cursor);
        if (found >= 0) {
          start = found;
          end = found + fallbackWord.length;
          cursor = end;
        }
      }
      return {
        label: normalizeLabel(item.entity_group || item.entity),
        start,
        end,
        score: item.score == null ? null : Number(item.score),
      };
    })
    .filter((item) => Number.isInteger(item.start) && Number.isInteger(item.end))
    .sort((first, second) => first.start - second.start);
}

async function timed(callback, repeat) {
  const durations = [];
  let output = [];
  for (let index = 0; index < repeat; index += 1) {
    const started = performance.now();
    output = await callback();
    durations.push(performance.now() - started);
  }
  return { output, durations };
}

function latencySummary(values) {
  const sorted = [...values].sort((first, second) => first - second);
  return {
    count: values.length,
    mean_ms: round(values.reduce((sum, value) => sum + value, 0) / values.length, 2),
    median_ms: round(sorted[Math.floor(sorted.length / 2)], 2),
    p95_ms: round(sorted[Math.min(sorted.length - 1, Math.round((sorted.length - 1) * 0.95))], 2),
    max_ms: round(Math.max(...values), 2),
  };
}

function sanitizedDetections(detections) {
  return detections.map((detection) => ({
    label: detection.label,
    start: detection.start,
    end: detection.end,
    length: detection.end - detection.start,
    score: detection.score == null ? null : round(detection.score, 4),
  }));
}

function memorySnapshot() {
  const usage = process.memoryUsage();
  return {
    rss_mb: round(usage.rss / 1024 / 1024, 2),
    heap_used_mb: round(usage.heapUsed / 1024 / 1024, 2),
    external_mb: round(usage.external / 1024 / 1024, 2),
  };
}

function cpuPercent(startUsage, elapsedMs) {
  const usage = process.cpuUsage(startUsage);
  const cpuMs = (usage.user + usage.system) / 1000;
  return elapsedMs > 0 ? round((cpuMs / elapsedMs) * 100, 2) : null;
}

function round(value, digits) {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

async function main() {
  const args = parseArgs();
  const fixtures = loadFixtures(args.fixtures);
  const { pipeline, env } = await importTransformers();
  if (env?.allowLocalModels !== undefined) env.allowLocalModels = true;
  const startCpu = process.cpuUsage();
  const startWall = performance.now();
  const startMemory = memorySnapshot();
  const { classifier, runtime } = await createPipeline(pipeline, args);
  const afterLoadMemory = memorySnapshot();
  const modelCases = [];
  const regexCases = [];
  const modelLatencies = [];
  const regexLatencies = [];

  for (const fixture of fixtures) {
    const expected = expectedSpans(fixture);
    const modelTimed = await timed(() => modelDetections(classifier, fixture.text), args.repeat);
    const regexTimed = await timed(() => Promise.resolve(regexBaseline(fixture.text)), args.repeat);
    modelLatencies.push(...modelTimed.durations);
    regexLatencies.push(...regexTimed.durations);
    modelCases.push({
      id: fixture.id,
      description: fixture.description,
      char_count: fixture.text.length,
      expected_labels: expected.map((span) => span.label).sort(),
      evaluation: evaluate(expected, modelTimed.output),
      latency: latencySummary(modelTimed.durations),
      detections: sanitizedDetections(modelTimed.output),
    });
    regexCases.push({
      id: fixture.id,
      evaluation: evaluate(expected, regexTimed.output),
      latency: latencySummary(regexTimed.durations),
      detections: sanitizedDetections(regexTimed.output),
    });
  }

  const elapsedMs = performance.now() - startWall;
  const report = {
    created_at: new Date().toISOString(),
    host: {
      platform: process.platform,
      arch: process.arch,
      node: process.version,
      cpus: os.cpus().length,
      total_memory_mb: round(os.totalmem() / 1024 / 1024, 2),
    },
    model: {
      model: MODEL_ID,
      runtime: 'transformers.js',
      ...runtime,
    },
    run_config: {
      fixtures: args.fixtures,
      repeat: args.repeat,
    },
    accuracy: {
      openai_privacy_filter: aggregate(modelCases.map((item) => item.evaluation)),
      regex_baseline: aggregate(regexCases.map((item) => item.evaluation)),
    },
    performance: {
      openai_privacy_filter_latency: latencySummary(modelLatencies),
      regex_baseline_latency: latencySummary(regexLatencies),
      wall_time_ms: round(elapsedMs, 2),
      process_cpu_percent_mean: cpuPercent(startCpu, elapsedMs),
      memory_start: startMemory,
      memory_after_load: afterLoadMemory,
      memory_end: memorySnapshot(),
      gpu_or_ane_note: 'Transformers.js runtime selected device is recorded; use Instruments or powermetrics for external GPU/ANE counters.',
    },
    cases: {
      openai_privacy_filter: modelCases,
      regex_baseline: regexCases,
    },
  };

  if (args.output) {
    fs.writeFileSync(args.output, `${JSON.stringify(report, null, 2)}\n`);
  }

  const modelAccuracy = report.accuracy.openai_privacy_filter;
  const regexAccuracy = report.accuracy.regex_baseline;
  const latency = report.performance.openai_privacy_filter_latency;
  console.log('OpenAI Privacy Filter Transformers.js Mac benchmark');
  console.log(`runtime=${runtime.device} dtype=${runtime.dtype} load_ms=${runtime.load_time_ms}`);
  console.log(`privacy_filter precision=${modelAccuracy.precision} recall=${modelAccuracy.recall} f1=${modelAccuracy.f1} misses=${modelAccuracy.miss_total} false_positives=${modelAccuracy.false_positive_total}`);
  console.log(`regex_baseline precision=${regexAccuracy.precision} recall=${regexAccuracy.recall} f1=${regexAccuracy.f1} misses=${regexAccuracy.miss_total} false_positives=${regexAccuracy.false_positive_total}`);
  console.log(`performance mean_ms=${latency.mean_ms} median_ms=${latency.median_ms} p95_ms=${latency.p95_ms} max_ms=${latency.max_ms} rss_end_mb=${report.performance.memory_end.rss_mb} cpu_mean_percent=${report.performance.process_cpu_percent_mean}`);
  for (const item of modelCases) {
    const evaluation = item.evaluation;
    console.log(`- ${item.id}: hits=${evaluation.hit_count}/${evaluation.expected_count} misses=${evaluation.miss_count} mismatches=${evaluation.label_mismatch_count} false_positives=${evaluation.false_positive_count} latency_mean_ms=${item.latency.mean_ms}`);
  }
  if (args.output) console.log(`json_report=${args.output}`);
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exit(1);
});
