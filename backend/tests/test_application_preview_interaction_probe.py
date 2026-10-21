# contract-test-file: tooling
"""Probe boundary tests; never launch a browser or execute generated code here."""
import importlib.util
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

SPEC = importlib.util.spec_from_file_location(
    'preview_interaction_probe',
    Path(__file__).parents[1] / 'scripts/application_preview_interaction_probe.py',
)
probe_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe_module)


class InteractionProbeTests(unittest.TestCase):
    def test_exact_public_host_only(self):
        validate = probe_module.validated_public_url
        self.assertEqual(validate('https://5173-test.e2b.app', '5173-test.e2b.app'),
                         'https://5173-test.e2b.app/')
        for url in ('http://5173-test.e2b.app', 'https://5173-test.e2b.app.evil.test',
                    'https://secret@5173-test.e2b.app', 'https://5173-test.e2b.app/?token=secret',
                    'https://5173-test.e2b.app/other', 'http://127.0.0.1:5173/'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate(url, '5173-test.e2b.app')

    def test_streamed_ack_precedes_video_collection(self):
        self._run_probe(emit_ack=True)

    def test_success_without_streamed_ack_fails(self):
        self._run_probe(emit_ack=False)

    def test_prepared_browser_waits_for_single_target_upload(self):
        target_sent = threading.Event()
        writes = []
        phases = []

        def write(path, content):
            writes.append(path)
            if path.endswith('config.json'):
                self.assertEqual(json.loads(content)['url'], 'https://5173-app.e2b.app/')
                target_sent.set()

        def run(_command, **kwargs):
            self.assertEqual(kwargs['timeout'], 180)
            kwargs['on_stdout']('OPENMATES_INTERACTION:{"phase":"browser_ready"}')
            self.assertTrue(target_sent.wait(timeout=2))
            for phase in ('browser_navigation_started', 'app_rendered', 'interaction_acknowledged'):
                kwargs['on_stdout']('OPENMATES_INTERACTION:' + json.dumps({'phase': phase}))
            return SimpleNamespace(exit_code=0, stdout='OPENMATES_INTERACTION_RESULT:' + json.dumps({
                'interactive': True, 'page_errors': [], 'video_path': None}))

        sandbox = SimpleNamespace(files=SimpleNamespace(write=write), commands=SimpleNamespace(run=run))
        with tempfile.TemporaryDirectory() as directory:
            probe = probe_module.RemoteInteractionProbe(
                sandbox=sandbox, url=None, capture_directory='/trusted', scenario='todo',
                output_dir=Path(directory), event=lambda phase: phases.append(phase) or len(phases),
                prepared=True)
            with self.assertRaises(RuntimeError):
                probe.send_target('https://5173-app.e2b.app', '5173-app.e2b.app')
            probe.start()
            probe.wait_for_browser_ready(timeout=2)
            self.assertEqual(writes, ['/tmp/openmates-interaction-probe.cjs'])
            probe.send_target('https://5173-app.e2b.app', '5173-app.e2b.app')
            result = probe.finish()
            self.assertTrue(result['interactive'])
            self.assertTrue(result['prepared_browser'])
            self.assertEqual(writes.count('/tmp/openmates-interaction-config.json'), 1)
            self.assertLess(phases.index('browser_ready'), phases.index('browser_navigation_started'))

    def _run_probe(self, *, emit_ack):
        phases = []
        files = Mock()
        files.read.return_value = b'recording'
        def run(command, **kwargs):
            self.assertIn('node /tmp/openmates-interaction-probe.cjs', command)
            self.assertNotIn('https://', command)
            self.assertEqual(kwargs['timeout'], 60)
            kwargs['on_stdout']('OPENMATES_INTERACTION:{"phase":"app_rendered"}\n')
            if emit_ack:
                kwargs['on_stdout']('OPENMATES_INTERACTION:{"phase":"interaction_')
                kwargs['on_stdout']('acknowledged"}\n')
            result = {'interactive': True, 'page_errors': [],
                      'video_path': '/tmp/openmates-startup-proof/proof.webm'}
            return SimpleNamespace(exit_code=0, stdout='OPENMATES_INTERACTION_RESULT:' + json.dumps(result))
        sandbox = SimpleNamespace(get_host=lambda _port: '5173-test.e2b.app', files=files,
                                  commands=SimpleNamespace(run=run))
        def event(phase):
            phases.append(phase)
            return len(phases) / 10
        with tempfile.TemporaryDirectory() as directory:
            probe = probe_module.RemoteInteractionProbe(
                sandbox=sandbox, url='https://5173-test.e2b.app',
                capture_directory='/trusted', scenario='todo', output_dir=Path(directory), event=event)
            probe.start()
            result = probe.finish()
            self.assertEqual(result['interactive'], emit_ack)
            self.assertEqual(result['status'], 'pass' if emit_ack else 'fail')
            self.assertEqual((Path(directory) / 'interactive.webm').read_bytes(), b'recording')
            if emit_ack:
                self.assertLess(phases.index('interaction_acknowledged'), phases.index('interactive_probe_finished'))
                self.assertEqual(result['interaction_acknowledged_seconds'], 0.3)


if __name__ == '__main__':
    unittest.main()
