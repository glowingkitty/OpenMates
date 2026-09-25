export type WorkspaceHashRoute =
	| { workspace: 'chats'; itemId: null }
	| { workspace: 'plans'; itemId: string | null }
	| { workspace: 'projects'; itemId: string | null }
	| { workspace: 'tasks'; itemId: string | null }
	| { workspace: 'workflows'; itemId: string | null };

function normalizedFragment(hash: string): string {
	return hash.replace(/^#\/?/, '');
}

function hashParams(fragment: string): URLSearchParams {
	const [firstSegment] = fragment.split('&', 1);
	const hasWorkspaceMarker =
		firstSegment === 'workflows' ||
		firstSegment === 'projects' ||
		firstSegment === 'plans' ||
		firstSegment === 'tasks';
	const separator = fragment.indexOf('&');
	const parameterFragment = hasWorkspaceMarker
		? separator >= 0
			? fragment.slice(separator + 1)
			: ''
		: fragment;
	return new URLSearchParams(parameterFragment);
}

/**
 * Resolve the root app's hash to the workspace that owns it.
 *
 * List views use a short marker (`#projects`) while detail views use their
 * stable identifier (`#project-id=...`). Unknown hashes continue to belong to
 * Chats so settings, signup, embeds, and chat deep links keep working.
 */
export function readWorkspaceHashRoute(hash: string): WorkspaceHashRoute {
	const fragment = normalizedFragment(hash);
	const marker = fragment.split('&', 1)[0];
	const params = hashParams(fragment);

	const workflowId = params.get('workflow-id')?.trim();
	if (workflowId || marker === 'workflows') {
		return { workspace: 'workflows', itemId: workflowId || null };
	}

	const projectId = params.get('project-id')?.trim();
	if (projectId || marker === 'projects') {
		return { workspace: 'projects', itemId: projectId || null };
	}

	const planId = params.get('plan-id')?.trim();
	if (planId || marker === 'plans') {
		return { workspace: 'plans', itemId: planId || null };
	}

	const taskId = params.get('task-id')?.trim();
	if (taskId || marker === 'tasks') {
		return { workspace: 'tasks', itemId: taskId || null };
	}

	return { workspace: 'chats', itemId: null };
}
