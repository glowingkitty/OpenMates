"""Finite existing-runner memory readiness probe, never migration acceptance."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

from scripts.ci_client_container_launch import Config, Launch, CliJsonDriver, need

SPEC = 'cli-memory-readiness.spec.ts'
MODES = ('leaf', 'threads', 'child', 'node-threads')


def verify_fixture(mode, value):
    need(type(value) is dict and value.get('fixture') == mode, 'fixed_fixture_output')
    need(value.get('unit') == 'KiB' and value.get('acceptanceEligible') is False, 'fixture_units_and_scope')
    root = value.get('rootThreadGroupPeakRssKiB')
    need(type(root) is int and root > 0, 'kernel_fixture_rss_required')
    if mode == 'child':
        need(value.get('wholeFixturePeakRssKiB') is None and value.get('rssScope') == 'root-only-child-aggregate-unavailable', 'child_total_must_remain_unavailable')
    else:
        need(value.get('wholeFixturePeakRssKiB') == root and value.get('rssScope') == 'one-known-thread-group', 'known_single_thread_group_required')


def run(root):
    from ci_environment import require_runner
    require_runner()  # Before reading context, probing tools, or any Docker operation.
    need(os.environ.get('CI_TEST_MODE') == 'e2e' and json.loads(os.environ.get('CI_SPECS_JSON', '[]')) == [SPEC], 'exact_e2e_selector_required')
    from ci_runtime_images import runtime_key, verify_loaded_image
    from ci_run_tests import pinned_node, verify_pinned_node_runtime
    root = Path(root).resolve()
    evidence = json.loads((root / 'test-results/ci-environment.json').read_text())
    source = evidence['source_commit']
    need(re.fullmatch('[a-f0-9]{40}', source) and source == os.environ.get('BUILD_COMMIT_SHA') and evidence.get('run_id') == os.environ.get('GITHUB_RUN_ID'), 'managed_source_run_required')
    actual_source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True, timeout=10).strip()
    need(actual_source == source, 'actual_candidate_source_required')
    need(evidence.get('shared_dev_dns') == 'rejected' and evidence.get('shared_dev_https') == 'rejected', 'normal_isolation_verification_required')
    api = evidence['services']['api']
    gateway = evidence['services']['runner-gateway']
    need(api['running'] is True and gateway['running'] is True, 'managed_services_required')
    image = api['image']
    key = runtime_key(root, 'api')
    verify_loaded_image(root, 'api', image, key)
    verify_pinned_node_runtime()
    node = Path(pinned_node()).resolve(strict=True)
    supervisor = root / 'scripts/ci_client_memory_supervisor.py'
    fixture = root / 'scripts/ci_client_memory_fixture.py'
    node_fixture = root / 'scripts/ci_client_memory_fixture.mjs'
    need(os.access(fixture, os.X_OK), 'executable_fixed_fixture_required')
    private = root / 'test-results/ci-private/client-memory'
    private.mkdir(mode=0o700, parents=True, exist_ok=False)
    report = {'schemaVersion': 1, 'kind': 'harmless-memory-readiness', 'sourceCommit': source,
        'runId': evidence['run_id'], 'acceptanceEligible': False, 'currentMigrationAcceptance': False,
        'status': 'failed', 'scope': 'harmless-fixtures-only-no-product-baseline', 'attempts': []}
    destination = root / 'test-results/ci-client-memory-readiness.json'
    deadline = time.monotonic() + 145
    try:
        for index, mode in enumerate(MODES, 1):
            state = private / mode
            state.mkdir(mode=0o700)
            command = (str(node), str(node_fixture)) if mode == 'node-threads' else (str(fixture), mode)
            readonly = (fixture, node_fixture, node)
            cfg = Config(source_root=root, private_root=private, source=source, image=image,
                runtime_key=key, gateway=gateway['container'], owner='memory-readiness-' + evidence['run_id'],
                arm='rust', pair=index, argv=command, env={'HOME': str(state), 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8'},
                cwd=state, readonly_paths=readonly, state_root=state, conditions=(('image', image),),
                deadline=deadline, work_deadline=deadline - 12, memory_limit=256 * 1024**2,
                pids_limit=32, cpus='1', uid=os.getuid(), gid=os.getgid(), supervisor=supervisor,
                supervisor_sha256=hashlib.sha256(supervisor.read_bytes()).hexdigest())
            # Legacy arm is merely the launcher's finite ownership slot; neither
            # fixture is a Rust application or a TypeScript comparison cohort.
            attempt = {'fixture': mode, 'status': 'failed', 'acceptanceEligible': False}
            report['attempts'].append(attempt)
            launch = Launch(cfg)
            driver = CliJsonDriver(lambda unused, value: verify_fixture(mode, value))
            try:
                proxy = launch.start(*driver.open(cfg))
                driver.drive(cfg, proxy)
                attempt['fixtureRss'] = driver.values[('rust', index)]
            finally:
                if launch.bridge is not None and not launch.cleanup_started:
                    attempt['collection'] = launch.finish()
                elif not launch.cleanup_started:
                    launch.cleanup()
                attempt['cleanupVerified'] = launch.last_cleanup_result
                if launch.bridge is not None:
                    attempt['heldMemory'] = launch.bridge.memory
                output = driver.outputs.get(('rust', index))
                if output is not None:
                    attempt['output'] = {'complete': output['complete'], 'exitCode': output['exitCode'],
                        'stdoutBytes': len(output['stdout']), 'stderrBytes': len(output['stderr'])}
            collected = attempt['collection']
            need(collected['cleanupVerified'] is True and collected['memory']['status'] == 'observed' and collected['containerExitCode'] == 0, 'actual_collection_and_cleanup_required')
            attempt['status'] = 'observed'
            destination.write_text(json.dumps(report, indent=2))
        report['status'] = 'observed'
    finally:
        destination.write_text(json.dumps(report, indent=2))
    return report


if __name__ == '__main__':
    run(Path(__file__).resolve().parents[1])
