/**
 * Real CLI cross-client producer and consumer scaffold.
 * The control-plane directory contains only opaque IDs and marker hashes.
 * CLI authentication must be preconfigured by the test runner; this file never
 * reads, writes, or logs credentials and targets the real dev API path.
 */

import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';

const PACKAGE_ROOT = fileURLToPath(new URL('..', import.meta.url));
const RUN_ID = process.env.APPLE_CROSS_CLIENT_RUN_ID || '';
const ARTIFACT_DIR = process.env.APPLE_CROSS_CLIENT_ARTIFACT_DIR || '';
const API_URL = process.env.OPENMATES_API_URL || 'https://api.dev.openmates.org';

function requireControlPlane(): { runId: string; artifactDir: string } {
  if (!RUN_ID || !ARTIFACT_DIR) throw new Error('APPLE_CROSS_CLIENT_RUN_ID and APPLE_CROSS_CLIENT_ARTIFACT_DIR are required');
  return { runId: RUN_ID, artifactDir: path.resolve(ARTIFACT_DIR) };
}

function manifestPath(artifactDir: string, name: string): string {
  return path.join(artifactDir, `apple-cross-client-${RUN_ID}-${name}.json`);
}

function runCli(args: string[]): Record<string, unknown> {
  const output = execFileSync('node', ['dist/cli.js', ...args], {
    cwd: PACKAGE_ROOT,
    encoding: 'utf8',
    env: { ...process.env, OPENMATES_API_URL: API_URL, TERM: 'dumb' }
  });
  return JSON.parse(output) as Record<string, unknown>;
}

// contract-test: direct surface=cli assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity
test('publishes a real CLI producer manifest for Apple consumption', () => {
  const { runId, artifactDir } = requireControlPlane();
  const marker = `Apple parity CLI marker ${runId}`;
  const result = runCli(['chats', 'new', marker, '--json']);
  const chatId = result.chat_id || result.chatId;
  assert.equal(typeof chatId, 'string', 'real CLI chat creation must return an opaque chat ID');
  fs.mkdirSync(artifactDir, { recursive: true });
  fs.writeFileSync(manifestPath(artifactDir, 'cli-producer'), `${JSON.stringify({
    schema_version: 1,
    run_id: runId,
    producer: 'cli',
    chat_id: chatId,
    marker_hash: crypto.createHash('sha256').update(marker).digest('hex'),
    created_at: new Date().toISOString()
  }, null, 2)}\n`);
});

// contract-test: direct surface=cli assertions=chats.message.identity-idempotent,chats.surface.semantic-parity
test('reads the Apple producer chat exactly once from the real dev API', () => {
  const { runId, artifactDir } = requireControlPlane();
  const apple = JSON.parse(fs.readFileSync(manifestPath(artifactDir, 'apple-producer'), 'utf8')) as Record<string, unknown>;
  assert.equal(apple.run_id, runId);
  assert.equal(typeof apple.chat_id, 'string');
  const result = runCli(['chats', 'show', String(apple.chat_id), '--json']);
  const serialized = JSON.stringify(result);
  assert.ok(serialized.includes(String(apple.marker)), 'CLI must decrypt the synthetic Apple marker');
  fs.writeFileSync(manifestPath(artifactDir, 'cli-consumer'), `${JSON.stringify({
    schema_version: 1,
    run_id: runId,
    consumer: 'cli',
    chat_id: apple.chat_id,
    marker_hash: crypto.createHash('sha256').update(String(apple.marker)).digest('hex'),
    consumed_at: new Date().toISOString()
  }, null, 2)}\n`);
});
