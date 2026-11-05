import { describe, expect, it } from 'vitest';
import { readWorkflowChatHandoff, advanceCompletionStartupContext, completionLinkAfterNavigation, decideCompletionPersonalContext, isWorkflowCompletionLink, preservesCompletionLinkOnTeamChange, readWorkflowCompletionLink, runConfirmsWorkflowChatTarget } from './workflowCompletionRoute';
import type { WorkflowRunDetail } from '@repo/ui';

const hash = '#workflow-id=workflow-1&workflow-tab=runs&run-id=run-1&chat-id=chat-1&message-id=message-1&delivery-id=delivery-1';
const run = {
	id: 'run-1',
	workflow_id: 'workflow-1',
	version_id: 'version-1',
	status: 'completed',
	trigger_type: 'schedule',
	node_runs: [{
		id: 'node-run-1',
		run_id: 'run-1',
		workflow_id: 'workflow-1',
		node_id: 'send',
		node_type: 'send_chat_message',
		status: 'completed',
		output_summary: { delivery_id: 'delivery-1', chat_id: 'chat-1', message_id: 'message-1' }
	}]
} satisfies WorkflowRunDetail;

describe('Workflow completion notification routing', () => {
	// contract-test: supporting surface=gui.web assertions=notifications.workflow-run.chat-target
	it('hands off both restored and client-side Workflow targets only after their exact chat route resolves', () => {
		const canonical = new URL('https://app.example/#chat-id=chat-1&message-id=message-1');
		for (const source of [hash, '#chat-id=chat-1&message-id=message-1&delivery-id=delivery-1&workflow-id=workflow-1&run-id=run-1&workflow-tab=runs']) {
			expect(readWorkflowChatHandoff(new URL(`https://app.example/${source}`), canonical))
				.toEqual({ hash: canonical.hash, chatId: 'chat-1', messageId: 'message-1' });
		}
		const secondMessage = '#chat-id=chat-1&message-id=message-2';
		expect(readWorkflowChatHandoff(
			new URL('https://app.example/' + secondMessage + '&delivery-id=delivery-2&workflow-id=workflow-1&run-id=run-1'),
			new URL('https://app.example/' + secondMessage)))
			.toEqual({ hash: secondMessage, chatId: 'chat-1', messageId: 'message-2' });
		expect(readWorkflowChatHandoff(null, canonical)).toBeNull();
		expect(readWorkflowChatHandoff(canonical, canonical)).toBeNull();
		expect(readWorkflowChatHandoff(new URL(`https://app.example/${hash}`), new URL('https://app.example/#chat-id=chat-1&message-id=other'))).toBeNull();
		expect(readWorkflowChatHandoff(new URL(`https://app.example/${hash}`), new URL('https://other.example/' + canonical.hash))).toBeNull();
	});

	// contract-test: direct surface=gui.web assertions=notifications.workflow-run.chat-target
	it('accepts ordinary message URLs and every committed Send even after a later failure', () => {
		const link = readWorkflowCompletionLink('#chat-id=chat-1&message-id=message-2&delivery-id=delivery-2&workflow-id=workflow-1&run-id=run-1&workflow-tab=runs');
		expect(link.kind).toBe('chat');
		if (link.kind !== 'chat') return;
		const failed = { ...run, status: 'failed' as const, completion_notification: {
			notification_id: 'first', chat_id: 'chat-1', message_id: 'message-1', delivery_id: 'delivery-1'
		}, node_runs: [...run.node_runs, { ...run.node_runs[0], id: 'second', node_id: 'second',
			output_summary: { delivery_id: 'delivery-2', chat_id: 'chat-1', message_id: 'message-2', status: 'acknowledged' } }] };
		expect(runConfirmsWorkflowChatTarget(failed, link.target)).toBe(true);
		expect(runConfirmsWorkflowChatTarget(failed, { ...link.target, messageId: 'foreign' })).toBe(false);
	});

	// contract-test: direct surface=gui.web assertions=notifications.workflow-run.chat-target
	it('accepts only an exact Send message delivery in the owner run', () => {
		const link = readWorkflowCompletionLink(hash);
		expect(link.kind).toBe('chat');
		if (link.kind !== 'chat') return;
		expect(runConfirmsWorkflowChatTarget(run, link.target)).toBe(true);
		expect(runConfirmsWorkflowChatTarget({ ...run, id: 'another-run' }, link.target)).toBe(false);
		expect(runConfirmsWorkflowChatTarget({ ...run, node_runs: [{ ...run.node_runs![0], output_summary: { delivery_id: 'delivery-2', chat_id: 'chat-1', message_id: 'message-1' } }] }, link.target)).toBe(false);
		expect(runConfirmsWorkflowChatTarget({ ...run, node_runs: [] }, link.target)).toBe(false);
		expect(runConfirmsWorkflowChatTarget({ ...run, node_runs: [], completion_notification: {
			notification_id: 'notification-1', chat_id: 'chat-1', message_id: 'message-1', delivery_id: 'delivery-1'
		} }, link.target)).toBe(true);
		expect(runConfirmsWorkflowChatTarget({ ...run, completion_notification: {
			notification_id: 'notification-1', chat_id: 'another-chat', message_id: 'message-1', delivery_id: 'delivery-1'
		} }, link.target)).toBe(false);
		expect(runConfirmsWorkflowChatTarget({ ...run, completion_notification: { notification_id: 'notification-2', chat_id: null } }, link.target)).toBe(true);
	});

	// contract-test: direct surface=gui.web assertions=notifications.workflow-run.run-target
	it('keeps a no-send link on its exact run and rejects partial chat targets', () => {
		expect(readWorkflowCompletionLink('#workflow-id=workflow-1&workflow-tab=runs&run-id=run-1')).toEqual({ kind: 'run' });
		expect(readWorkflowCompletionLink('#workflow-id=workflow-1&workflow-tab=runs&run-id=run-1&chat-id=chat-1')).toEqual({ kind: 'run' });
		expect(readWorkflowCompletionLink('#workflow-id=workflow-1&workflow-tab=runs&run-id=run-1&delivery-id=delivery-1')).toEqual({ kind: 'invalid' });
	});

	// contract-test: direct surface=gui.web assertions=notifications.workflow-run.run-target,notifications.workflow-run.chat-target
	it('switches workspace context only for marked run links or complete chat targets', () => {
		const ordinaryRun = '#workflow-id=workflow-1&workflow-tab=runs&run-id=run-1';
		expect(isWorkflowCompletionLink(ordinaryRun)).toBe(false);
		expect(isWorkflowCompletionLink(`${ordinaryRun}&workflow-completion=1`)).toBe(true);
		expect(isWorkflowCompletionLink(`${hash}&workflow-completion=1`)).toBe(true);
		expect(isWorkflowCompletionLink(hash)).toBe(true);
		expect(isWorkflowCompletionLink(`${ordinaryRun}&workflow-completion=1&chat-id=chat-1`)).toBe(false);
		expect(isWorkflowCompletionLink(`${ordinaryRun}&workflow-completion=1&delivery-id=delivery-1`)).toBe(false);
		expect(isWorkflowCompletionLink('#workflow-tab=runs&run-id=run-1&workflow-completion=1')).toBe(false);
	});

	// contract-test: direct surface=gui.web assertions=notifications.workflow-run.chat-target
	it('preserves only the explicit Personal reset and cancels deliberate Team or account changes', () => {
		const pending = { ownerId: 'owner-1', hash, fromTeamId: 'team-a' };
		const markedRun = '#workflow-id=workflow-1&workflow-tab=runs&run-id=run-1&workflow-completion=1';
		expect(preservesCompletionLinkOnTeamChange('team-a', 'owner-1', hash, pending, null)).toBe(true);
		expect(preservesCompletionLinkOnTeamChange(null, 'owner-1', hash, pending, null)).toBe(true);
		expect(preservesCompletionLinkOnTeamChange('team-b', 'owner-1', hash, pending, null)).toBe(false);
		expect(preservesCompletionLinkOnTeamChange('team-a', 'owner-2', hash, pending, null)).toBe(false);
		expect(preservesCompletionLinkOnTeamChange(null, 'owner-1', `${hash}&other=1`, pending, null)).toBe(false);
		expect(preservesCompletionLinkOnTeamChange('team-a', 'owner-1', hash, null, null)).toBe(false);
		// A later user-selected Personal→Team change must clear even a marked run link.
		expect(preservesCompletionLinkOnTeamChange('team-a', 'owner-1', markedRun, null, null)).toBe(false);
		expect(preservesCompletionLinkOnTeamChange('team-a', 'owner-1', '#workflow-id=workflow-1&workflow-tab=runs&run-id=run-1', null, null)).toBe(false);
	});

	// contract-test: supporting surface=gui.web assertions=notifications.workflow-run.chat-target
	it('retains only the initial notification through auth and Team restoration', () => {
		let startup = { hash, ownerId: null as string | null };
		// A Team preference can restore before the authenticated route may resolve it.
		expect(preservesCompletionLinkOnTeamChange('team-a', null, hash, null, startup)).toBe(true);
		startup = advanceCompletionStartupContext(startup, hash, 'owner-1', false)!;
		expect(startup.ownerId).toBe('owner-1');
		expect(preservesCompletionLinkOnTeamChange('team-a', 'owner-1', hash, null, startup)).toBe(true);
		expect(advanceCompletionStartupContext(startup, hash, 'owner-2', false)).toBeNull();
		expect(advanceCompletionStartupContext(startup, '#workflows', 'owner-1', false)).toBeNull();

		// Once the route is authenticated, its explicit Team→Personal token takes over.
		expect(advanceCompletionStartupContext(startup, hash, 'owner-1', true)).toBeNull();
		const pending = { ownerId: 'owner-1', hash, fromTeamId: 'team-a' };
		expect(preservesCompletionLinkOnTeamChange(null, 'owner-1', hash, pending, null)).toBe(true);
		expect(preservesCompletionLinkOnTeamChange('team-a', 'owner-1', hash, null, null)).toBe(false);

		// If startup was Personal, readiness consumes the startup exception before
		// a later deliberate Personal→Team selection on a marked run URL.
		const markedRun = '#workflow-id=workflow-1&workflow-tab=runs&run-id=run-1&workflow-completion=1';
		const personalStartup = { hash: markedRun, ownerId: 'owner-1' };
		const readyPersonal = advanceCompletionStartupContext(personalStartup, markedRun, 'owner-1', true);
		expect(readyPersonal).toBeNull();
		expect(preservesCompletionLinkOnTeamChange('team-a', 'owner-1', markedRun, null, readyPersonal)).toBe(false);
	});

	// contract-test: direct surface=gui.web assertions=notifications.workflow-run.run-target,notifications.workflow-run.chat-target
	it('does not mint a new Personal switch on a later user Team choice, but accepts a new visit', () => {
		const markedRun = '#workflow-id=workflow-1&workflow-tab=runs&run-id=run-1&workflow-completion=1';
		const readyPersonal = decideCompletionPersonalContext('owner-1', markedRun, null, null);
		expect(readyPersonal).toEqual({ handled: { ownerId: 'owner-1', hash: markedRun }, pending: null });
		const deliberateTeamChoice = decideCompletionPersonalContext('owner-1', markedRun, 'team-a', readyPersonal.handled);
		expect(deliberateTeamChoice.pending).toBeNull();
		expect(preservesCompletionLinkOnTeamChange('team-a', 'owner-1', markedRun, deliberateTeamChoice.pending, null)).toBe(false);
		// A different account cannot reuse the same visit's handled state.
		expect(decideCompletionPersonalContext('owner-2', markedRun, 'team-a', readyPersonal.handled).pending).toBeNull();
		const departed = completionLinkAfterNavigation(readyPersonal.handled, '#workflows');
		expect(departed).toBeNull();
		const reopened = decideCompletionPersonalContext('owner-1', markedRun, 'team-a', departed);
		expect(reopened.pending).toEqual({ ownerId: 'owner-1', hash: markedRun, fromTeamId: 'team-a' });
	});
});
