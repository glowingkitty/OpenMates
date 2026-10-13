/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/** Published refresh grace against the disposable isolated CI backend. */
const { test, expect } = require('./helpers/cookie-audit');
const { createHash, randomUUID } = require('node:crypto');
const { execFileSync } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const { getTestAccount, generateTotp } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

function expireIsolatedAccessWindow(token: string): void {
	const sourceRoot = process.env.OPENMATES_CI_SOURCE_ROOT;
	if (process.env.OPENMATES_CI_ISOLATED !== '1' || !sourceRoot) {
		throw new Error('Rotation fixture requires the disposable isolated CI backend.');
	}
	const composeFile = path.join(sourceRoot, 'test-results/ci-private/compose.json');
	if (!fs.existsSync(composeFile)) throw new Error('Isolated compose fixture is missing.');
	// Only the disposable session link changes. Neither the durable lifetime nor
	// any sibling session is modified; no credential goes into process arguments.
	const digest = createHash('sha256').update(token).digest('hex');
	const fixture = [
		'import json, os, re, sys, redis',
		'digest = sys.stdin.read().strip()',
		'assert re.fullmatch("[a-f0-9]{64}", digest)',
		'host, port = os.environ["DRAGONFLY_URL"].rsplit(":", 1)',
		'client = redis.Redis(host=host, port=int(port), password=os.environ["DRAGONFLY_PASSWORD"])',
		'key = "session:" + digest',
		'link = json.loads(client.get(key))',
		'assert link.get("user_id") and client.ttl(key) > 0',
		'link["token_expiry"] = 0',
		'assert client.set(key, json.dumps(link), xx=True, keepttl=True)'
	].join('\n');
	execFileSync('docker', ['compose', '-f', composeFile, 'exec', '-T', 'api', 'python', '-c', fixture], {
		input: digest, stdio: ['pipe', 'pipe', 'pipe'], timeout: 30000
	});
}

function challengeIsolatedSession(token: string): void {
	const sourceRoot = process.env.OPENMATES_CI_SOURCE_ROOT;
	if (process.env.OPENMATES_CI_ISOLATED !== '1' || !sourceRoot) {
		throw new Error('Risk fixture requires the disposable isolated CI backend.');
	}
	const composeFile = path.join(sourceRoot, 'test-results/ci-private/compose.json');
	if (!fs.existsSync(composeFile)) throw new Error('Isolated compose fixture is missing.');
	// Seed only a challenge on this disposable token. Approval must use the real
	// enrolled-factor endpoint below; no refresh token enters process arguments.
	const digest = createHash('sha256').update(token).digest('hex');
	const fixture = [
		'import asyncio, re, sys',
		'from backend.core.api.app.services.cache import CacheService',
		'from backend.core.api.app.services.directus import DirectusService',
		'from backend.core.api.app.services.session_security_state import COLLECTION, get_session_state',
		'digest = sys.stdin.read().strip()',
		'assert re.fullmatch("[a-f0-9]{64}", digest)',
		'async def main():',
		'    cache = CacheService()',
		'    directus = DirectusService(cache_service=cache)',
		'    try:',
		'        state = await get_session_state(directus, digest)',
		'        assert state and not state.get("risk_pending")',
		'        assert await directus._update_item(COLLECTION, state["id"], {"risk_pending": True, "strong_verified_at": None, "proof_method": None}, admin_required=True)',
		'        await cache.delete("auth:session-state:" + digest)',
		'    finally:',
		'        await directus.close()',
		'        await cache.close()',
		'asyncio.run(main())'
	].join('\n');
	execFileSync('docker', ['compose', '-f', composeFile, 'exec', '-T', 'api', 'python', '-c', fixture], {
		input: digest, stdio: ['pipe', 'pipe', 'pipe'], timeout: 30000
	});
}

async function refreshCookie(context: any): Promise<string> {
	const cookie = (await context.cookies()).find((value: any) => value.name === 'auth_refresh_token');
	if (!cookie?.value) throw new Error('Authenticated refresh cookie is missing.');
	return cookie.value;
}

function updateIsolatedPersonalMemoryRows(userId: string, ownerRowId: string, foreignRowId: string,
	marker: string, mode: 'seed' | 'delete'): void {
	const sourceRoot = process.env.OPENMATES_CI_SOURCE_ROOT;
	if (process.env.OPENMATES_CI_ISOLATED !== '1' || !sourceRoot) {
		throw new Error('Personal memory fixture requires the disposable isolated CI backend.');
	}
	const composeFile = path.join(sourceRoot, 'test-results/ci-private/compose.json');
	if (!fs.existsSync(composeFile)) throw new Error('Isolated compose fixture is missing.');
	const fixture = [
		'import asyncio, hashlib, json, sys, time, uuid',
		'from backend.core.api.app.services.directus import DirectusService',
		'data = json.load(sys.stdin)',
		'assert data["mode"] in ("seed", "delete")',
		'assert all(isinstance(data[key], str) and data[key] for key in ("user_id", "owner_id", "foreign_id", "marker"))',
		'assert uuid.UUID(data["owner_id"]) and uuid.UUID(data["foreign_id"])',
		'async def main():',
		'    directus = DirectusService()',
		'    try:',
		'        ids = (data["owner_id"], data["foreign_id"])',
		'        if data["mode"] == "delete":',
		'            for row_id in ids:',
		'                found = await directus.get_items("user_app_settings_and_memories", params={"filter": {"id": {"_eq": row_id}}, "limit": 1}, no_cache=True)',
		'                if found: assert await directus.delete_item("user_app_settings_and_memories", row_id)',
		'            return',
		'        owner_hash = hashlib.sha256(data["user_id"].encode()).hexdigest()',
		'        foreign_hash = hashlib.sha256(uuid.uuid4().bytes).hexdigest()',
		'        now = int(time.time())',
		'        for row_id, scope_hash in ((data["owner_id"], owner_hash), (data["foreign_id"], foreign_hash)):',
		'            created, _ = await directus.create_item("user_app_settings_and_memories", {',
		'                "id": row_id, "hashed_user_id": scope_hash, "hashed_team_id": None,',
		'                "app_id": "code", "item_type": "test", "item_key": row_id.replace("-", ""),',
		'                "encrypted_item_json": data["marker"], "encrypted_app_key": "",',
		'                "item_version": 1, "created_at": now, "updated_at": now, "sequence_number": 1,',
		'            })',
		'            assert created',
		'    finally:',
		'        await directus.close()',
		'asyncio.run(main())'
	].join('\n');
	execFileSync('docker', ['compose', '-f', composeFile, 'exec', '-T', 'api', 'python', '-c', fixture], {
		input: JSON.stringify({ user_id: userId, owner_id: ownerRowId, foreign_id: foreignRowId, marker, mode }),
		stdio: ['pipe', 'pipe', 'pipe'], timeout: 30000
	});
}

function updateIsolatedSendContextProjects(userId: string, projectIds: Record<string, string>,
	marker: string, mode: 'seed' | 'delete'): void {
	const sourceRoot = process.env.OPENMATES_CI_SOURCE_ROOT;
	if (process.env.OPENMATES_CI_ISOLATED !== '1' || !sourceRoot) {
		throw new Error('Send-context Project fixture requires the disposable isolated CI backend.');
	}
	const composeFile = path.join(sourceRoot, 'test-results/ci-private/compose.json');
	if (!fs.existsSync(composeFile)) throw new Error('Isolated compose fixture is missing.');
	const fixture = [
		'import asyncio, hashlib, json, sys, time, uuid',
		'from backend.core.api.app.services.directus import DirectusService',
		'data = json.load(sys.stdin)',
		'assert data["mode"] in ("seed", "delete")',
		'assert all(uuid.UUID(value) for value in data["project_ids"].values())',
		'async def main():',
		'    directus = DirectusService()',
		'    try:',
		'        ids = data["project_ids"]',
		'        if data["mode"] == "delete":',
		'            for project_id in ids.values():',
		'                hashed = hashlib.sha256(project_id.encode()).hexdigest()',
		'                settings = await directus.get_items("project_settings", params={"filter": {"hashed_project_id": {"_eq": hashed}}, "limit": -1}, no_cache=True)',
		'                for row in settings or []: assert await directus.delete_item("project_settings", row["id"])',
		'                projects = await directus.get_items("projects", params={"filter": {"project_id": {"_eq": project_id}}, "limit": 1}, no_cache=True)',
		'                for row in projects or []: assert await directus.delete_item("projects", row["id"])',
		'            return',
		'        owner = hashlib.sha256(data["user_id"].encode()).hexdigest()',
		'        foreign = hashlib.sha256(uuid.uuid4().bytes).hexdigest()',
		'        team = hashlib.sha256(uuid.uuid4().bytes).hexdigest()',
		'        now = int(time.time())',
		'        for kind, project_id in ids.items():',
		'            scope_user = foreign if kind == "foreign" else owner',
		'            scope_team = team if kind == "team" else None',
		'            created, _ = await directus.create_item("projects", {',
		'                "project_id": project_id, "hashed_user_id": scope_user, "hashed_team_id": scope_team,',
		'                "created_by_user_hash": owner, "encrypted_project_key": data["marker"] + ":key",',
		'                "encrypted_name": data["marker"] + ":name", "encrypted_description": data["marker"] + ":description",',
		'                "pinned": True, "archived": kind == "archived", "is_private": True, "is_shared": False,',
		'                "version": 1, "created_at": now, "updated_at": now, "last_opened_at": now, "item_count": 0,',
		'            })',
		'            assert created',
		'            if kind in ("enabled", "disabled"):',
		'                settings, _ = await directus.create_item("project_settings", {',
		'                    "hashed_project_id": hashlib.sha256(project_id.encode()).hexdigest(),',
		'                    "hashed_user_id": owner, "hashed_team_id": None, "updated_by_user_hash": owner,',
		'                    "write_mode": "always_ask", "auto_selection": kind == "enabled",',
		'                    "focus_activation_policy": "approval",',
		'                    "default_focus_id_hash": hashlib.sha256(uuid.uuid4().bytes).hexdigest(),',
		'                    "encrypted_settings": data["marker"] + ":settings", "updated_at": now,',
		'                })',
		'                assert settings',
		'    finally:',
		'        await directus.close()',
		'asyncio.run(main())'
	].join('\n');
	execFileSync('docker', ['compose', '-f', composeFile, 'exec', '-T', 'api', 'python', '-c', fixture], {
		input: JSON.stringify({ user_id: userId, project_ids: projectIds, marker, mode }),
		stdio: ['pipe', 'pipe', 'pipe'], timeout: 30000
	});
}

// contract-test: direct surface=rest_api assertions=auth.session.lifecycle,auth.session.isolation,auth.secrets.lifecycle
test('opt-in cookie session returns fresh scoped Personal ciphertext without widening default or anonymous responses', async ({ page, playwright }: any) => {
	test.setTimeout(120000);
	test.skip(process.env.OPENMATES_CI_ISOLATED !== '1', 'Requires the disposable isolated CI backend.');
	const credentials = getTestAccount();
	skipWithoutCredentials(test, credentials.email, credentials.password, credentials.otpKey);
	await loginToTestAccount(page, undefined, undefined, { waitForEditor: true, credentials });
	const apiUrl = process.env.OPENMATES_E2E_API_URL;
	if (!apiUrl || new URL(apiUrl).hostname !== 'localhost') {
		throw new Error('Personal memory fixture requires the runner-local API.');
	}
	const sessionId = await page.evaluate(() => sessionStorage.getItem('session_id'));
	if (!sessionId) throw new Error('Browser session ID is missing.');
	const userAgent = await page.evaluate(() => navigator.userAgent);
	const origin = new URL(page.url()).origin;
	const cookie = await refreshCookie(page.context());
	const authenticated = await playwright.request.newContext({
		baseURL: apiUrl, userAgent, extraHTTPHeaders: { Origin: origin, Cookie: `auth_refresh_token=${cookie}` }
	});
	const anonymous = await playwright.request.newContext({
		baseURL: apiUrl, userAgent, extraHTTPHeaders: { Origin: origin }
	});
	const ownerRowId = randomUUID();
	const foreignRowId = randomUUID();
	const marker = Buffer.from(`isolated-personal-memory:${ownerRowId}`).toString('base64');
	let ownerId: string | null = null;
	try {
		const ordinary = await authenticated.post('/v1/auth/session', { data: { session_id: sessionId } });
		expect(ordinary.status()).toBe(200);
		const ordinaryBody = await ordinary.json();
		expect(ordinaryBody.success).toBe(true);
		expect(Object.hasOwn(ordinaryBody, 'personal_memories')).toBe(false);
		ownerId = ordinaryBody.user?.id;
		expect(ownerId).toEqual(expect.any(String));
		updateIsolatedPersonalMemoryRows(ownerId!, ownerRowId, foreignRowId, marker, 'seed');

		const opted = await authenticated.post('/v1/auth/session', {
			data: { session_id: sessionId, include_personal_memories: true }
		});
		expect(opted.status()).toBe(200);
		const optedBody = await opted.json();
		expect(optedBody.success).toBe(true);
		expect(optedBody.user?.id).toBe(ownerId);
		expect(optedBody.ws_token).toEqual(expect.any(String));
		const batch = optedBody.personal_memories;
		expect(Object.keys(batch).sort()).toEqual(['encrypted_settings', 'memories']);
		expect(batch.encrypted_settings === null || typeof batch.encrypted_settings === 'string').toBe(true);
		expect(Array.isArray(batch.memories)).toBe(true);
		const ownerRow = batch.memories.find((row: any) => row.id === ownerRowId);
		expect(ownerRow).toBeTruthy();
		expect(Object.keys(ownerRow).sort()).toEqual([
			'app_id', 'created_at', 'encrypted_item_json', 'id', 'item_key', 'item_type', 'item_version', 'updated_at'
		]);
		expect(ownerRow).toMatchObject({ app_id: 'code', item_type: 'test',
			item_key: ownerRowId.replaceAll('-', ''), encrypted_item_json: marker, item_version: 1 });
		expect(batch.memories.some((row: any) => row.id === foreignRowId)).toBe(false);

		const unauthenticated = await anonymous.post('/v1/auth/session', {
			data: { session_id: sessionId, include_personal_memories: true }
		});
		expect(unauthenticated.status()).toBe(200);
		const anonymousBody = await unauthenticated.json();
		expect(anonymousBody.success).toBe(false);
		expect(Object.hasOwn(anonymousBody, 'personal_memories')).toBe(false);
	} finally {
		if (ownerId) updateIsolatedPersonalMemoryRows(ownerId, ownerRowId, foreignRowId, marker, 'delete');
		await Promise.all([authenticated.dispose(), anonymous.dispose()]);
	}
});

// contract-test: direct surface=gui.web assertions=auth.session.authoritative-enforcement,auth.session.isolation
test('Personal memory snapshot socket returns scoped ciphertext once and rejects a newly challenged session', async ({ page, playwright }: any) => {
	test.setTimeout(120000);
	test.skip(process.env.OPENMATES_CI_ISOLATED !== '1', 'Requires the disposable isolated CI backend.');
	const credentials = getTestAccount();
	skipWithoutCredentials(test, credentials.email, credentials.password, credentials.otpKey);
	let applicationSocketUrl: string | null = null;
	page.on('websocket', (socket: any) => {
		if (new URL(socket.url()).pathname.endsWith('/v1/ws')) applicationSocketUrl = socket.url();
	});
	await loginToTestAccount(page, undefined, undefined, { waitForEditor: true, credentials });
	await expect.poll(() => applicationSocketUrl).not.toBeNull();
	const apiUrl = process.env.OPENMATES_E2E_API_URL;
	if (!apiUrl || new URL(apiUrl).hostname !== 'localhost') {
		throw new Error('Personal memory fixture requires the runner-local API.');
	}
	const sessionId = await page.evaluate(() => sessionStorage.getItem('session_id'));
	if (!sessionId) throw new Error('Browser session ID is missing.');
	const userAgent = await page.evaluate(() => navigator.userAgent);
	const origin = new URL(page.url()).origin;
	const cookie = await refreshCookie(page.context());
	const authenticated = await playwright.request.newContext({
		baseURL: apiUrl, userAgent, extraHTTPHeaders: { Origin: origin, Cookie: `auth_refresh_token=${cookie}` }
	});
	const ownerRowId = randomUUID();
	const foreignRowId = randomUUID();
	const marker = Buffer.from(`isolated-personal-memory:${ownerRowId}`).toString('base64');
	let ownerId: string | null = null;
	try {
		const session = await authenticated.post('/v1/auth/session', { data: { session_id: sessionId } });
		expect(session.status()).toBe(200);
		const body = await session.json();
		expect(body.success).toBe(true);
		expect(body.ws_token).toEqual(expect.any(String));
		ownerId = body.user?.id;
		expect(ownerId).toEqual(expect.any(String));
		updateIsolatedPersonalMemoryRows(ownerId!, ownerRowId, foreignRowId, marker, 'seed');
		await page.exposeFunction('__challengePersonalMemorySnapshot', () => challengeIsolatedSession(cookie));
		const results = await page.evaluate(async (observedUrl: string) => {
			const sockets: WebSocket[] = [];
			const openSocket = () => new Promise<{ socket: WebSocket; capabilities: string[] }>((resolve, reject) => {
				const url = new URL(observedUrl);
				// A distinct correlation ID preserves the app's own connection while
				// retaining its signed token, device identity, cookie, and user agent.
				url.searchParams.set('sessionId', `personal-memory-snapshot-${crypto.randomUUID()}`);
				const socket = new WebSocket(url);
				sockets.push(socket);
				const timeout = setTimeout(() => reject(new Error('Personal snapshot socket did not advertise capabilities')), 20000);
				socket.addEventListener('message', (event) => {
					let frame: { type?: string; payload?: { capabilities?: string[] } };
					try { frame = JSON.parse(String(event.data)); } catch { return; }
					if (frame.type !== 'server_capabilities') return;
					clearTimeout(timeout);
					resolve({ socket, capabilities: frame.payload?.capabilities ?? [] });
				});
				socket.addEventListener('error', () => {
					clearTimeout(timeout);
					reject(new Error('Personal snapshot socket failed to open'));
				}, { once: true });
			});
			const request = (socket: WebSocket, requestId: string) => new Promise<Record<string, any>>((resolve, reject) => {
				const timeout = setTimeout(() => {
					socket.removeEventListener('message', receive);
					reject(new Error('Personal snapshot result timed out'));
				}, 20000);
				function receive(event: MessageEvent) {
					let frame: { type?: string; payload?: Record<string, any> };
					try { frame = JSON.parse(String(event.data)); } catch { return; }
					if (frame.type !== 'personal_memory_snapshot_result' || frame.payload?.request_id !== requestId) return;
					clearTimeout(timeout);
					socket.removeEventListener('message', receive);
					resolve(frame.payload);
				}
				socket.addEventListener('message', receive);
				socket.send(JSON.stringify({ type: 'personal_memory_snapshot', payload: { request_id: requestId } }));
			});
			try {
				const first = await openSocket();
				const requestId = crypto.randomUUID();
				const snapshot = await request(first.socket, requestId);
				const duplicate = await request(first.socket, crypto.randomUUID());
				// Open the second socket while the durable session is still valid;
				// the next request must check authority before the 10s watcher runs.
				const second = await openSocket();
				await (window as typeof window & { __challengePersonalMemorySnapshot: () => Promise<void> }).__challengePersonalMemorySnapshot();
				const challenged = await request(second.socket, crypto.randomUUID());
				return { capabilities: first.capabilities, snapshot, duplicate, challenged };
			} finally {
				for (const socket of sockets) socket.close();
			}
		}, applicationSocketUrl as string);
		expect(results.capabilities).toContain('personal_memory_snapshot_v1');
		expect(results.snapshot.success).toBe(true);
		const batch = results.snapshot.personal_memories;
		expect(Object.keys(batch).sort()).toEqual(['encrypted_settings', 'memories']);
		expect(batch.encrypted_settings === null || typeof batch.encrypted_settings === 'string').toBe(true);
		expect(Array.isArray(batch.memories)).toBe(true);
		const ownerRow = batch.memories.find((row: any) => row.id === ownerRowId);
		expect(ownerRow).toBeTruthy();
		expect(Object.keys(ownerRow).sort()).toEqual([
			'app_id', 'created_at', 'encrypted_item_json', 'id', 'item_key', 'item_type', 'item_version', 'updated_at'
		]);
		expect(ownerRow).toMatchObject({ app_id: 'code', item_type: 'test',
			item_key: ownerRowId.replaceAll('-', ''), encrypted_item_json: marker, item_version: 1 });
		expect(batch.memories.some((row: any) => row.id === foreignRowId)).toBe(false);
		expect(batch.memories.every((row: any) => !Object.hasOwn(row, 'hashed_user_id')
			&& !Object.hasOwn(row, 'hashed_team_id'))).toBe(true);
		expect(results.duplicate).toMatchObject({ success: false, error: { code: 'already_used' } });
		expect(Object.hasOwn(results.duplicate, 'personal_memories')).toBe(false);
		expect(results.challenged).toMatchObject({ success: false, error: { code: 'unauthorized' } });
		expect(Object.hasOwn(results.challenged, 'personal_memories')).toBe(false);
	} finally {
		if (ownerId) updateIsolatedPersonalMemoryRows(ownerId, ownerRowId, foreignRowId, marker, 'delete');
		await authenticated.dispose();
	}
});

// contract-test: direct surface=gui.web assertions=auth.session.authoritative-enforcement,auth.session.isolation
test('Personal send-context socket returns fresh scoped ciphertext and eligible Project metadata once', async ({ page, playwright }: any) => {
	test.setTimeout(150000);
	test.skip(process.env.OPENMATES_CI_ISOLATED !== '1', 'Requires the disposable isolated CI backend.');
	const credentials = getTestAccount();
	skipWithoutCredentials(test, credentials.email, credentials.password, credentials.otpKey);
	let applicationSocketUrl: string | null = null;
	page.on('websocket', (socket: any) => {
		if (new URL(socket.url()).pathname.endsWith('/v1/ws')) applicationSocketUrl = socket.url();
	});
	await loginToTestAccount(page, undefined, undefined, { waitForEditor: true, credentials });
	await expect.poll(() => applicationSocketUrl).not.toBeNull();
	const apiUrl = process.env.OPENMATES_E2E_API_URL;
	if (!apiUrl || new URL(apiUrl).hostname !== 'localhost') {
		throw new Error('Personal send-context fixture requires the runner-local API.');
	}
	const sessionId = await page.evaluate(() => sessionStorage.getItem('session_id'));
	if (!sessionId) throw new Error('Browser session ID is missing.');
	const userAgent = await page.evaluate(() => navigator.userAgent);
	const origin = new URL(page.url()).origin;
	const cookie = await refreshCookie(page.context());
	const authenticated = await playwright.request.newContext({
		baseURL: apiUrl, userAgent, extraHTTPHeaders: { Origin: origin, Cookie: `auth_refresh_token=${cookie}` }
	});
	const memoryIds = { owner: randomUUID(), foreign: randomUUID() };
	const projectIds = { enabled: randomUUID(), disabled: randomUUID(), archived: randomUUID(), foreign: randomUUID(), team: randomUUID() };
	const marker = Buffer.from(`isolated-send-context:${randomUUID()}`).toString('base64');
	let ownerId: string | null = null;
	let memoriesSeeded = false;
	let projectsSeeded = false;
	try {
		const session = await authenticated.post('/v1/auth/session', { data: { session_id: sessionId } });
		expect(session.status()).toBe(200);
		const body = await session.json();
		expect(body.success).toBe(true);
		expect(body.ws_token).toEqual(expect.any(String));
		ownerId = body.user?.id;
		expect(ownerId).toEqual(expect.any(String));
		memoriesSeeded = true;
		updateIsolatedPersonalMemoryRows(ownerId!, memoryIds.owner, memoryIds.foreign, marker, 'seed');
		projectsSeeded = true;
		updateIsolatedSendContextProjects(ownerId!, projectIds, marker, 'seed');
		await page.exposeFunction('__challengePersonalSendContext', () => challengeIsolatedSession(cookie));
		const results = await page.evaluate(async (observedUrl: string) => {
			const sockets: WebSocket[] = [];
			const openSocket = () => new Promise<{ socket: WebSocket; capabilities: string[] }>((resolve, reject) => {
				const url = new URL(observedUrl);
				url.searchParams.set('sessionId', `personal-send-context-${crypto.randomUUID()}`);
				const socket = new WebSocket(url);
				sockets.push(socket);
				const timeout = setTimeout(() => reject(new Error('Send-context socket did not advertise capabilities')), 20000);
				socket.addEventListener('message', (event) => {
					let frame: { type?: string; payload?: { capabilities?: string[] } };
					try { frame = JSON.parse(String(event.data)); } catch { return; }
					if (frame.type !== 'server_capabilities') return;
					clearTimeout(timeout);
					resolve({ socket, capabilities: frame.payload?.capabilities ?? [] });
				});
				socket.addEventListener('error', () => {
					clearTimeout(timeout);
					reject(new Error('Send-context socket failed to open'));
				}, { once: true });
			});
			const request = (socket: WebSocket, type: 'personal_send_context_snapshot' | 'personal_memory_snapshot') =>
				new Promise<Record<string, any>>((resolve, reject) => {
					const requestId = crypto.randomUUID();
					const expected = type === 'personal_send_context_snapshot'
						? 'personal_send_context_snapshot_result' : 'personal_memory_snapshot_result';
					const timeout = setTimeout(() => {
						socket.removeEventListener('message', receive);
						reject(new Error('Send-context result timed out'));
					}, 20000);
					function receive(event: MessageEvent) {
						let frame: { type?: string; payload?: Record<string, any> };
						try { frame = JSON.parse(String(event.data)); } catch { return; }
						if (frame.type !== expected || frame.payload?.request_id !== requestId) return;
						clearTimeout(timeout);
						socket.removeEventListener('message', receive);
						resolve(frame.payload);
					}
					socket.addEventListener('message', receive);
					socket.send(JSON.stringify({ type, payload: { request_id: requestId } }));
				});
			try {
				const first = await openSocket();
				const combined = await request(first.socket, 'personal_send_context_snapshot');
				const oldAfterCombined = await request(first.socket, 'personal_memory_snapshot');
				const second = await openSocket();
				const oldFirst = await request(second.socket, 'personal_memory_snapshot');
				const combinedAfterOld = await request(second.socket, 'personal_send_context_snapshot');
				const third = await openSocket();
				await (window as typeof window & { __challengePersonalSendContext: () => Promise<void> }).__challengePersonalSendContext();
				const challenged = await request(third.socket, 'personal_send_context_snapshot');
				return { capabilities: first.capabilities, combined, oldAfterCombined, oldFirst, combinedAfterOld, challenged };
		} finally {
			for (const socket of sockets) socket.close();
		}
		}, applicationSocketUrl as string);
		expect(results.capabilities).toContain('personal_send_context_snapshot_v1');
		expect(results.combined.success).toBe(true);
		expect(Object.keys(results.combined).sort()).toEqual(['personal_memories', 'project_candidates', 'request_id', 'success']);
		const batch = results.combined.personal_memories;
		expect(Object.keys(batch).sort()).toEqual(['encrypted_settings', 'memories']);
		expect(batch.encrypted_settings === null || typeof batch.encrypted_settings === 'string').toBe(true);
		expect(batch.memories.some((row: any) => row.id === memoryIds.owner && row.encrypted_item_json === marker)).toBe(true);
		expect(batch.memories.some((row: any) => row.id === memoryIds.foreign)).toBe(false);
		expect(batch.memories.every((row: any) => !Object.hasOwn(row, 'hashed_user_id') && !Object.hasOwn(row, 'hashed_team_id'))).toBe(true);
		const candidates = results.combined.project_candidates;
		expect(Array.isArray(candidates)).toBe(true);
		const enabled = candidates.find((row: any) => row.project_id === projectIds.enabled);
		expect(enabled).toEqual({ project_id: projectIds.enabled,
			encrypted_project_key: `${marker}:key`, encrypted_name: `${marker}:name`,
			encrypted_description: `${marker}:description`, auto_selection: true, focus_activation_policy: 'approval' });
		expect(candidates.some((row: any) => [projectIds.disabled, projectIds.archived, projectIds.foreign, projectIds.team].includes(row.project_id))).toBe(false);
		expect(candidates.every((row: any) => Object.keys(row).sort().join(',') ===
			'auto_selection,encrypted_description,encrypted_name,encrypted_project_key,focus_activation_policy,project_id')).toBe(true);
		expect(results.oldAfterCombined).toMatchObject({ success: false, error: { code: 'already_used' } });
		expect(Object.hasOwn(results.oldAfterCombined, 'personal_memories')).toBe(false);
		expect(results.oldFirst.success).toBe(true);
		expect(Object.hasOwn(results.oldFirst, 'project_candidates')).toBe(false);
		expect(results.combinedAfterOld).toMatchObject({ success: false, error: { code: 'already_used' } });
		expect(Object.hasOwn(results.combinedAfterOld, 'project_candidates')).toBe(false);
		expect(results.challenged).toMatchObject({ success: false, error: { code: 'unauthorized' } });
		expect(Object.hasOwn(results.challenged, 'personal_memories')).toBe(false);
		expect(Object.hasOwn(results.challenged, 'project_candidates')).toBe(false);
	} finally {
		if (ownerId && projectsSeeded) updateIsolatedSendContextProjects(ownerId, projectIds, marker, 'delete');
		if (ownerId && memoriesSeeded) updateIsolatedPersonalMemoryRows(ownerId, memoryIds.owner, memoryIds.foreign, marker, 'delete');
		await authenticated.dispose();
	}
});

// contract-test: direct surface=rest_api assertions=auth.session.risk-reauth,auth.session.authoritative-enforcement,auth.session.isolation
test('durable pending risk on a known device with unchanged country requires proof before issuing a WS token', async ({ page, playwright, browser }: any) => {
	test.setTimeout(180000);
	test.skip(process.env.OPENMATES_CI_ISOLATED !== '1', 'Requires the disposable isolated CI backend.');
	const credentials = getTestAccount();
	skipWithoutCredentials(test, credentials.email, credentials.password, credentials.otpKey);
	await loginToTestAccount(page, undefined, undefined, { waitForEditor: true, credentials });
	const apiUrl = process.env.OPENMATES_E2E_API_URL;
	if (!apiUrl || new URL(apiUrl).hostname !== 'localhost') {
		throw new Error('Risk fixture requires the runner-local API.');
	}
	const sessionId = await page.evaluate(() => sessionStorage.getItem('session_id'));
	if (!sessionId) throw new Error('Browser session ID is missing.');
	const userAgent = await page.evaluate(() => navigator.userAgent);
	const origin = new URL(page.url()).origin;
	const siblingContext = await browser.newContext({ baseURL: process.env.PLAYWRIGHT_TEST_BASE_URL, userAgent });
	const clients: any[] = [];
	async function holding(token: string): Promise<any> {
		const client = await playwright.request.newContext({
			baseURL: apiUrl, userAgent,
			extraHTTPHeaders: { Origin: origin, Cookie: `auth_refresh_token=${token}` }
		});
		clients.push(client);
		return client;
	}
	async function session(client: any): Promise<any> {
		return client.post('/v1/auth/session', { data: { session_id: sessionId } });
	}
	try {
		const siblingPage = await siblingContext.newPage();
		await loginToTestAccount(siblingPage, undefined, undefined, { waitForEditor: true, credentials });
		const siblingClient = await holding(await refreshCookie(siblingContext));
		const currentToken = await refreshCookie(page.context());
		const currentClient = await holding(currentToken);
		// Establish a successful baseline using exactly the same cookie, headers,
		// session ID and source address as the subsequent challenged requests.
		const baseline = await session(currentClient);
		expect(baseline.status()).toBe(200);
		const baselineBody = await baseline.json();
		expect(baselineBody.success).toBe(true);
		expect(baselineBody.re_auth_required).toBeNull();
		expect(baselineBody.ws_token).toEqual(expect.any(String));
		challengeIsolatedSession(currentToken);

		for (let attempt = 0; attempt < 2; attempt += 1) {
			const challenged = await session(currentClient);
			expect(challenged.status()).toBe(200);
			const body = await challenged.json();
			expect(body.success).toBe(false);
			expect(body.re_auth_required).toBe('2fa');
			expect(body.re_auth_reason).toBe('session_verification');
			expect(body.ws_token).toBeNull();
			expect((await currentClient.get('/v1/auth/sessions')).status()).toBe(401);
			expect((await siblingClient.get('/v1/auth/sessions')).status()).toBe(200);
		}

		// Account-wide replay protection also covers prior logins. Advance to a
		// fresh window and use its accepted next step for a real verification.
		await page.waitForTimeout((30 - Math.floor(Date.now() / 1000) % 30) * 1000 + 2000);
		const verified = await currentClient.post('/v1/auth/2fa/verify/device', {
			data: { tfa_code: generateTotp(credentials.otpKey, 1) }
		});
		expect(verified.status()).toBe(200);
		expect((await verified.json()).success).toBe(true);
		const resumed = await session(currentClient);
		expect(resumed.status()).toBe(200);
		const resumedBody = await resumed.json();
		expect(resumedBody.success).toBe(true);
		expect(resumedBody.re_auth_required).toBeNull();
		expect(resumedBody.ws_token).toEqual(expect.any(String));
		expect((await currentClient.get('/v1/auth/sessions')).status()).toBe(200);
		expect((await siblingClient.get('/v1/auth/sessions')).status()).toBe(200);
	} finally {
		await Promise.all(clients.map((client) => client.dispose()));
		await siblingContext.close();
	}
});

// contract-test: direct surface=rest_api assertions=auth.session.lifecycle,auth.session.authoritative-enforcement,auth.session.isolation
// contract-test: direct surface=gui.web assertions=auth.session.lifecycle
test('published rotation shares cookies, expires after grace, and respects revocation', async ({ page, playwright, browser }: any) => {
	test.setTimeout(120000);
	test.skip(process.env.OPENMATES_CI_ISOLATED !== '1', 'Requires the disposable isolated CI backend.');
	const credentials = getTestAccount();
	skipWithoutCredentials(test, credentials.email, credentials.password, credentials.otpKey);
	await loginToTestAccount(page, undefined, undefined, { waitForEditor: true, credentials });
	const apiUrl = process.env.OPENMATES_E2E_API_URL;
	if (!apiUrl || new URL(apiUrl).hostname !== 'localhost') {
		throw new Error('Rotation fixture requires the runner-local API.');
	}
	const sessionId = await page.evaluate(() => sessionStorage.getItem('session_id'));
	if (!sessionId) throw new Error('Browser session ID is missing.');
	const userAgent = await page.evaluate(() => navigator.userAgent);
	const origin = new URL(page.url()).origin;
	const clients: any[] = [];
	const siblingContext = await browser.newContext({ baseURL: process.env.PLAYWRIGHT_TEST_BASE_URL, userAgent });
	const siblingPage = await siblingContext.newPage();
	async function holding(token: string): Promise<any> {
		const client = await playwright.request.newContext({
			baseURL: apiUrl, userAgent,
			extraHTTPHeaders: { Origin: origin, Cookie: `auth_refresh_token=${token}` }
		});
		clients.push(client);
		return client;
	}
	async function session(client: any): Promise<any> {
		return client.post(`${apiUrl}/v1/auth/session`, { data: { session_id: sessionId }, headers: { Origin: origin } });
	}
	try {
		await loginToTestAccount(siblingPage, undefined, undefined, { waitForEditor: true, credentials });
		const siblingClient = await holding(await refreshCookie(siblingContext));
		const original = await refreshCookie(page.context());
		expireIsolatedAccessWindow(original);
		const rotated = await session(page.context().request);
		expect(rotated.status()).toBe(200);
		expect((await rotated.json()).success).toBe(true);
		const successor = await refreshCookie(page.context());
		expect(successor !== original, 'A single issuer rotation must publish a successor cookie.').toBe(true);
		const oldClient = await holding(original);
		const [overlap, protectedRequest] = await Promise.all([
			session(oldClient), oldClient.get('/v1/auth/sessions')
		]);
		expect(overlap.status()).toBe(200);
		expect((await overlap.json()).success).toBe(true);
		expect(protectedRequest.status()).toBe(200);
		const provider = await oldClient.post('/v1/auth/2fa/setup/provider', {
			data: { provider: 'Isolated fixture authenticator' }
		});
		expect(provider.status()).toBe(200);
		expect((await provider.json()).success).toBe(true);
		expect((provider.headers()['set-cookie'] || '').includes(`auth_refresh_token=${successor}`),
			'A manual authentication route must publish the successor on its model response.').toBe(true);
		// fetch resolves at response headers, allowing a real SSE response to be
		// checked and cancelled without buffering its indefinite event body.
		const stream = await fetch(`${apiUrl}/v1/notifications/stream`, {
			headers: { Origin: origin, Cookie: `auth_refresh_token=${original}`, 'User-Agent': userAgent }
		});
		try {
			expect(stream.status).toBe(200);
			expect(stream.headers.getSetCookie().some((cookie) => cookie.includes(`auth_refresh_token=${successor}`)),
				'A streaming response must carry the guard-approved successor cookie.').toBe(true);
		} finally {
			await stream.body?.cancel();
		}
		const listing = await protectedRequest.json();
		expect(listing.sessions.filter((item: any) => item.is_current).length).toBe(1);
		const registered = await oldClient.post('/v1/auth/sessions/register-meta', {
			data: { encrypted_meta: Buffer.from('opaque isolated fixture').toString('base64') }
		});
		expect(registered.status()).toBe(200);
		const logoutOthers = await oldClient.post('/v1/auth/sessions/logout-others', { data: {} });
		expect(logoutOthers.status()).toBe(200);
		expect((await siblingClient.get('/v1/auth/sessions')).status()).toBe(401);
		expect((await oldClient.get('/v1/auth/sessions')).status()).toBe(200);
		for (const result of [overlap, protectedRequest]) {
			const cookie = result.headers()['set-cookie'] || '';
			expect(cookie.includes(`auth_refresh_token=${successor}`), 'Overlap must reuse the published cookie.').toBe(true);
		}
		await expect(page.locator('[data-authenticated="true"]')).toBeVisible();
		await expect(page.getByTestId('message-editor')).toBeVisible();

		// Allow the real server's 15-second result TTL to expire.
		await page.waitForTimeout(16000);
		expect((await session(oldClient)).status()).toBe(401);
		expect((await oldClient.get('/v1/auth/sessions')).status()).toBe(401);
		const activeClient = await holding(successor);
		expect((await session(activeClient)).status()).toBe(200);

		// A second rotation creates a fresh grace interval, then explicit logout
		// must deny both its retired source and its active successor immediately.
		expireIsolatedAccessWindow(successor);
		expect((await session(page.context().request)).status()).toBe(200);
		const next = await refreshCookie(page.context());
		expect(next !== successor).toBe(true);
		const nextClient = await holding(next);
		const logout = await activeClient.post('/v1/auth/logout', { data: {} });
		expect(logout.status()).toBe(200);
		expect((await logout.json()).success).toBe(true);
		expect((await activeClient.get('/v1/auth/sessions')).status()).toBe(401);
		expect((await nextClient.get('/v1/auth/sessions')).status()).toBe(401);
	} finally {
		await Promise.all(clients.map((client) => client.dispose()));
		await siblingContext.close();
	}
});
