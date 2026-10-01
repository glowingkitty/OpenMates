import { describe, expect, it } from 'vitest';

import { isLegacyAppsWorkspaceHash, readWorkspaceHashRoute } from './workspaceHashRoute';

describe('readWorkspaceHashRoute', () => {
	// contract-test: supporting surface=gui.web assertions=workspace-shell.nav.released-surfaces-visible
	it.each([
		['#apps', { workspace: 'apps', itemId: null }],
		['#apps/all', { workspace: 'apps', itemId: null }],
		['#apps/health/search-appointments&tab=embeds&embed-id=embed-1', { workspace: 'apps', itemId: null }],
		['#workflows', { workspace: 'workflows', itemId: null }],
		['#/projects', { workspace: 'projects', itemId: null }],
		['#plans', { workspace: 'tasks', itemId: null }],
		['#tasks&settings=main', { workspace: 'tasks', itemId: null }],
		['#workflow-id=workflow-1&workflow-tab=runs', { workspace: 'workflows', itemId: 'workflow-1' }],
		['#project-id=project-1&settings=main', { workspace: 'projects', itemId: 'project-1' }],
		['#plan-id=plan-1', { workspace: 'plan-detail', itemId: 'plan-1' }],
		['#task-id=task-1', { workspace: 'tasks', itemId: 'task-1' }]
	] as const)('resolves %s', (hash, expected) => {
		expect(readWorkspaceHashRoute(hash)).toEqual(expected);
	});

	// contract-test: supporting surface=gui.web assertions=workspace-shell.nav.released-surfaces-visible
	it.each(['', '#chat-id=chat-1', '#settings/privacy', '#signup/welcome', '#embed-id=embed-1'])(
		'leaves established chat-shell hash %s with Chats',
		(hash) => {
			expect(readWorkspaceHashRoute(hash)).toEqual({ workspace: 'chats', itemId: null });
		}
	);
});

describe('isLegacyAppsWorkspaceHash', () => {
	// contract-test: supporting surface=gui.web assertions=apps.navigation.hash-and-forwarding
	it.each([
		'#settings/apps',
		'#settings/apps/health/skill/search_appointments',
		'#settings/apps/health/focus/prepare_doctor_appointment',
		'#settings/apps/health/memory/medical_history',
		'#settings=settings_memories',
		'#settings=apps/health/skill/search_appointments'
	])('preserves %s through startup before canonical forwarding', (hash) => {
		expect(isLegacyAppsWorkspaceHash(hash)).toBe(true);
	});

	// contract-test: supporting surface=gui.web assertions=apps.navigation.hash-and-forwarding
	it.each(['', '#settings/privacy', '#chat-id=chat-1&settings=apps/health', '#apps/health'])(
		'leaves %s to its existing startup owner',
		(hash) => expect(isLegacyAppsWorkspaceHash(hash)).toBe(false)
	);
});
