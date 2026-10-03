// Disposable CLI host lifecycle shared by connected Project browser specs.
import { chmodSync, copyFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';

export function copyRemoteHostSession(sourceStateDir: string, fixtureStateDir: string): string {
  mkdirSync(fixtureStateDir, { recursive: true, mode: 0o700 });
  chmodSync(fixtureStateDir, 0o700);
  const sessionPath = join(fixtureStateDir, 'session.json');
  copyFileSync(join(sourceStateDir, 'session.json'), sessionPath);
  chmodSync(sessionPath, 0o600);
  return sessionPath;
}

export interface RemoteFixtureEvent {
  event: string;
  project_id: string;
  project_name: string;
  path_privacy_verified?: boolean;
  [key: string]: string | boolean | undefined;
}

const MAX_FIXTURE_DIAGNOSTIC_CHARS = 8_000;

function appendFixtureDiagnostic(current: string, chunk: unknown): string {
  const next = `${current}${String(chunk)}`;
  return next.length > MAX_FIXTURE_DIAGNOSTIC_CHARS
    ? next.slice(-MAX_FIXTURE_DIAGNOSTIC_CHARS)
    : next;
}

function sanitizeFixtureDiagnostic(value: string): string {
  return value
    // eslint-disable-next-line no-control-regex -- Strip terminal escape sequences from fixture logs.
    .replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, '')
    .replace(/\bBearer\s+\S+/gi, 'Bearer [REDACTED]')
    .replace(/\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/g, '[REDACTED_JWT]')
    .replace(/((?:authorization|cookie|password|secret|token|otp(?:_key)?|encrypted_[a-z_]*key)\s*["']?\s*[:=]\s*["']?)[^\s"',}]+/gi, '$1[REDACTED]')
    .replace(/\b[A-Za-z0-9+/_=-]{80,}\b/g, '[REDACTED_LONG_VALUE]')
    // eslint-disable-next-line no-control-regex -- Remove non-printing bytes from diagnostic output.
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, '')
    .trim();
}

function fixtureDiagnostic(stdout: string, stderr: string): string {
  return [
    `stdout:\n${sanitizeFixtureDiagnostic(stdout) || '(empty)'}`,
    `stderr:\n${sanitizeFixtureDiagnostic(stderr) || '(empty)'}`,
  ].join('\n');
}

export function waitForFixtureEvent(processHandle, eventName: string, timeoutMs = 60000): Promise<RemoteFixtureEvent> {
  return new Promise((resolvePromise, reject) => {
    let output = '';
    let errorOutput = '';
    let settled = false;
    const cleanup = () => {
      clearTimeout(timeout);
      processHandle.stdout.off('data', onData);
      processHandle.stderr?.off('data', onErrorData);
      processHandle.off('close', onClose);
    };
    const fail = (message: string) => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(new Error(`${message}\n${fixtureDiagnostic(output, errorOutput)}`));
    };
    const onData = (chunk) => {
      output = appendFixtureDiagnostic(output, chunk);
      for (const line of output.split('\n')) {
        try {
          const payload = JSON.parse(line);
          if (payload.event !== eventName) continue;
          if (settled) return;
          settled = true;
          cleanup();
          resolvePromise(payload);
          return;
        } catch {
          // Ignore CLI status text and incomplete JSON lines.
        }
      }
    };
    const onErrorData = (chunk) => {
      errorOutput = appendFixtureDiagnostic(errorOutput, chunk);
    };
    const onClose = (code, signal) => {
      fail(`Remote fixture exited before ${eventName} (code=${code ?? 'null'}, signal=${signal ?? 'none'})`);
    };
    const timeout = setTimeout(() => fail(`Timed out waiting for ${eventName}`), timeoutMs);
    processHandle.stdout.on('data', onData);
    processHandle.stderr?.on('data', onErrorData);
    processHandle.once('close', onClose);
  });
}

export async function stopFixtureProcess(processHandle): Promise<void> {
  if (processHandle.exitCode !== null || processHandle.signalCode !== null) return;
  const waitForClose = (timeoutMs: number): Promise<boolean> => new Promise((resolvePromise) => {
    const timeout = setTimeout(() => {
      processHandle.off('close', onClose);
      resolvePromise(false);
    }, timeoutMs);
    const onClose = () => {
      clearTimeout(timeout);
      resolvePromise(true);
    };
    processHandle.once('close', onClose);
  });
  const gracefulClose = waitForClose(10_000);
  processHandle.kill('SIGTERM');
  if (await gracefulClose) return;
  const forcedClose = waitForClose(5_000);
  processHandle.kill('SIGKILL');
  if (!await forcedClose) throw new Error('Remote fixture did not close after SIGKILL');
}
