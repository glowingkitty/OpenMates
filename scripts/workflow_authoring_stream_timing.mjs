#!/usr/bin/env node
// contract-test-file: infrastructure
// One gated rollout request. Never write credentials, instructions, or SSE payloads to logs.

import { randomUUID } from 'node:crypto';
import { performance } from 'node:perf_hooks';
import { OpenMatesClient, deriveAppUrl } from '../frontend/packages/openmates-cli/dist/index.js';

async function readInput() {
  let source = '';
  for await (const chunk of process.stdin) {
    source += chunk.toString('utf8');
    if (source.length > 32_000) throw new Error('InputTooLarge');
  }
  const input = JSON.parse(source);
  if (typeof input.text !== 'string' || !input.text.trim()
      || typeof input.api_url !== 'string' || input.api_url !== 'https://api.dev.openmates.org') {
    throw new Error('InvalidInput');
  }
  return input;
}

async function run() {
  const input = await readInput();
  const client = OpenMatesClient.load({ apiUrl: input.api_url });
  // Uses the isolated CLI profile and checks access before the paid request.
  await client.listWorkflows();
  const session = client.getSession();
  const cookie = Object.entries(session.cookies).map(([key, value]) => `${key}=${value}`).join('; ');
  if (!cookie) throw new Error('NoSessionCookie');
  // The SDK transport keeps rotated refresh cookies in the isolated profile.
  // Assert that hook exists before opening a paid stream.
  if (typeof client.http?.captureCookies !== 'function') throw new Error('SdkCookieCaptureUnavailable');

  const started = performance.now();
  const timing = {
    first_started_seconds: null,
    first_header_seconds: null,
    first_validated_action_seconds: null,
    first_preview_seconds: null,
    final_event_seconds: null,
    validated_preview_count: 0,
  };
  let finalSession = null;
  let startedSessionId = null;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 180_000);
  try {
    const response = await fetch(`${input.api_url}/v1/workflows/input/stream`, {
      method: 'POST',
      headers: {
        Accept: 'text/event-stream',
        'Content-Type': 'application/json',
        Cookie: cookie,
        Origin: deriveAppUrl(input.api_url),
        'X-OpenMates-SDK': 'cli',
      },
      body: JSON.stringify({ text: input.text, input_type: 'text', optimistic_save: true,
                             timezone: input.timezone || 'UTC', idempotency_key: randomUUID() }),
      signal: controller.signal,
    });
    client.http.captureCookies(response);
    client.getSession();
    if (!response.ok || !response.body) throw new Error(`StreamHttp${response.status}`);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let dataLines = [];
    const dispatch = () => {
      if (!dataLines.length) return;
      const event = JSON.parse(dataLines.join('\n'));
      dataLines = [];
      const elapsed = Math.round((performance.now() - started) / 10) / 100;
      if (event.type === 'started') {
        startedSessionId = event.session_id;
        timing.first_started_seconds ??= elapsed;
      } else if (event.type === 'preview' && event.validated === true) {
        timing.validated_preview_count += 1;
        timing.first_preview_seconds ??= elapsed;
        if (event.accepted_node_count === 0) timing.first_header_seconds ??= elapsed;
        else timing.first_validated_action_seconds ??= elapsed;
      } else if (event.type === 'session') {
        finalSession = event.session;
        timing.final_event_seconds = elapsed;
      } else if (event.type === 'error') {
        throw new Error('StreamErrorEvent');
      }
    };
    const consume = (flush = false) => {
      while (true) {
        const newline = buffer.indexOf('\n');
        if (newline < 0) break;
        const line = buffer.slice(0, newline).replace(/\r$/, '');
        buffer = buffer.slice(newline + 1);
        if (!line) dispatch();
        else if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart());
      }
      if (flush) {
        if (buffer.startsWith('data:')) dataLines.push(buffer.slice(5).trimStart());
        dispatch();
      }
    };
    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        consume();
      }
      buffer += decoder.decode();
      consume(true);
    } finally {
      reader.releaseLock();
    }
  } finally {
    clearTimeout(timeout);
  }

  if (!finalSession && startedSessionId) {
    // A dropped SSE connection does not cancel server authoring. Recover by ID.
    const deadline = performance.now() + 120_000;
    while (performance.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 2_000));
      const current = await client.getWorkflowInputSession(startedSessionId);
      if (current.status !== 'running') {
        finalSession = current;
        break;
      }
    }
  }
  if (!finalSession) throw new Error('NoFinalSession');
  process.stdout.write(JSON.stringify({ session: finalSession, stream_timing: timing }));
}

run().catch((error) => {
  process.stderr.write(`Workflow stream timing failed: ${error?.name || 'Error'}\n`);
  process.exitCode = 1;
});
