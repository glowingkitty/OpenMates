/** Shared Git-ignore and additive private-path policy for Project file executors. */

import ignore, { type Ignore } from 'ignore';
import { PROJECT_CREDENTIAL_GLOBS } from './projectSearchProtocol.js';

export const PROJECT_BUILTIN_PRIVATE_PATHS = [
	...PROJECT_CREDENTIAL_GLOBS,
	'.openmates/permissions.yml',
	'**/.openmates/permissions.yml',
] as const;

export interface ProjectIgnoreFile {
	/** POSIX path relative to the policy root, for example `.gitignore` or `src/.gitignore`. */
	path: string;
	content: string;
}

export interface ProjectPathPolicyInput {
	ignoreFiles: ProjectIgnoreFile[];
	privatePaths: string[];
}

export interface ProjectPathPolicy {
	isIgnored(path: string, isDirectory?: boolean): boolean;
	isPrivate(path: string, isDirectory?: boolean): boolean;
	/** Conservative ripgrep exclusions. Callers still apply isPrivate to every result. */
	privateGlobs(): readonly string[];
}

export class ProjectPathPolicyError extends Error {
	readonly code = 'invalid_policy';

	constructor(message: string) {
		super(message);
		this.name = 'ProjectPathPolicyError';
	}
}

interface ScopedIgnore {
	base: string;
	matcher: Ignore;
}

export function createProjectPathPolicy(input: ProjectPathPolicyInput): ProjectPathPolicy {
	if (!input || !Array.isArray(input.ignoreFiles) || !Array.isArray(input.privatePaths)) {
		throw new ProjectPathPolicyError('Project path policy input is invalid');
	}

	const scopedIgnores = input.ignoreFiles
		.map((file) => {
			const path = normalizePolicyPath(file.path, false);
			if (path !== '.gitignore' && !path.endsWith('/.gitignore')) {
				throw new ProjectPathPolicyError(`Ignore file path is invalid: ${file.path}`);
			}
			if (typeof file.content !== 'string') throw new ProjectPathPolicyError(`Ignore file content is invalid: ${path}`);
			return { path, base: path === '.gitignore' ? '' : path.slice(0, -'/.gitignore'.length), content: file.content };
		})
		.sort((left, right) => pathDepth(left.base) - pathDepth(right.base) || left.path.localeCompare(right.path))
		.map(({ base, content }) => ({ base, matcher: ignore({ ignorecase: false }).add(content) }));

	const privatePatterns = [...new Set([...PROJECT_BUILTIN_PRIVATE_PATHS, ...input.privatePaths].map(normalizePrivatePattern))];
	const privateMatcher = ignore().add(privatePatterns);
	const privateRgGlobs = [...new Set(privatePatterns.flatMap(privatePatternToRgGlobs))];

	return {
		isIgnored(path, isDirectory = false) {
			const normalized = normalizePolicyPath(path, true);
			return evaluateScopedIgnores(scopedIgnores, normalized, isDirectory);
		},
		isPrivate(path, isDirectory = false) {
			const normalized = normalizePolicyPath(path, true);
			if (privateMatcher.ignores(asIgnoreCandidate(normalized, isDirectory))) return true;
			// A private subtree pattern such as `secrets/**` protects its directory name too.
			return isDirectory && privateMatcher.ignores(`${normalized}/.openmates-private-path-probe`);
		},
		privateGlobs() {
			return privateRgGlobs;
		},
	};
}

function evaluateScopedIgnores(scopes: ScopedIgnore[], path: string, isDirectory: boolean): boolean {
	let ignored = false;
	for (const scope of scopes) {
		if (scope.base) {
			if (path !== scope.base && !path.startsWith(`${scope.base}/`)) continue;
			// Git never reads an ignore file inside a directory excluded by a parent rule.
			if (evaluateEarlierScopes(scopes, scope, scope.base)) continue;
		}
		const relative = scope.base ? path.slice(scope.base.length + (path === scope.base ? 0 : 1)) : path;
		if (!relative) continue;
		const result = scope.matcher.test(asIgnoreCandidate(relative, isDirectory));
		if (result.ignored) ignored = true;
		else if (result.unignored) ignored = false;
	}
	return ignored;
}

function evaluateEarlierScopes(scopes: ScopedIgnore[], current: ScopedIgnore, directory: string): boolean {
	let ignored = false;
	for (const scope of scopes) {
		if (scope === current) break;
		if (scope.base && directory !== scope.base && !directory.startsWith(`${scope.base}/`)) continue;
		const relative = scope.base ? directory.slice(scope.base.length + (directory === scope.base ? 0 : 1)) : directory;
		if (!relative) continue;
		const result = scope.matcher.test(asIgnoreCandidate(relative, true));
		if (result.ignored) ignored = true;
		else if (result.unignored) ignored = false;
	}
	return ignored;
}

function normalizePolicyPath(value: string, allowRoot: boolean): string {
	if (typeof value !== 'string' || value.includes('\\') || hasControl(value) || value.startsWith('/') || /^[A-Za-z]:/.test(value)) {
		throw new ProjectPathPolicyError(`Project path is invalid: ${String(value)}`);
	}
	const parts = value.replace(/^\.\//, '').split('/');
	if (parts.some((part) => part === '..')) throw new ProjectPathPolicyError(`Project path escapes its root: ${value}`);
	const normalized = parts.filter((part) => part && part !== '.').join('/');
	if (!normalized && !allowRoot) throw new ProjectPathPolicyError('Project path cannot be empty');
	return normalized || '.';
}

function normalizePrivatePattern(value: string): string {
	if (typeof value !== 'string' || !value.trim() || value.startsWith('!') || value.includes('\\') || hasControl(value)
		|| /^[A-Za-z]:/.test(value) || value.split('/').some((part) => part === '..')) {
		throw new ProjectPathPolicyError(`Private path pattern is invalid: ${String(value)}`);
	}
	const normalized = value.startsWith('./') ? value.slice(2) : value;
	if (!normalized || normalized === '/' || normalized.startsWith('//')) {
		throw new ProjectPathPolicyError(`Private path pattern is invalid: ${value}`);
	}
	return normalized;
}

function privatePatternToRgGlobs(pattern: string): string[] {
	const anchored = pattern.startsWith('/');
	let value = anchored ? pattern.slice(1) : pattern;
	const directory = value.endsWith('/');
	if (directory) value = value.slice(0, -1);
	const values = value.includes('/') || anchored ? [value] : [value, `**/${value}`];
	return values.flatMap((item) => directory ? [item, `${item}/**`] : [item]);
}

function asIgnoreCandidate(path: string, isDirectory: boolean): string {
	const normalized = path === '.' ? '' : path;
	return isDirectory && normalized && !normalized.endsWith('/') ? `${normalized}/` : normalized;
}

function pathDepth(path: string): number {
	return path ? path.split('/').length : 0;
}

function hasControl(value: string): boolean {
	return [...value].some((character) => {
		const code = character.charCodeAt(0);
		return code < 32 || code === 127;
	});
}
