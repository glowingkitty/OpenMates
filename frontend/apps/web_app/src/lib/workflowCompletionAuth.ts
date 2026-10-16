/** Preserve a Workflow completion destination while publishing a successful login. */
export type WorkflowLoginSuccess = { user?: { id?: string }; inSignupFlow?: boolean };

export type WorkflowLoginActions = {
	publishOwner: (userId: string) => void;
	setSignupFlow: (active: boolean) => void;
	publishSession: () => void;
	closeLogin: () => void;
};

export function completeWorkflowLogin(detail: WorkflowLoginSuccess, actions: WorkflowLoginActions): void {
	const userId = detail.user?.id;
	if (userId) actions.publishOwner(userId);
	actions.setSignupFlow(detail.inSignupFlow === true);
	actions.publishSession();
	if (!detail.inSignupFlow) actions.closeLogin();
}
