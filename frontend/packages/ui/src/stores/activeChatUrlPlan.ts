/**
 * URL plan of `activeChatStore.updateUrlHash` as a pure decision. The store
 * gathers the facts (hash, route, semantic path) and applies the plan; the
 * flag-off path decides here, with VITE_OPENMATES_RUST_CORE the chatState unit
 * decides (packages/openmates-rust/src/web_chat_state/selection.rs).
 */
export interface UrlPlanFacts {
	chatId: string | null;
	/** The hash is an Apps workspace route. */
	appsRoute: boolean;
	hasChatIdParam: boolean;
	/** chat-id, workflow-id, run-id, message-id and delivery-id are all present. */
	workflowHandoff: boolean;
	onSemanticPath: boolean;
	currentHash: string;
	/** Hash the store built for this change (chat id set, or cleared when chatId is null). */
	targetHash: string;
}

export type UrlPlanAction = 'none' | 'replace_root' | 'replace_root_hash' | 'replace_hash';
export interface UrlPlan {
	action: UrlPlanAction;
	/** Stamp the programmatic-hash-update window (hashchange loop guard). */
	programmatic: boolean;
}

export function planUrlUpdate(f: UrlPlanFacts): UrlPlan {
	if (f.chatId) {
		if (f.onSemanticPath) return { action: 'replace_root_hash', programmatic: false };
		return f.currentHash !== f.targetHash ? { action: 'replace_hash', programmatic: true } : { action: 'none', programmatic: false };
	}
	if ((f.appsRoute && !f.hasChatIdParam) || f.workflowHandoff) return { action: 'none', programmatic: false };
	if (f.onSemanticPath) return { action: 'replace_root', programmatic: false };
	return f.currentHash !== f.targetHash ? { action: 'replace_hash', programmatic: true } : { action: 'none', programmatic: false };
}
