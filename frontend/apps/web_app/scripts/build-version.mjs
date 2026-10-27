import { execFileSync } from 'node:child_process';

/** SvelteKit hashes this value into its HTML/client bootstrap global. */
export function getVersionName() {
	// Vercel CLI uploads omit .git. VERCEL_URL is stable for all workers in
	// that deployment; a timestamp evaluated separately in each worker is not.
	for (const key of ['OPENMATES_BUILD_VERSION', 'VERCEL_GIT_COMMIT_SHA', 'VERCEL_URL']) {
		const value = process.env[key]?.trim();
		if (value) return value;
	}
	try {
		return execFileSync('git', ['rev-parse', 'HEAD'], {
			encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore']
		}).trim();
	} catch {
		throw new Error('Cannot identify this build. Set OPENMATES_BUILD_VERSION to one stable value for every build worker.');
	}
}
