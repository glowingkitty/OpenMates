#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Opt-in dev proof of exact templates, using leased disposable account and Project.

No mocked content; graphs remain disabled and run manually. Search Send results
must be acknowledged by the paired CLI. Website baseline and repeat are silent.
"""
from __future__ import annotations
import argparse
import base64
from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import threading
from uuid import uuid4

API_URL = 'https://api.dev.openmates.org'
IDS = ['berlin-ai-events', 'munich-apartments', 'morning-weather', 'weekly-dinner-inspiration', 'website-changes']
CATEGORIES = ['science', 'finance', 'general_knowledge', 'cooking_food', 'software_development']



def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def private_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    os.chmod(path, 0o600)


def configured_slots(repo, environ=None):
    """Mirror the login helper's dotenv precedence without exposing credentials.

    Require slot-specific credentials: a base-account fallback cannot safely be
    leased under several distinct slot identities.
    """
    values = {}
    dotenv = repo / '.env'
    if dotenv.exists():
        for raw_line in dotenv.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1]
            values[key.strip()] = value
    values.update(os.environ if environ is None else environ)
    return [slot for slot in range(1, 21)
            if values.get(f'OPENMATES_TEST_ACCOUNT_{slot}_EMAIL', '').strip()
            and values.get(f'OPENMATES_TEST_ACCOUNT_{slot}_PASSWORD', '').strip()]


def validate_provisioned_state(state, fixture_path, session):
    """Bind a private synthetic signup receipt to this exact session identity."""
    if not state.is_absolute() or not state.is_relative_to(Path('/tmp')) or state == Path('/tmp'):
        raise ValueError('Provisioned state must be an absolute private /tmp path')
    if state.is_symlink() or state.resolve() != state or not state.is_dir():
        raise ValueError('Provisioned state cannot contain symlink routing')
    info = state.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError('Provisioned state must be owner-only 0700')
    for path in (fixture_path, state / 'session.json'):
        if path.is_symlink() or not path.is_file():
            raise ValueError('Fixture evidence/session must be regular private files')
        info = path.stat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError('Fixture evidence/session must be owner-only 0600')
    fixture = json.loads(fixture_path.read_text())
    if fixture.get('target') != API_URL or str(fixture.get('session')) != str(session):
        raise ValueError('Fixture target/session does not match this proof')
    if fixture.get('signup_state') != str(state):
        raise ValueError('Fixture signup state does not match supplied state')
    email = fixture.get('synthetic_email')
    if not isinstance(email, str) or not re.fullmatch(r'e2e-workflow-(?:[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})@(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}', email):
        raise ValueError('Fixture must identify a newly created synthetic workflow account')
    domain = email.rsplit('@', 1)[1]
    if fixture.get('mail_blocked') is not True or fixture.get('signup_domain_verified') is not True or fixture.get('synthetic_domain') != domain:
        raise ValueError('Fixture must prove blocked email and approved signup domain')
    identity = base64.b64encode(hashlib.sha256(email.strip().lower().encode()).digest()).decode()
    stored = json.loads((state / 'session.json').read_text())
    if stored.get('apiUrl') != API_URL or stored.get('hashedEmail') != identity:
        raise ValueError('Signup session identity does not match synthetic fixture receipt')
    return fixture


def load_candidates(path):
    candidates = json.loads(path.read_text())
    if not isinstance(candidates, list) or [item.get('id') for item in candidates] != IDS:
        raise ValueError('Expected exactly five approved IDs in order')
    for item, category in zip(candidates, CATEGORIES):
        if item.get('category') != category or not item.get('icon'):
            raise ValueError('Expected approved category/icon metadata')
        graph = item['graph']
        if graph.get('version') != 2 or graph.get('trigger_node_id') != 'trigger':
            raise ValueError('Expected version-2 schedule graph')
        if item['id'] != 'website-changes' and [node['type'] for node in graph['nodes']] != ['schedule_trigger', 'app_skill_action', 'send_chat_message']:
            raise ValueError('Expected schedule, real app skill, Send graph')
    return candidates


def load_portable_export(path, cli_path):
    """Use the CLI's YAML 1.2 parser, preserving plain clock strings such as 16:00."""
    program = r"""
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
const require = createRequire(process.argv[1]);
const {parseDocument} = require('yaml');
const source = readFileSync(process.argv[2], 'utf8');
const document = parseDocument(source, {uniqueKeys:true, strict:true, version:'1.2'});
if (document.errors.length) {console.error('Export YAML parse failed'); process.exit(1);}
process.stdout.write(JSON.stringify(document.toJS({maxAliasCount:20})));
"""
    result = subprocess.run(['node', '--input-type=module', '-e', program,
                             str(cli_path.resolve()), str(path.resolve())],
                            capture_output=True, text=True, timeout=30, check=False)
    if result.returncode:
        raise ValueError('CLI YAML 1.2 export parser failed')
    document = json.loads(result.stdout)
    if not isinstance(document, dict) or document.get('format') != 'openmates-workflow':
        raise ValueError('Export parser did not return a portable workflow document')
    return document


def restored_export_graph(document, original):
    """Restore portable node IDs so websiteChangesGraph still locates its nodes."""
    graph = deepcopy(document['workflow']['graph'])
    if len(graph['nodes']) != len(original['nodes']) or len(graph['edges']) != len(original['edges']):
        raise ValueError('Export changed graph shape')
    mapping = {node['id']: original['nodes'][i]['id'] for i, node in enumerate(graph['nodes'])}
    pattern = re.compile(r'(\$nodes\.|\{\{\s*steps\.|\$items\.|\{\{\s*items\.)(' + '|'.join(re.escape(key) for key in mapping) + r')(?=[.}\s]|$)')
    def visit(value):
        if isinstance(value, str):
            return pattern.sub(lambda match: match[1] + mapping[match[2]], value)
        if isinstance(value, list):
            return [visit(item) for item in value]
        if isinstance(value, dict):
            return {key: visit(item) for key, item in value.items()}
        return value
    graph = visit(graph)
    graph['trigger_node_id'] = mapping[graph['trigger_node_id']]
    for node in graph['nodes']:
        node['id'] = mapping[node['id']]
    for edge in graph['edges']:
        edge['from'], edge['to'] = mapping[edge['from']], mapping[edge['to']]
    # Strip runtime model defaults absent from the exact authored definition.
    restored = {key: graph[key] for key in original}
    restored['nodes'] = [{key: node[key] for key in source} for node, source in zip(graph['nodes'], original['nodes'])]
    restored['edges'] = [{key: edge[key] for key in source} for edge, source in zip(graph['edges'], original['edges'])]
    if restored != original:
        raise ValueError('Sanitized export differs from tested candidate graph')
    return restored


def validate_run(detail, candidate, occurrence):
    if detail.get('status') != 'completed':
        raise ValueError('Full run did not complete')
    nodes = {node['node_id']: node for node in detail.get('node_runs', [])}
    search = nodes.get('read' if candidate['id'] == 'website-changes' else 'search', {})
    output = search.get('output_summary') or {}
    raw = output.get('raw') or {}
    if search.get('status') != 'completed' or output.get('success') is False or output.get('error') or raw.get('success') is False or raw.get('error'):
        raise ValueError('Real app skill did not complete successfully')
    deliveries = list((detail.get('output_summary', {}).get('deliveries') or {}).values())
    message = nodes.get('message', {})
    summary = {'run_id': detail['id'], 'status': 'completed', 'app_status': search['status']}
    if candidate['id'] == 'website-changes':
        state = output.get('change_status')
        summary['change_status'] = state
        if occurrence == 0 and state != 'initialized':
            raise ValueError('Initial website read did not establish baseline')
        if state in {'initialized', 'unchanged'}:
            if deliveries or message.get('status') == 'completed' or nodes.get('summary', {}).get('status') == 'completed':
                raise ValueError('Baseline/unchanged read unexpectedly sent content')
            summary['silent'] = True
            return summary
        if state != 'changed' or nodes.get('summary', {}).get('status') != 'completed':
            raise ValueError('Actual website change did not complete AI summary')
    else:
        count, results = output.get('result_count'), output.get('results')
        if not isinstance(count, int) or count <= 0 or not isinstance(results, list) or not results or count != len(results):
            raise ValueError('Search/forecast returned no usable results')
        if candidate['id'] == 'morning-weather' and (not isinstance(output.get('forecast_day'), dict) or not output['forecast_day'] or not output['forecast_day'].get('date')):
            raise ValueError('Weather selected forecast day is empty or missing date')
        summary['result_count'] = count
    if message.get('status') != 'completed' or not deliveries or any(item.get('status') != 'acknowledged' or item.get('client_persisted') is not True for item in deliveries):
        raise ValueError('Send lacks acknowledged encrypted chat delivery')
    summary['deliveries'] = [{'delivery_id': d.get('delivery_id'), 'chat_id': d.get('chat_id'), 'status': d.get('status'), 'client_persisted': d.get('client_persisted')} for d in deliveries]
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', required=True)
    parser.add_argument('--repo-root', type=Path, default=Path(__file__).resolve().parents[1])
    for flag in ['candidates', 'state-dir', 'receipt', 'output-dir', 'cli-path']:
        parser.add_argument('--' + flag, type=Path, required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--slot', type=int, choices=range(1, 21))
    parser.add_argument('--use-provisioned-state', action='store_true',
                        help='Use only the private synthetic signup state bound by --fixture-receipt.')
    parser.add_argument('--fixture-receipt', type=Path)
    parser.add_argument('--only', action='append', choices=IDS,
                        help='Verify only this template; repeat to select several. Full input is still validated.')
    parser.add_argument('--allow-paid-dev-inference', action='store_true')
    args = parser.parse_args()
    if any(os.getenv(key) for key in ['CI', 'GITHUB_ACTIONS', 'BUILDKITE', 'GITLAB_CI']):
        parser.error('Real-dev proof cannot run in CI')
    if not args.allow_paid_dev_inference or not re.fullmatch(r'[0-9a-f]{40}', args.revision):
        parser.error('Explicit inference opt-in and deployed full revision required')
    state, out, receipt_path = args.state_dir.absolute(), args.output_dir.resolve(), args.receipt.resolve()
    fixture = None
    if args.use_provisioned_state:
        if args.slot is None or args.fixture_receipt is None:
            parser.error('Provisioned mode requires explicit --slot and --fixture-receipt')
        try:
            fixture = validate_provisioned_state(state, args.fixture_receipt.absolute(), args.session)
        except (ValueError, OSError, KeyError) as exc:
            parser.error(str(exc))
        if receipt_path == args.fixture_receipt.resolve():
            parser.error('Proof receipt must not overwrite the signup fixture receipt')
    else:
        if args.fixture_receipt is not None:
            parser.error('--fixture-receipt requires --use-provisioned-state')
        state = state.resolve()
        if not state.is_relative_to(Path('/tmp')) or state == Path('/tmp') or state.exists():
            parser.error('State must be fresh under /tmp')
    if out.exists() or out.is_relative_to(state) or receipt_path.is_relative_to(state):
        parser.error('Outputs must be fresh and outside disposable state')
    all_candidates = load_candidates(args.candidates.resolve())
    selected_ids = set(args.only or IDS)
    candidates = [candidate for candidate in all_candidates if candidate['id'] in selected_ids]
    repo = args.repo_root.resolve()
    available_slots = [args.slot] if fixture else configured_slots(repo)
    if not available_slots:
        parser.error('No slot-specific test account credentials configured')
    if args.slot is not None and args.slot not in available_slots:
        parser.error('Explicit test account slot is not configured')
    sys.path[:0] = [str(repo / 'scripts'), str(repo)]
    from workflow_schedule_real_test import ProofError, acquire_leases, cli, ident, sessions
    from workflow_real_test_helpers import resolve_cli_path, run_cli
    cli_path = resolve_cli_path(str(args.cli_path.resolve()))
    receipt = {'status': 'started', 'target': API_URL, 'session': args.session, 'deployed_revision': args.revision,
               'started_at': datetime.now(UTC).isoformat(), 'candidate_sha256': digest(all_candidates),
               'selected_template_ids': [candidate['id'] for candidate in candidates],
               'verification_status': 'pending', 'media_status': 'pending',
               'media_failures': [], 'workflows': {}, 'cleanup': {}}
    leases, workflows, chats, renewal_errors = [], [], set(), []
    project_id, heartbeat = None, None
    stop = threading.Event()
    if fixture:
        receipt.update(auth_mode='provisioned_synthetic_signup',
                       fixture_receipt_sha256=hashlib.sha256(args.fixture_receipt.read_bytes()).hexdigest())
    else:
        state.mkdir(mode=0o700)
    out.mkdir(mode=0o700, parents=True)
    os.environ['OPENMATES_STATE_DIR'], os.environ['OPENMATES_PROFILE'] = str(state), ''
    os.environ.pop('OPENMATES_API_KEY', None)
    try:
        for configured_slot in ([args.slot] if args.slot is not None else available_slots):
            try:
                leases, slot = acquire_leases(args.session, configured_slot)
                break
            except ProofError as exc:
                if str(exc) != 'no_free_test_account_slot':
                    raise
        else:
            raise ProofError('no_free_test_account_slot')
        receipt['account_slot'] = slot
        def renew():
            while not stop.wait(sessions.DOCKER_TEST_LEASE_RENEW_INTERVAL_SECONDS):
                for lease_id, owner, resources, mode in leases:
                    try:
                        sessions.renew_test_resource_lease(lease_id, owner, resources, mode=mode)
                    except RuntimeError:
                        renewal_errors.append('lease_renewal_failed')
                        return
        heartbeat = threading.Thread(target=renew, daemon=True)
        heartbeat.start()
        if not fixture:
            diagnostic_path = out / 'login-diagnostic.json'
            try:
                login = subprocess.run(['node', '--experimental-strip-types', str(repo / 'scripts/workflow_templates_test_login.mjs'), 'login', '--slot', str(slot), '--api-url', API_URL], cwd=repo, capture_output=True, text=True, timeout=180, check=False)
            except subprocess.TimeoutExpired as exc:
                def decoded(value):
                    return value.decode(errors='replace') if isinstance(value, bytes) else value or ''
                private_json(diagnostic_path, {'exit_code': None, 'timed_out': True,
                                             'stdout': decoded(exc.stdout), 'stderr': decoded(exc.stderr)})
                receipt.update(login_exit_code=None, login_timed_out=True,
                               login_diagnostic=str(diagnostic_path))
                raise ProofError('disposable_login_timeout') from exc
            private_json(diagnostic_path, {'exit_code': login.returncode,
                                         'stdout': login.stdout, 'stderr': login.stderr})
            receipt.update(login_exit_code=login.returncode, login_diagnostic=str(diagnostic_path))
            if login.returncode:
                status = re.search(r'(?:Lookup|Login) failed with HTTP (\d{3})', login.stderr)
                message = re.search(r'\blogin\.[a-z_]+\b', login.stderr)
                if status:
                    receipt['login_http_status'] = int(status.group(1))
                if message:
                    receipt['login_message_code'] = message.group(0)
                if 'fetch failed' in login.stderr:
                    receipt['login_transport_failure'] = True
                for line in reversed(login.stderr.splitlines()):
                    try:
                        diagnostic = json.loads(line)
                        if isinstance(diagnostic.get('http_status'), int):
                            receipt['login_http_status'] = diagnostic['http_status']
                        if diagnostic.get('code') == 'login.transport_failure':
                            receipt['login_transport_failure'] = True
                        break
                    except (ValueError, AttributeError):
                        continue
                raise ProofError('disposable_login_failed')
        project = cli(cli_path, ['projects', 'create', f'Template proof {uuid4().hex[:8]}', '--write-policy', 'always_ask', '--personal'], 'project_create')
        project_id = ident((project.get('project') or {}).get('project_id'), 'project_id')
        receipt['project_id'] = project_id
        enabled = {item['id'] for item in cli(cli_path, ['workflows', 'capabilities'], 'capabilities') if item.get('enabled') is True}
        for candidate in candidates:
            for node in candidate['graph']['nodes']:
                if node['type'] == 'app_skill_action':
                    config = node['config']
                    if f"{config['app_id']}.{config['skill_id']}" not in enabled:
                        raise ProofError('candidate_capability_unavailable')
        verified = []
        for candidate in candidates:
            label = candidate['id']
            item = {'graph_sha256': digest(candidate['graph']), 'category': candidate['category'], 'icon': candidate['icon'], 'runs': []}
            receipt['workflows'][label] = item
            created = cli(cli_path, ['workflows', 'create', '--title', candidate['title'], '--graph', json.dumps(candidate['graph'], separators=(',', ':')), '--run-content-retention', 'last_5'], f'{label}_create', 240)
            workflow_id = ident(created.get('id'), 'workflow_id')
            workflows.append(workflow_id)
            item['workflow_id'] = workflow_id
            if created.get('enabled') is not False:
                raise ProofError('candidate_not_disabled')
            cli(cli_path, ['workflows', workflow_id, 'add-to-project', project_id, '--openmates-only', '--yes'], f'{label}_project')
            for occurrence in range(2 if label == 'website-changes' else 1):
                key = f'template-{uuid4()}'
                run = cli(cli_path, ['workflows', 'run', workflow_id, '--mode', 'manual', '--idempotency-key', key], f'{label}_accept_{occurrence}', 120)
                run_id = ident(run.get('id'), 'run_id')
                item.setdefault('accepted_runs', []).append({'run_id': run_id, 'idempotency_key': key})
                # Retry the same accepted invocation: --wait syncs and acknowledges
                # encrypted deliveries without rerunning skills.
                cli(cli_path, ['workflows', 'run', workflow_id, '--mode', 'manual', '--idempotency-key', key, '--wait'], f'{label}_wait_{occurrence}', 240)
                detail = cli(cli_path, ['workflows', 'run-show', workflow_id, run_id], f'{label}_run_show')
                for delivery in (detail.get('output_summary', {}).get('deliveries') or {}).values():
                    if delivery.get('chat_id'):
                        chats.add(delivery['chat_id'])
                private_json(out / label / f'run-{occurrence}.json', detail)
                item['runs'].append(validate_run(detail, candidate, occurrence))
            exported = out / label / f'{label}.workflow.yml'
            cli(cli_path, ['workflows', 'export', workflow_id, '--output', str(exported)], f'{label}_export')
            os.chmod(exported, 0o600)
            graph = restored_export_graph(load_portable_export(exported, cli_path), candidate['graph'])
            verified.append({**candidate, 'graph': graph})
            item.update(export_sha256=hashlib.sha256(exported.read_bytes()).hexdigest(), sanitized_graph_sha256=digest(graph))
            item['status'] = 'verified'
            # Preserve earlier successful proofs if a later provider fails.
            private_json(out / 'verified-templates.json', verified)
            receipt['verified_catalog'] = str(out / 'verified-templates.json')
            # Exact successful graph evidence is persisted before optional media.
            for occurrence, summary in enumerate(item['runs']):
                capture_dir = out / label / f'capture-{occurrence}'
                diagnostic_path = out / label / f'capture-{occurrence}-diagnostic.json'
                try:
                    capture = subprocess.run([sys.executable, str(repo / 'scripts/cli_video_capture.py'),
                        '--output-dir', str(capture_dir), '--target-environment', API_URL,
                        '--timeout-seconds', '90', '--display-number', str(180 + slot),
                        '--no-response-media', '--', 'node', str(cli_path), 'workflows', 'run-show',
                        workflow_id, summary['run_id'], '--api-url', API_URL, '--json'],
                        cwd=repo, capture_output=True, text=True, timeout=120, check=False)
                    private_json(diagnostic_path, {'exit_code': capture.returncode,
                                                  'stdout': capture.stdout, 'stderr': capture.stderr})
                    captured = (capture.returncode == 0 and (capture_dir / 'raw-terminal.mp4').is_file()
                                and (capture_dir / 'manifest.json').is_file())
                except subprocess.TimeoutExpired as exc:
                    def decoded(value):
                        return value.decode(errors='replace') if isinstance(value, bytes) else value or ''
                    private_json(diagnostic_path, {'exit_code': None, 'timed_out': True,
                        'stdout': decoded(exc.stdout), 'stderr': decoded(exc.stderr)})
                    captured = False
                summary['terminal_capture_diagnostic'] = str(diagnostic_path)
                summary['terminal_capture_status'] = 'captured' if captured else 'failed'
                if captured:
                    summary.update(terminal_recording=str(capture_dir / 'raw-terminal.mp4'),
                                   terminal_manifest=str(capture_dir / 'manifest.json'))
                else:
                    receipt['media_failures'].append({'template_id': label, 'run_id': summary['run_id'],
                                                      'diagnostic': str(diagnostic_path)})
                print(f'{label}: full run {occurrence + 1} verified; capture {summary["terminal_capture_status"]}.', flush=True)
        if renewal_errors:
            raise ProofError('lease_renewal_failed')
        private_json(out / 'verified-templates.json', verified)
        receipt.update(verified_catalog=str(out / 'verified-templates.json'), status='passed',
                       verification_status='passed')
    except BaseException as exc:
        receipt.update(status='failed', error_code=str(exc) if isinstance(exc, ProofError) else type(exc).__name__)
        receipt['verification_status'] = 'failed'
        if isinstance(exc, ValueError):
            receipt['assertion'] = str(exc)
        print(f"Template proof failed: {receipt['error_code']}", flush=True)
    finally:
        for workflow_id in reversed(workflows):
            try:
                for accepted in next(item for item in receipt['workflows'].values() if item.get('workflow_id') == workflow_id).get('accepted_runs', []):
                    detail = cli(cli_path, ['workflows', 'run-show', workflow_id, accepted['run_id']], 'cleanup_run_show')
                    if detail.get('status') not in {'completed', 'failed', 'cancelled'}:
                        cli(cli_path, ['workflows', 'run-cancel', workflow_id, accepted['run_id']], 'cleanup_cancel')
                    for delivery in (detail.get('output_summary', {}).get('deliveries') or {}).values():
                        if delivery.get('chat_id'):
                            chats.add(delivery['chat_id'])
                cli(cli_path, ['workflows', 'delete', workflow_id, '--yes'], 'cleanup_workflow')
                receipt['cleanup'][workflow_id] = 'deleted'
            except ProofError:
                receipt['cleanup'][workflow_id], receipt['status'] = 'failed', 'failed'
        for chat_id in sorted(chats):
            try:
                # Chat deletion prints human acknowledgements even with --json,
                # and may exit zero on per-chat failures. Verify the exact count.
                deletion = run_cli(cli_path, API_URL,
                                   ['chats', 'delete', chat_id, '--yes', '--personal'], timeout_seconds=60)
                private_json(out / 'cleanup' / f'chat-{chat_id}.json',
                             {'exit_code': deletion.returncode, 'stdout': deletion.stdout, 'stderr': deletion.stderr})
                if deletion.returncode != 0 or not re.search(r'\b1/1 chat\(s\) deleted\.', deletion.stdout):
                    raise ProofError('cleanup_chat_not_acknowledged')
                receipt['cleanup'][chat_id] = 'deleted'
            except (ProofError, subprocess.TimeoutExpired):
                receipt['cleanup'][chat_id], receipt['status'] = 'failed', 'failed'
        if project_id:
            try:
                cli(cli_path, ['projects', 'delete', project_id, '--confirm', project_id, '--personal'], 'cleanup_project')
                receipt['cleanup']['project'] = 'deleted'
            except ProofError:
                receipt['cleanup']['project'], receipt['status'] = 'failed', 'failed'
        stop.set()
        if heartbeat:
            heartbeat.join(timeout=2)
        for lease_id, *_ in reversed(leases):
            try:
                sessions.release_test_resource_lease(lease_id)
            except RuntimeError:
                receipt['cleanup']['lease'], receipt['status'] = 'failed', 'failed'
        receipt['finished_at'] = datetime.now(UTC).isoformat()
        capture_statuses = [run['terminal_capture_status'] for item in receipt['workflows'].values()
                            for run in item.get('runs', []) if 'terminal_capture_status' in run]
        receipt['media_status'] = 'failed' if receipt['media_failures'] else (
            'captured' if capture_statuses else 'not_attempted')
        if all(value == 'deleted' for value in receipt['cleanup'].values()) and receipt['status'] == 'passed':
            shutil.rmtree(state)
        else:
            receipt['retained_private_state'] = str(state)
        private_json(receipt_path, receipt)
        print(f'Private receipt: {receipt_path}', flush=True)
    return 0 if receipt['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
