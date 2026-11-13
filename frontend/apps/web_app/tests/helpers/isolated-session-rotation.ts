/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Disposable isolated-CI fixture that makes the next /v1/auth/session call
 * rotate this refresh token, as an ordinary reload ~10 minutes after login or a
 * second tab's reload would. Only the session cache link's access window is
 * changed; the durable lifetime and sibling sessions are untouched, and no
 * credential is passed in process arguments.
 */
const { createHash } = require('node:crypto');
const { execFileSync } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');

function expireIsolatedAccessWindow(token: string): void {
	const sourceRoot = process.env.OPENMATES_CI_SOURCE_ROOT;
	if (process.env.OPENMATES_CI_ISOLATED !== '1' || !sourceRoot) {
		throw new Error('Rotation fixture requires the disposable isolated CI backend.');
	}
	const composeFile = path.join(sourceRoot, 'test-results/ci-private/compose.json');
	if (!fs.existsSync(composeFile)) throw new Error('Isolated compose fixture is missing.');
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

module.exports = { expireIsolatedAccessWindow };
