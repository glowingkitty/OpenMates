import { describe, expect, it } from 'vitest';
import { completeWorkflowLogin } from './workflowCompletionAuth';

describe('Workflow completion login handoff', () => {
	// contract-test: supporting surface=gui.web assertions=notifications.workflow-run.chat-target
	it('publishes the verified owner before unlocking a pending completion target', () => {
		const calls: string[] = [];
		completeWorkflowLogin({ user: { id: 'owner-1' }, inSignupFlow: false }, {
			publishOwner: (id) => calls.push(`owner:${id}`),
			setSignupFlow: (active) => calls.push(`signup:${active}`),
			publishSession: () => calls.push('authenticated'),
			closeLogin: () => calls.push('close-login')
		});
		expect(calls).toEqual(['owner:owner-1', 'signup:false', 'authenticated', 'close-login']);
	});

	// contract-test: supporting surface=gui.web assertions=notifications.workflow-run.chat-target
	it('keeps unfinished signup open while publishing its session', () => {
		const calls: string[] = [];
		completeWorkflowLogin({ user: { id: 'owner-2' }, inSignupFlow: true }, {
			publishOwner: (id) => calls.push(`owner:${id}`),
			setSignupFlow: (active) => calls.push(`signup:${active}`),
			publishSession: () => calls.push('authenticated'),
			closeLogin: () => calls.push('close-login')
		});
		expect(calls).toEqual(['owner:owner-2', 'signup:true', 'authenticated']);
	});
});
