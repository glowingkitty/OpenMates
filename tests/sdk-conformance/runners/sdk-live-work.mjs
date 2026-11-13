/**
 * Live-backend npm driver for the cross-language API-key SDK harness
 * (frontend/apps/web_app/tests/sdk-live-work-crud.spec.ts). Reads one bounded
 * JSON batch of public `openmates/sdk` operations on stdin, runs them in order
 * against the real isolated backend with the explicit API key from the
 * environment and prints one JSON result per operation. Mirrors
 * packages/openmates-rust/examples/sdk-live-work-conformance.rs and
 * sdk-live-work.py; never reads CLI state.
 */
import {readFileSync} from 'node:fs';

const MAX_BATCH_BYTES = 1024 * 1024;
const {OpenMates, OpenMatesApiError, OpenMatesConfigError} = await import('../../../frontend/packages/openmates-cli/dist/sdk-entry.js');

/** Same stable classes as the Rust and Python drivers. */
function errorClass(error) {
	if (error instanceof OpenMatesApiError) {
		const status = error.status;
		if (status === 404 || status === 410) return {error: 'not_found'};
		if (status === 401) return {error: 'unauthorized'};
		if (status === 403) return {error: 'forbidden'};
		if (status === 409) return {error: 'conflict'};
		if (status === 400 || status === 422) return {error: 'invalid'};
		return {error: `http_${status}`};
	}
	if (error instanceof OpenMatesConfigError) return {error: 'invalid'};
	// A public SDK method that rejects with a plain Error (for example npm
	// tasks.show of a missing Task) has no typed class; report it as such so the
	// spec records the error-semantics gap instead of losing the whole batch.
	if (error instanceof Error) return {error: 'untyped', detail: error.constructor.name};
	throw error;
}

const camel = (input = {}) => {
	const out = {};
	for (const [key, value] of Object.entries(input)) {
		const name = key === 'linked_project_ids' ? 'linkedProjectIds' : key.replace(/_([a-z])/g, (_, c) => c.toUpperCase());
		out[name] = value;
	}
	return out;
};
// Tasks name Project links `projectIds` in the npm option type.
const taskInput = (input = {}) => {
	const {linkedProjectIds, ...rest} = camel(input);
	return linkedProjectIds ? {...rest, projectIds: linkedProjectIds} : rest;
};
const personal = {personal: true};

async function run(client, op) {
	const key = `${op.family}.${op.op}`;
	switch (key) {
		case 'probe.chats': return {count: (await client.chats.list({limit: 1})).length ?? null};
		case 'projects.create': return client.projects.create(camel(op.input), personal);
		case 'projects.show': return client.projects.show(op.id, personal);
		case 'projects.list': return client.projects.list(personal);
		case 'projects.update': return client.projects.update(op.id, camel(op.input), personal);
		case 'projects.delete': return client.projects.delete(op.id, {...personal, confirmed: true});
		case 'tasks.create': return client.tasks.create(taskInput(op.input));
		case 'tasks.show': return client.tasks.show(op.id);
		case 'tasks.list': return client.tasks.list();
		case 'tasks.update': return client.tasks.update(op.id, taskInput(op.input));
		case 'tasks.delete': return client.tasks.delete(op.id, {confirmed: true});
		case 'plans.create': return client.plans.create(camel(op.input));
		case 'plans.show': return client.plans.show(op.id);
		case 'plans.list': return client.plans.list();
		case 'plans.update': return client.plans.update(op.id, camel(op.input));
		case 'plans.delete': return client.plans.delete(op.id, {confirmed: true});
		case 'history.list': return client.history.list({objectType: op.input?.object_type, objectId: op.input?.object_id, limit: op.input?.limit});
		case 'docs.list': return client.docs.list();
		default: throw new Error(`unsupported live operation ${key}`);
	}
}

const raw = readFileSync(0);
if (raw.length > MAX_BATCH_BYTES) throw new Error('batch bound');
const batch = JSON.parse(raw);
for (const name of ['OPENMATES_API_KEY', 'OPENMATES_API_URL', 'OPENMATES_DEVICE_ID']) {
	if (!process.env[name]) throw new Error(`${name} required`);
}
const client = new OpenMates({
	apiKey: process.env.OPENMATES_API_KEY,
	apiUrl: process.env.OPENMATES_API_URL,
	deviceId: process.env.OPENMATES_DEVICE_ID
});
const results = [];
for (const op of batch.operations) {
	try {
		results.push({ok: true, value: (await run(client, op)) ?? null});
	} catch (error) {
		results.push({ok: false, ...errorClass(error)});
	}
}
console.log(JSON.stringify(results));
