import { describe, expect, it } from 'vitest';

import { readWorkspaceHashRoute } from './workspaceHashRoute';

describe('readWorkspaceHashRoute', () => {
	// contract-test: supporting surface=gui.web assertions=workspace-shell.nav.released-surfaces-visible
	it.each([
		['#workflows', { workspace: 'workflows', itemId: null }],
		['#/projects', { workspace: 'projects', itemId: null }],
		['#plans', { workspace: 'plans', itemId: null }],
		['#tasks&settings=main', { workspace: 'tasks', itemId: null }],
		['#workflow-id=workflow-1&workflow-tab=runs', { workspace: 'workflows', itemId: 'workflow-1' }],
		['#project-id=project-1&settings=main', { workspace: 'projects', itemId: 'project-1' }],
		['#plan-id=plan-1', { workspace: 'plans', itemId: 'plan-1' }],
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
