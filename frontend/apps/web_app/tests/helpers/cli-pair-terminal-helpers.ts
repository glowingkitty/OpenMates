/* eslint-disable @typescript-eslint/no-require-imports */
/** Pair with the actual CLI in a graphical PTY, keeping terminal input open until it exits. */
export {};
import type {TestInfo} from '@playwright/test';
const {spawn, execFileSync} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const ROOT = path.resolve(__dirname, '../../../../..');
let recorderReady = false;

function recordPairLogin(cli: string, env: Record<string, string | undefined>, apiUrl: string, testInfo: TestInfo) {
  if (!recorderReady) {
    execFileSync('sudo', ['apt-get', 'install', '-y', 'zutty', 'fonts-dejavu-core', 'x11-xserver-utils', 'xdotool'],
      {cwd: ROOT, timeout: 120_000, stdio: 'pipe'});
    recorderReady = true;
  }
  const outputDir = testInfo.outputPath('cli-pair-terminal');
  const display = ':' + (140 + Number(process.env.PLAYWRIGHT_WORKER_SLOT || '1'));
  const terminalEnv = {...env, DISPLAY: display, TERM: 'xterm-256color', LIBGL_ALWAYS_SOFTWARE: 'true', GALLIUM_DRIVER: 'llvmpipe'};
  const child = spawn('python3', [
    path.join(ROOT, 'scripts/cli_video_capture.py'), '--output-dir', outputDir,
    '--target-environment', apiUrl, '--classification', 'cli_pair_login',
    '--display-number', display.slice(1), '--timeout-seconds', '90', '--no-response-media',
    '--', 'node', cli, 'login'
  ], {cwd: ROOT, env: terminalEnv, stdio: ['ignore', 'pipe', 'pipe']});
  let closed = false, stdout = '', stderr = '';
  child.stdout.on('data', (chunk: Buffer) => { stdout += chunk.toString(); });
  child.stderr.on('data', (chunk: Buffer) => { stderr += chunk.toString(); });
  const exit = new Promise<number | null>((resolve, reject) => {
    child.once('error', reject);
    child.once('close', (code: number | null) => { closed = true; resolve(code); });
  });
  const transcriptPath = path.join(outputDir, 'transcript.txt');
  const output = () => fs.existsSync(transcriptPath) ? fs.readFileSync(transcriptPath, 'utf8') : '';
  async function waitForOutput(pattern: RegExp): Promise<RegExpMatchArray> {
    const deadline = Date.now() + 20_000;
    while (Date.now() < deadline) {
      const match = output().match(pattern);
      if (match) return match;
      if (closed) break;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    throw new Error('Pair terminal did not reach ' + pattern + ': ' + output() + stderr);
  }
  function windowId(): string {
    return execFileSync('xdotool', ['search', '--onlyvisible', '--name', '^OpenMates CLI$'],
      {env: terminalEnv, encoding: 'utf8', timeout: 5_000}).trim().split('\n').at(-1);
  }
  return {
    async waitForToken(): Promise<string> {
      return (await waitForOutput(/pair=([A-Z0-9]{6})/))[1];
    },
    async sendPin(pin: string): Promise<void> {
      // Wait until readline has hidden input; never put the PIN in argv or artifacts.
      await waitForOutput(/Enter 6-char pairing PIN:/);
      execFileSync('xdotool', ['windowfocus', '--sync', windowId()], {env: terminalEnv, timeout: 5_000});
      execFileSync('xdotool', ['type', '--clearmodifiers', '--delay', '15', '--file', '-'],
        {env: terminalEnv, input: pin, timeout: 5_000});
      execFileSync('xdotool', ['key', '--clearmodifiers', 'Return'], {env: terminalEnv, timeout: 5_000});
    },
    async waitForExit(): Promise<{code: number | null; output: string}> {
      // No EOF, Ctrl+C, or PTY close: login must release its own terminal handle.
      let timer: ReturnType<typeof setTimeout>;
      try {
        const code = await Promise.race([exit, new Promise<never>((_, reject) => {
          timer = setTimeout(() => reject(new Error('CLI login did not exit naturally: ' + output())), 30_000);
        })]);
        const manifestPath = path.join(outputDir, 'manifest.json');
        const manifest = fs.existsSync(manifestPath) ? JSON.parse(fs.readFileSync(manifestPath, 'utf8')) : null;
        if (!manifest || manifest.capture_kind !== 'real_terminal_screen' || manifest.reconstructed !== false) {
          throw new Error('Missing real terminal capture: ' + stdout + stderr);
        }
        // Zutty reports its own success even when its child fails. util-linux
        // script records the actual CLI status only after the child exits.
        const transcript = output();
        const cliExit = transcript.match(/^Script done on .*\[COMMAND_EXIT_CODE="(\d+)"\]\s*$/m);
        if (!cliExit) throw new Error('CLI exited without a recorded command status: ' + code + stderr);
        return {code: Number(cliExit[1]), output: transcript};
      } finally {
        clearTimeout(timer!);
      }
    },
    async dispose(): Promise<void> {
      if (!closed) {
        // Failure cleanup only; closing the window lets the recorder finalize its video.
        try { execFileSync('xdotool', ['windowclose', windowId()], {env: terminalEnv, timeout: 5_000}); } catch { /* recorder has its own deadline */ }
      }
      await exit.catch(() => undefined);
      for (const [name, file, contentType] of [
        ['openmates-cli-real-terminal-video', 'raw-terminal.mp4', 'video/mp4'],
        ['openmates-cli-real-terminal-manifest', 'manifest.json', 'application/json'],
        ['openmates-cli-real-terminal-transcript', 'transcript.txt', 'text/plain'],
        ['openmates-cli-real-terminal-events', 'events.jsonl', 'application/jsonl']
      ]) {
        const artifact = path.join(outputDir, file);
        if (fs.existsSync(artifact)) await testInfo.attach(name, {path: artifact, contentType});
      }
    }
  };
}
module.exports = {recordPairLogin};
