import { execFileSync } from 'node:child_process';
import path from 'node:path';

/** Seed a historical link only on a newly created task in disposable CI storage. */
export function seedLegacyTaskLink(taskId: string): void {
	if (process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted'
		|| process.env.CI_TEST_MODE !== 'e2e') {
		throw new Error('Legacy task fixtures require the isolated GitHub E2E stack');
	}
	const root = path.resolve(__dirname, '../../../../..');
	const script = `
import os, sys, time
import requests

assert os.environ.get("CI") == "true"
assert os.environ.get("OPENMATES_CI_ISOLATED") == "1"
assert os.environ.get("OPENMATES_DEPLOYMENT_MODE") == "self_host"
assert os.environ.get("FRONTEND_URLS") == "http://localhost:5173"
assert os.environ.get("CMS_URL") == "http://cms:8055"
login = requests.post("http://cms:8055/auth/login", json={
    "email": os.environ["DATABASE_ADMIN_EMAIL"],
    "password": os.environ["DATABASE_ADMIN_PASSWORD"],
}, timeout=15)
login.raise_for_status()
headers = {"Authorization": "Bearer " + login.json()["data"]["access_token"]}
url = "http://cms:8055/items/user_tasks"
response = requests.get(url, headers=headers, params={
    "filter[task_id][_eq]": sys.argv[1],
    "fields": "id,created_at,version,encrypted_title,primary_chat_id,external_chat_provider,assignee_type",
}, timeout=15)
response.raise_for_status()
rows = response.json()["data"]
assert len(rows) == 1
task = rows[0]
assert 0 <= time.time() - int(task["created_at"]) <= 900
assert not task.get("primary_chat_id") and not task.get("external_chat_provider")
assert task.get("assignee_type") in ("user", "unassigned")
response = requests.patch(url + "/" + task["id"], headers=headers, json={
    "external_chat_provider": "opencode",
    "external_chat_lookup_hash": "c" * 64,
    "encrypted_external_chat_id": task["encrypted_title"],
    "encrypted_external_chat_title": task["encrypted_title"],
    "version": int(task["version"]) + 1,
}, timeout=15)
response.raise_for_status()
print("legacy task fixture seeded")
`;
	const output = execFileSync('docker', [
		'compose', '-f', path.join(root, 'test-results/ci-private/compose.json'),
		'exec', '-T', '-e', 'CI=true', '-e', 'OPENMATES_CI_ISOLATED=1',
		'api', 'python', '-c', script, taskId,
	], { cwd: root, encoding: 'utf8', timeout: 45_000 });
	if (output.trim() !== 'legacy task fixture seeded') throw new Error('Legacy task fixture did not complete');
}
