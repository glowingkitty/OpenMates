/**
 * `settings` unit protocol of the shared Rust core Worker (unitPort.ts wire v1).
 *
 * Every operation is a pure decision of the shared Rust settings request policy
 * (packages/openmates-rust/src/web_settings.rs). The page keeps IndexedDB, the
 * decrypted entry store, notifications and the dialog; it sends the request
 * facts and gets back the dialog categories, entry rows, the answered guard
 * and the persisted request system message. Structured values travel as JSON text.
 */
import type { UnitProtocol } from '../host/unitPort';
import type { RequestCategory } from '../../appSettingsRequestPolicy';
import type { ConfirmOutcome, ResponseCategory, ResponseKeyPlan } from '../../appSettingsResponsePolicy';

export interface SettingsCategoryPlan { categories: RequestCategory[]; validKeys: string[] }
export type SettingsRequestMessageOutcome =
	| { kind: 'ok'; message: { message_id: string; role: 'system'; content: string; created_at: number; user_message_id: string } }
	| { kind: 'error'; message: string };

export interface SettingsUnitProtocol extends UnitProtocol {
	categoryPlan: { request: { requestedKeys: string; counts: string }; response: SettingsCategoryPlan };
	requestAnswered: { request: { systemContents: string; userMessageId: string }; response: boolean };
	buildRequestMessage: {
		request: { userMessageId: string; requestId: string; requestedKeys: string; createdAt: string; counts: string; voice: boolean };
		response: SettingsRequestMessageOutcome;
	};
	planSelectedKeys: { request: { selectedKeys: string }; response: ResponseKeyPlan[] };
	selectEntryIds: { request: { entryIds: string; selection: string }; response: string[] };
	responseCategories: { request: { categories: string; released: string }; response: ResponseCategory[] };
	confirmOutcome: { request: { releasedCount: number; voice: boolean; hasMessageId: boolean }; response: ConfirmOutcome };
	responseContent: { request: { userMessageId: string; action: string; categories: string }; response: string };
}

/** Worker module exports (snake_case, JSON strings) of browser_settings.rs. */
export interface SettingsBinding {
	settings_category_plan(requestedKeysJson: string, countsJson: string): string;
	settings_request_answered(systemContentsJson: string, userMessageId: string): boolean;
	settings_build_request_message(userMessageId: string, requestId: string, requestedKeysJson: string, createdAtJson: string, countsJson: string, voice: boolean): string;
	settings_plan_selected_keys(selectedKeysJson: string): string;
	settings_select_entry_ids(entryIdsJson: string, selectionJson: string): string;
	settings_response_categories(categoriesJson: string, releasedJson: string): string;
	settings_confirm_outcome(releasedCount: number, voice: boolean, hasMessageId: boolean): string;
	settings_response_content(userMessageId: string, action: string, categoriesJson: string): string;
}

const BINDING_EXPORTS: readonly (keyof SettingsBinding)[] = [
	'settings_category_plan', 'settings_request_answered', 'settings_build_request_message',
	'settings_plan_selected_keys', 'settings_select_entry_ids', 'settings_response_categories', 'settings_confirm_outcome', 'settings_response_content',
];

export function isSettingsBinding(value: unknown): value is SettingsBinding {
	if (typeof value !== 'object' || value === null) return false;
	const binding = value as Record<string, unknown>;
	return BINDING_EXPORTS.every((name) => typeof binding[name] === 'function');
}
