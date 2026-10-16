/**
 * Parse Workflow completion deep links and verify their chat destination.
 * The owner-scoped run response is authoritative; URL IDs alone never open a chat.
 * A no-chat link remains on the exact run history entry.
 */
import type { WorkflowRunDetail } from '@repo/ui';

export type WorkflowCompletionTarget = {
	workflowId: string;
	runId: string;
	chatId: string;
	messageId: string;
	deliveryId: string;
};

export type WorkflowCompletionLink =
	| { kind: 'run' }
	| { kind: 'invalid' }
	| { kind: 'chat'; target: WorkflowCompletionTarget };

/** The run URL is also the safe fallback when no Send message node executed. */
export function readWorkflowCompletionLink(hash: string): WorkflowCompletionLink {
	const params = new URLSearchParams(hash.replace(/^#\/?/, ''));
	// Existing Workflow links may carry chat-id as unrelated authoring context.
	if (!params.has('message-id') && !params.has('delivery-id')) return { kind: 'run' };
	const workflowId = params.get('workflow-id')?.trim();
	const runId = params.get('run-id')?.trim();
	const chatId = params.get('chat-id')?.trim();
	const messageId = params.get('message-id')?.trim();
	const deliveryId = params.get('delivery-id')?.trim();
	if (!workflowId || !runId || params.get('workflow-tab') !== 'runs' || !chatId || !messageId || !deliveryId) {
		return { kind: 'invalid' };
	}
	return { kind: 'chat', target: { workflowId, runId, chatId, messageId, deliveryId } };
}

/** Only notification links may move an active Team context to Personal. */
export function isWorkflowCompletionLink(hash: string): boolean {
	const link = readWorkflowCompletionLink(hash);
	if (link.kind === 'chat') return true;
	if (link.kind === 'invalid') return false;
	const params = new URLSearchParams(hash.replace(/^#\/?/, ''));
	return params.get('workflow-completion') === '1' &&
		!!params.get('workflow-id')?.trim() &&
		params.get('workflow-tab') === 'runs' &&
		!!params.get('run-id')?.trim() &&
		!params.has('chat-id');
}

export type PersonalCompletionSwitch = { ownerId: string; hash: string; fromTeamId: string };
export type CompletionStartupContext = { hash: string; ownerId: string | null };
export type HandledCompletionLink = { ownerId: string; hash: string };

/** A new visit starts only after leaving the previous exact notification hash. */
export function completionLinkAfterNavigation(handled: HandledCompletionLink | null, hash: string): HandledCompletionLink | null {
	return handled?.hash === hash ? handled : null;
}

/** Resolve an authenticated notification once, even when it already starts in Personal. */
export function decideCompletionPersonalContext(
	ownerId: string,
	hash: string,
	teamId: string | null,
	handled: HandledCompletionLink | null
): { handled: HandledCompletionLink; pending: PersonalCompletionSwitch | null } {
	if (handled?.hash === hash) return { handled, pending: null };
	const nextHandled = { ownerId, hash };
	return {
		handled: nextHandled,
		pending: teamId ? { ownerId, hash, fromTeamId: teamId } : null
	};
}

/** Retain an initial notification hash only until its first authenticated route decision. */
export function advanceCompletionStartupContext(
	startup: CompletionStartupContext | null,
	hash: string,
	ownerId: string | null,
	routeReady: boolean
): CompletionStartupContext | null {
	if (!startup || startup.hash !== hash || (startup.ownerId && ownerId && startup.ownerId !== ownerId)) return null;
	if (routeReady) return null;
	return { hash: startup.hash, ownerId: startup.ownerId ?? ownerId };
}

/** Keep only the exact notification link through its one intentional Team→Personal reset. */
export function preservesCompletionLinkOnTeamChange(
	teamId: string | null,
	ownerId: string | null,
	hash: string,
	pending: PersonalCompletionSwitch | null,
	startup: CompletionStartupContext | null
): boolean {
	if (!isWorkflowCompletionLink(hash)) return false;
	if (pending) return !!ownerId && pending.ownerId === ownerId && pending.hash === hash &&
		(teamId === pending.fromTeamId || teamId === null);
	return !!startup && startup.hash === hash &&
		(startup.ownerId === null || startup.ownerId === ownerId);
}

/** Authoritative run detail, scoped by the API to its owner, must name the exact delivery. */
export function runConfirmsWorkflowChatTarget(run: WorkflowRunDetail, target: WorkflowCompletionTarget): boolean {
	if (run.id !== target.runId || run.workflow_id !== target.workflowId) return false;
	if (run.completion_notification) {
		return run.completion_notification.delivery_id === target.deliveryId &&
			run.completion_notification.chat_id === target.chatId &&
			run.completion_notification.message_id === target.messageId;
	}
	return (
		(run.node_runs ?? []).some((node) =>
			node.node_type === 'send_chat_message' &&
			node.status === 'completed' &&
			node.output_summary?.delivery_id === target.deliveryId &&
			node.output_summary?.chat_id === target.chatId &&
			node.output_summary?.message_id === target.messageId
		));
}
