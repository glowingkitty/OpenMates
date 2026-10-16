import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';

export type UsageItem = { eventId: string; workspaceType: 'chat' | 'app' | 'workflow' | 'project'; credits: number };
type FixtureInput = {
	operation: 'seed' | 'cleanup' | 'personal-balance' | 'pdf-text';
	teamId?: string;
	ownerId?: string;
	items?: UsageItem[];
	pdfBase64?: string;
};

const root = path.resolve(__dirname, '../../../../..');
const compose = path.join(root, 'test-results/ci-private/compose.json');

/** Synthetic usage belongs only to Teams just created by this isolated CI browser test. */
function runFixture(input: FixtureInput): { balanceDigest?: string; text?: string } {
	if (
		process.env.GITHUB_ACTIONS !== 'true' ||
		process.env.RUNNER_ENVIRONMENT !== 'github-hosted' ||
		process.env.CI_TEST_MODE !== 'e2e' ||
		!existsSync(compose)
	) {
		throw new Error('Team usage fixture requires the disposable GitHub E2E stack');
	}
	const script = `
import asyncio, base64, hashlib, json, logging, os, sys, time
logging.disable(logging.CRITICAL)
assert os.environ.get('CI') == 'true'
assert os.environ.get('OPENMATES_CI_ISOLATED') == '1'
assert os.environ.get('OPENMATES_DEPLOYMENT_MODE') == 'self_host'
assert os.environ.get('FRONTEND_URLS') == 'http://localhost:5173'
assert os.environ.get('CMS_URL') == 'http://cms:8055'
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.directus.team_methods import hash_id

async def main():
    data = json.load(sys.stdin)
    if data['operation'] == 'pdf-text':
        import fitz
        document = fitz.open(stream=base64.b64decode(data['pdfBase64']), filetype='pdf')
        assert 0 < document.page_count <= 2
        print(json.dumps({'text': '\\n'.join(page.get_text() for page in document)}))
        return
    cache = CacheService()
    directus = DirectusService(cache_service=cache)
    try:
        owner_id = data['ownerId']
        fields = await directus.get_user_fields_direct(owner_id, ['id', 'encrypted_credit_balance'], no_cache=True)
        assert fields and fields.get('id') == owner_id
        balance = fields.get('encrypted_credit_balance') or ''
        digest = hashlib.sha256(balance.encode()).hexdigest()
        if data['operation'] != 'personal-balance':
            team_id = data['teamId']
            rows = await directus.get_items('teams', params={
                'filter[hashed_team_id][_eq]': hash_id(team_id),
                'fields': 'id,team_id,created_by_user_hash,created_at,status', 'limit': 2,
            }, no_cache=True, admin_required=True)
            assert isinstance(rows, list) and len(rows) == 1
            team = rows[0]
            assert team['team_id'] == team_id and team['created_by_user_hash'] == hash_id(owner_id)
            assert 0 <= time.time() - int(team['created_at']) <= 900
            membership = await directus.team.get_membership(team_id, owner_id)
            assert membership and membership.get('role') == 'owner'
            items = data['items']
            assert 1 <= len(items) <= 4
            assert len({item['eventId'] for item in items}) == len(items)
            for item in items:
                assert item['eventId'].startswith('team-usage-e2e-')
                assert item['workspaceType'] in ('chat', 'app', 'workflow', 'project')
                assert isinstance(item['credits'], int) and 1 <= item['credits'] <= 100
                existing = await directus.get_items('team_usage_events', params={
                    'filter[event_id][_eq]': item['eventId'], 'fields': 'id,hashed_team_id', 'limit': 2,
                }, no_cache=True, admin_required=True)
                if data['operation'] == 'seed':
                    assert existing == [], 'Refusing to overwrite an existing usage event'
                    assert team['status'] == 'active'
                    success, row = await directus.create_item('team_usage_events', {
                        'event_id': item['eventId'], 'hashed_team_id': hash_id(team_id),
                        'actor_user_hash': hash_id(owner_id), 'workspace_type': item['workspaceType'],
                        'object_id_hash': hashlib.sha256(item['eventId'].encode()).hexdigest(),
                        'credit_amount': item['credits'], 'created_at': int(time.time()),
                    }, admin_required=True)
                    assert success and row and row.get('id')
                else:
                    assert data['operation'] == 'cleanup'
                    for row in existing:
                        assert row['hashed_team_id'] == hash_id(team_id)
                        assert await directus.delete_item('team_usage_events', row['id'], admin_required=True)
        print(json.dumps({'balanceDigest': digest}))
    finally:
        await directus.close()
        await cache.close()

asyncio.run(main())
`;
	const output = execFileSync(
		'docker',
		[
			'compose', '-f', compose, 'exec', '-T', '-e', 'CI=true', '-e', 'OPENMATES_CI_ISOLATED=1',
			'api', 'python', '-c', script
		],
		{ cwd: root, input: JSON.stringify(input), encoding: 'utf8', timeout: 60_000 }
	);
	return JSON.parse(output.trim());
}

export function seedTeamUsage(teamId: string, ownerId: string, items: UsageItem[]): string {
	const result = runFixture({ operation: 'seed', teamId, ownerId, items });
	if (!result.balanceDigest) throw new Error('Missing Personal balance digest');
	return result.balanceDigest;
}

export function cleanupTeamUsage(teamId: string, ownerId: string, items: UsageItem[]): void {
	runFixture({ operation: 'cleanup', teamId, ownerId, items });
}

export function personalBalanceDigest(ownerId: string): string {
	const result = runFixture({ operation: 'personal-balance', ownerId });
	if (!result.balanceDigest) throw new Error('Missing Personal balance digest');
	return result.balanceDigest;
}

export function extractUsagePdfText(bytes: Buffer): string {
	const result = runFixture({ operation: 'pdf-text', pdfBase64: bytes.toString('base64') });
	if (!result.text) throw new Error('Team usage PDF has no text');
	return result.text;
}
