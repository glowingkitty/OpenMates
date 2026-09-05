#!/usr/bin/env node
/*
 * Real-dev audio timestamp REST harness.
 *
 * Purpose: upload synthetic speech through the CLI upload service, then exercise
 * the authenticated public audio transcription route without exposing media,
 * transcripts, session data, or transport keys in output.
 * Security: the caller supplies an isolated HOME containing a test-account
 * session; this harness only prints aggregate timing metadata and safe statuses.
 */

import { existsSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { homedir, tmpdir } from "node:os";
import { randomUUID } from "node:crypto";
import { spawnSync } from "node:child_process";
import { uploadFile } from "../../frontend/packages/openmates-cli/src/uploadService.ts";

const DEFAULT_API_URL = "https://api.dev.openmates.org";
const SYNTHETIC_SPEECH = "Hello this is a timestamp test.";
let stage = "setup";
let lastHttpStatus = 0;
let failureReason = "unspecified";

function usage() {
  process.stderr.write(`Usage: node scripts/tests/videos_get_transcript_real_dev.mjs [--api-url <url>] [--include-segment]\n`);
}

function parseArgs(argv) {
  const options = { apiUrl: DEFAULT_API_URL, includeSegment: false };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--api-url") options.apiUrl = argv[++index];
    else if (arg === "--include-segment") options.includeSegment = true;
    else if (arg === "--help" || arg === "-h") options.help = true;
    else throw new Error(`Unknown argument: ${arg}`);
  }
  return options;
}

function createSyntheticSpeechFixture() {
  const path = join(tmpdir(), `openmates-timestamp-${randomUUID()}.wav`);
  const result = spawnSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", `flite=text='${SYNTHETIC_SPEECH}'`, "-af", "apad=pad_dur=1", "-f", "wav", "pipe:1"], {
    encoding: "buffer",
    maxBuffer: 2 * 1024 * 1024,
  });
  if (result.error || result.status !== 0 || !result.stdout?.length) {
    throw new Error("Synthetic speech fixture creation failed. FFmpeg with the flite filter is required.");
  }
  writeFileSync(path, result.stdout, { mode: 0o600 });
  return path;
}

function requestItem(upload, id, options = {}) {
  const s3Key = upload.files?.original?.s3_key ?? Object.values(upload.files ?? {})[0]?.s3_key;
  if (!s3Key) throw new Error("Upload returned no audio object key.");
  return {
    id,
    embed_id: upload.embed_id,
    s3_key: s3Key,
    s3_base_url: upload.s3_base_url,
    aes_key: upload.aes_key,
    aes_nonce: upload.aes_nonce,
    vault_wrapped_aes_key: upload.vault_wrapped_aes_key,
    filename: "timestamp-fixture.wav",
    mime_type: upload.content_type,
    ...options,
  };
}

function cookieHeader(session) {
  const token = session.cookies?.auth_refresh_token;
  if (!token) throw new Error("The isolated test-account session has no upload authentication cookie.");
  return `auth_refresh_token=${token}`;
}

async function postJson(apiUrl, session, body) {
  const response = await fetch(`${apiUrl.replace(/\/$/, "")}/v1/apps/audio/skills/transcribe`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      Cookie: cookieHeader(session),
    },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(10 * 60 * 1000),
  });
  const data = await response.json().catch(() => null);
  lastHttpStatus = response.status;
  if (!response.ok) throw new Error(`Authenticated transcription returned HTTP ${response.status}.`);
  return data;
}

function resultFor(response, id) {
  const groups = response?.data?.results;
  if (!response?.success || !Array.isArray(groups)) throw new Error("Transcription returned an invalid response envelope.");
  const group = groups.find((item) => item?.id === id);
  if (!group) throw new Error("Transcription response omitted a requested result group.");
  return group;
}

function successfulResult(response, id) {
  const group = resultFor(response, id);
  if (group.error || !Array.isArray(group.results) || group.results.length !== 1) {
    const known = ["timestamps_unavailable", "timestamps_empty_silence", "Invalid provider timing duration", "Invalid provider timing", "Mistral", "decrypt", "Missing required fields"];
    const matched = known.findIndex((value) => String(group.error ?? "").includes(value));
    failureReason = matched >= 0 ? `processing_${matched}` : "unsuccessful_result";
    const timingCause = String(group.error ?? "").match(/Invalid provider timing: (field_type|nonfinite|negative_start|empty_or_reversed|duration_bound|out_of_order)/);
    if (timingCause) failureReason = timingCause[1];
    throw new Error("Expected a successful transcription result.");
  }
  return group.results[0];
}

function assertTiming(entries, duration, label) {
  if (!Array.isArray(entries) || entries.length === 0) throw new Error(`${label} timing is missing.`);
  let previousStart = -1;
  for (const entry of entries) {
    if (!Number.isFinite(entry?.start_seconds) || !Number.isFinite(entry?.end_seconds)
      || entry.start_seconds < 0 || entry.end_seconds <= entry.start_seconds
      || entry.end_seconds > duration || entry.start_seconds < previousStart || typeof entry.text !== "string") {
      throw new Error(`${label} timing is invalid.`);
    }
    previousStart = entry.start_seconds;
  }
}

function timingSummary(result) {
  const duration = result?.duration_seconds;
  if (!Number.isFinite(duration) || duration < 0) throw new Error("Transcription duration is invalid.");
  return {
    duration_seconds: duration,
    model_present: typeof result.model === "string" && result.model.length > 0,
    segment_count: Array.isArray(result.segments) ? result.segments.length : 0,
    word_count: Array.isArray(result.words) ? result.words.length : 0,
  };
}

function assertUntimed(result, label) {
  if (Object.hasOwn(result, "segments") || Object.hasOwn(result, "words")) {
    throw new Error(`${label} unexpectedly returned timing fields.`);
  }
  return timingSummary(result);
}

async function assertUnauthorized(apiUrl) {
  const response = await fetch(`${apiUrl.replace(/\/$/, "")}/v1/apps/audio/skills/transcribe`, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({ requests: [] }),
  });
  if (![401, 403].includes(response.status)) throw new Error(`Unauthenticated request returned HTTP ${response.status}.`);
  return { status: response.status };
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.help) return usage();
  if (!process.env.OPENMATES_TRANSCRIPT_TEST_HOME || process.env.OPENMATES_TRANSCRIPT_TEST_HOME !== homedir()) {
    throw new Error("Run the isolated Python gate, not this harness directly.");
  }
  // Read only the ephemeral session written by the existing test-account helper.
  // Upload needs its cookies, not the CLI keychain or refresh/storage machinery.
  const setupSession = JSON.parse(readFileSync(join(homedir(), ".openmates", "session.json"), "utf8"));
  const session = { apiUrl: options.apiUrl, cookies: setupSession.cookies };

  const fixture = createSyntheticSpeechFixture();
  try {
    stage = "upload";
    const upload = await uploadFile(fixture, session);
    stage = "word_request";
    const word = await postJson(options.apiUrl, session, {
      requests: [requestItem(upload, "versioned-word", { transcription_contract_version: 1 })],
    });
    stage = "word_validation";
    const wordResult = successfulResult(word, "versioned-word");
    const wordSummary = timingSummary(wordResult);
    assertTiming(wordResult.segments, wordSummary.duration_seconds, "segment");
    assertTiming(wordResult.words, wordSummary.duration_seconds, "word");

    // Keep both compatibility cases in one authenticated no-timing batch.
    stage = "compatibility_request";
    const none = await postJson(options.apiUrl, session, {
      requests: [
        requestItem(upload, "legacy-omitted"),
        requestItem(upload, "explicit-none", { transcription_contract_version: 1, timestamps: "none" }),
        requestItem(upload, "language-conflict", { transcription_contract_version: 1, language: "en" }),
      ],
    });
    stage = "compatibility_validation";
    const legacySummary = assertUntimed(successfulResult(none, "legacy-omitted"), "legacy omission");
    const explicitNoneSummary = assertUntimed(successfulResult(none, "explicit-none"), "explicit none");
    const conflict = resultFor(none, "language-conflict");
    if (!String(conflict.error ?? "").includes("language cannot be used with word timestamps") || conflict.results?.length) {
      throw new Error("Language/timestamp conflict was not rejected before transcription.");
    }

    const output = {
      surface: "rest",
      scenarios: {
        versioned_default_word: wordSummary,
        legacy_omitted_none: legacySummary,
        explicit_none: explicitNoneSummary,
        language_conflict: { rejected_before_provider: true },
        unauthorized: await assertUnauthorized(options.apiUrl),
      },
    };
    if (options.includeSegment) {
      stage = "segment_request";
      const segment = await postJson(options.apiUrl, session, {
        requests: [requestItem(upload, "explicit-segment", { transcription_contract_version: 1, timestamps: "segment" })],
      });
      stage = "segment_validation";
      const segmentResult = successfulResult(segment, "explicit-segment");
      const summary = timingSummary(segmentResult);
      assertTiming(segmentResult.segments, summary.duration_seconds, "segment");
      if (Object.hasOwn(segmentResult, "words")) throw new Error("Explicit segment unexpectedly returned word timing.");
      output.scenarios.explicit_segment = summary;
    }
    process.stdout.write(`${JSON.stringify(output)}\n`);
  } finally {
    if (existsSync(fixture)) rmSync(fixture, { force: true });
  }
}

main().catch(() => {
  process.stderr.write(`OPENMATES_REST_FAILURE stage=${stage} http=${lastHttpStatus}\n`);
  process.stderr.write(`OPENMATES_REST_REASON ${failureReason}\n`);
  process.exit(1);
});
