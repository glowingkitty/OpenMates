# contract-test-file: tooling
"""Trusted measurement code; browser and generated app run exclusively in E2B."""
from __future__ import annotations

import hashlib
import json
import shlex
import threading
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit


BROWSER_CHECK = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { chromium } = require('playwright');
const config = JSON.parse(fs.readFileSync('/tmp/openmates-interaction-config.json', 'utf8'));
const mark = phase => console.log('OPENMATES_INTERACTION:' + JSON.stringify({phase}));
(async () => {
  const browser = await chromium.launch({headless:true, args:[
    '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
    '--no-zygote', '--single-process', '--js-flags=--jitless']});
  let context;
  let video;
  let passed = false;
  const errors = [];
  try {
    context = await browser.newContext({viewport:{width:1280,height:800},
      recordVideo:{dir:'/tmp/openmates-startup-proof',size:{width:1280,height:800}}});
    const page = await context.newPage();
    page.setDefaultTimeout(15000);
    video = page.video();
    page.on('pageerror', () => errors.push('pageerror'));
    // Prevent a generated page from redirecting the measurement to another host.
    await page.route('**/*', async route => {
      if (route.request().isNavigationRequest() &&
          new URL(route.request().url()).origin !== new URL(config.url).origin) {
        return route.abort();
      }
      return route.continue();
    });
    mark('browser_navigation_started');
    const response = await page.goto(config.url, {waitUntil:'domcontentloaded',timeout:20000});
    assert.equal(response.status(), 200);
    assert.equal(new URL(page.url()).origin, new URL(config.url).origin);
    if (config.scenario === 'todo') {
      await page.getByRole('heading',{name:'My Todos',exact:true}).waitFor({state:'visible'});
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      mark('app_rendered');
      await page.getByRole('textbox',{name:'New todo',exact:true}).fill('Startup interaction proof');
      await page.getByRole('button',{name:'Add',exact:true}).click();
      await page.getByText('Startup interaction proof',{exact:true}).waitFor({state:'visible'});
      assert.equal(await page.getByRole('textbox',{name:'New todo',exact:true}).inputValue(), '');
    } else {
      await page.getByRole('heading',{name:'Recipe Manager',exact:true}).waitFor({state:'visible'});
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      mark('app_rendered');
      await page.getByTestId('recipe-filter').fill('berry');
      await page.getByTestId('recipe-option').click();
      await page.getByTestId('cook-button').click();
      await page.getByTestId('cook-count').filter({hasText:'Cooked 1 times'}).waitFor({state:'visible'});
      assert.equal((await page.getByTestId('recipe-count').textContent()).trim(), '1 recipes');
    }
    assert.deepEqual(errors, []);
    mark('interaction_acknowledged');
    passed = true;
    await page.waitForTimeout(500);
  } finally {
    if (context) await context.close();
    const videoPath = video ? await video.path() : null;
    console.log('OPENMATES_INTERACTION_RESULT:' + JSON.stringify({
      interactive:passed, page_errors:errors, video_path:videoPath}));
    await browser.close();
  }
})().catch(() => { console.error('Trusted interaction assertion failed'); process.exitCode=1; });
"""


# Browser/context/page creation occurs before any generated-app URL is supplied.
# The only post-HTTP-ready control operation is one trusted JSON file upload.
PREPARED_BROWSER_CHECK = BROWSER_CHECK.replace(
    "const config = JSON.parse(fs.readFileSync('/tmp/openmates-interaction-config.json', 'utf8'));",
    "let config;",
).replace(
    "    // Prevent a generated page",
    "    mark('browser_ready');\n"
    "    const deadline = Date.now() + 120000;\n"
    "    while (!fs.existsSync('/tmp/openmates-interaction-config.json')) {\n"
    "      if (Date.now() > deadline) throw new Error('URL delivery timeout');\n"
    "      await new Promise(resolve => setTimeout(resolve, 10));\n"
    "    }\n"
    "    config = JSON.parse(fs.readFileSync('/tmp/openmates-interaction-config.json', 'utf8'));\n"
    "    // Prevent a generated page",
)


def validated_public_url(url: str, expected_host: str) -> str:
    """Require the exact SDK-issued HTTPS host, with no credentials or redirect."""
    expected = urlsplit(expected_host if expected_host.startswith('https://') else 'https://' + expected_host)
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.netloc != expected.netloc or
            not parsed.hostname or parsed.username or parsed.password or
            parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        raise ValueError('Interaction probe requires the exact sandbox public HTTPS origin')
    return url.rstrip('/') + '/'


def sandbox_resources(sandbox: Any) -> dict[str, Any]:
    """Read resource allocation after measurement without exposing host metadata."""
    try:
        info = sandbox.get_info()
        return {name: value for name in ('cpu_count', 'memory_mb')
                if isinstance(value := getattr(info, name, None), (int, float))}
    except Exception as exc:
        return {'lookup_error_type': type(exc).__name__}


class RemoteInteractionProbe:
    """Run the probe concurrently with PNG capture, observing remote milestones."""

    def __init__(self, *, sandbox: Any, url: str | None, capture_directory: str,
                 scenario: str, output_dir: Path, event: Callable[[str], float],
                 prepared: bool = False) -> None:
        if scenario not in ('todo', 'recipe'):
            raise ValueError('Unknown interaction scenario')
        self.sandbox = sandbox
        if not prepared and url is None:
            raise ValueError('Non-prepared probe requires a URL')
        self.url = validated_public_url(url, sandbox.get_host(5173)) if url else None
        self.prepared = prepared
        self.browser_ready = threading.Event()
        self.script = PREPARED_BROWSER_CHECK if prepared else BROWSER_CHECK
        self.capture_directory = capture_directory
        self.scenario = scenario
        self.output_dir = output_dir
        self.event = event
        self.result: dict[str, Any] = {
            'scope': 'E2B browser -> public sandbox preview HTTPS; excludes OpenMates UI/proxy',
            'browser_location': 'E2B', 'scenario': scenario,
            'probe_sha256': hashlib.sha256(self.script.encode()).hexdigest(),
            'prepared_browser': prepared,
        }
        self._stdout_buffer = ''
        self.thread = threading.Thread(target=self._run, name='e2b-interaction-probe', daemon=True)

    def start(self) -> None:
        self.thread.start()

    def wait_for_browser_ready(self, timeout: float = 45) -> None:
        if not self.browser_ready.wait(timeout=timeout):
            raise TimeoutError('Prepared remote browser did not become ready')

    def send_target(self, url: str, expected_host: str) -> None:
        """The single measured control upload, validated against the app VM host."""
        if not self.prepared or not self.browser_ready.is_set():
            raise RuntimeError('Browser must be prepared before sending target')
        self.url = validated_public_url(url, expected_host)
        self._write_config()

    def _write_config(self) -> None:
        self.sandbox.files.write('/tmp/openmates-interaction-config.json', json.dumps({
            'url': self.url, 'scenario': self.scenario}))

    def _stdout(self, data: Any) -> None:
        text = data if isinstance(data, str) else getattr(data, 'line', '')
        self._stdout_buffer += text
        marker = 'OPENMATES_INTERACTION:'
        while marker in self._stdout_buffer:
            payload = self._stdout_buffer.split(marker, 1)[1]
            try:
                data, end = json.JSONDecoder().raw_decode(payload)
            except json.JSONDecodeError:
                return  # SDK transport may split a JSON marker across callbacks.
            self._stdout_buffer = payload[end:]
            phase = data.get('phase')
            if phase == 'browser_ready':
                self.event(phase)
                self.browser_ready.set()
            elif phase in ('browser_navigation_started', 'app_rendered', 'interaction_acknowledged'):
                self.result[phase + '_seconds'] = self.event(phase)

    def _run(self) -> None:
        try:
            self.event('interactive_probe_started')
            if not self.prepared:
                self._write_config()
            self.sandbox.files.write('/tmp/openmates-interaction-probe.cjs', self.script)
            command = ('cd ' + shlex.quote(self.capture_directory) +
                       ' && PLAYWRIGHT_BROWSERS_PATH=' + shlex.quote(self.capture_directory + '/browsers') +
                       ' NODE_PATH="$PWD/node_modules" node /tmp/openmates-interaction-probe.cjs')
            check = self.sandbox.commands.run(command, timeout=180 if self.prepared else 60, on_stdout=self._stdout)
            # Do not retain arbitrary generated-app output or exception strings.
            results = [json.loads(line.split(':', 1)[1]) for line in check.stdout.splitlines()
                       if line.startswith('OPENMATES_INTERACTION_RESULT:')]
            result = results[-1] if results else {}
            video_path = result.get('video_path')
            if (isinstance(video_path, str) and video_path.startswith('/tmp/openmates-startup-proof/')
                    and video_path.endswith('.webm') and '..' not in video_path):
                data = bytes(self.sandbox.files.read(video_path, format='bytes'))
                (self.output_dir / 'interactive.webm').write_bytes(data)
                self.result['recording_sha256'] = hashlib.sha256(data).hexdigest()
                self.result['recording_bytes'] = len(data)
                self.result['recording_path'] = str(self.output_dir / 'interactive.webm')
            self.result['interactive'] = bool(check.exit_code == 0 and result.get('interactive')
                and result.get('page_errors') == [] and 'interaction_acknowledged_seconds' in self.result)
            self.result['status'] = 'pass' if self.result['interactive'] else 'fail'
        except Exception as exc:
            self.result.update(status='fail', error_type=type(exc).__name__)
        finally:
            self.event('interactive_probe_finished')

    def finish(self) -> dict[str, Any]:
        self.thread.join(timeout=75)
        if self.thread.is_alive():
            self.result.update(status='fail', error_type='InteractionProbeTimeout')
        return dict(self.result)
