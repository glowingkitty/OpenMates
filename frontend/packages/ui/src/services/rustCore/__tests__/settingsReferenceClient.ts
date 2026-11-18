/**
 * Test-only stand-in for the shared Rust core Worker `settings` unit
 * (settingsClient.ts). Unit suites have no Worker, so test-setup.ts swaps
 * `settingsCall` for this module: it decodes the same JSON-string payloads the
 * page adapter (rustSettingsRequests.ts) sends and answers with the reference
 * policy below, a port of web_settings*.rs used only by tests. The product
 * decisions themselves are proven by the crate tests (web_settings_tests.rs).
 * Connected-account ops on the same unit go to the real client unchanged;
 * settingsSharedUnit and connectedAccountsSharedUnit tests unmock this module.
 */
import { vi } from 'vitest';
import { buildMemoryRequestMessage } from '../../../utils/appMemoryRequests';
import { formatDisplayName, getAppGradient, type RequestCategory } from '../../appSettingsRequestPolicy';
import type {
	ConfirmOutcome, PrivacyEntryPlan, ResponseCategory, ResponseKeyPlan, SettingsUnitProtocol,
} from '../settings/settingsProtocol';

export const rustSettingsStats = { calls: 0, failures: 0, opens: 0, ops: {} as Record<string, number> };

type Payload = Record<string, unknown>;
const json = <T>(value: unknown): T => JSON.parse(value as string) as T;

function splitKey(key: string): [string, string] | null {
	const dash = key.indexOf('-');
	return dash === -1 ? null : [key.substring(0, dash), key.substring(dash + 1)];
}

function categoryPlan(p: Payload): { categories: RequestCategory[]; validKeys: string[] } {
	const counts = json<Record<string, number>>(p.counts);
	const categories: RequestCategory[] = [];
	const validKeys: string[] = [];
	for (const key of json<string[]>(p.requestedKeys)) {
		const parts = splitKey(key);
		if (!parts || !parts[0] || !parts[1]) continue;
		const entryCount = counts[key] || 0;
		if (entryCount === 0) continue;
		validKeys.push(key);
		categories.push({
			key, appId: parts[0], itemType: parts[1], displayName: formatDisplayName(parts[1]),
			entryCount, iconGradient: getAppGradient(parts[0]), selected: true,
		});
	}
	return { categories, validKeys };
}

function requestAnswered(p: Payload): boolean {
	return json<string[]>(p.systemContents).some((content) => {
		if (!content) return false;
		try {
			const parsed = JSON.parse(content);
			return parsed.type === 'app_settings_memories_response' && parsed.user_message_id === p.userMessageId;
		} catch {
			return false;
		}
	});
}

function buildRequestMessage(p: Payload) {
	try {
		return {
			kind: 'ok' as const,
			message: buildMemoryRequestMessage({
				userMessageId: p.userMessageId as string, requestId: p.requestId as string,
				requestedKeys: json<string[]>(p.requestedKeys), createdAt: json<number>(p.createdAt),
				entryCounts: new Map(Object.entries(json<Record<string, number | null>>(p.counts))),
				...(p.voice ? { responseTransport: 'voice' as const } : {}),
			}),
		};
	} catch (error) {
		return { kind: 'error' as const, message: (error as Error).message };
	}
}

function planSelectedKeys(p: Payload): ResponseKeyPlan[] {
	const plan: ResponseKeyPlan[] = [];
	for (const key of json<string[]>(p.selectedKeys)) {
		const parts = splitKey(key);
		if (!parts) continue;
		const [appId, itemType] = parts;
		const route = appId === 'memory' ? 'memory' : appId === 'openmates' && itemType === 'memories' ? 'personal_memories' : 'entries';
		plan.push({ key, appId, itemType, route });
	}
	return plan;
}

function responseCategories(p: Payload): ResponseCategory[] {
	const released = json<Array<{ app_id: string; item_key: string }>>(p.released);
	return json<Array<{ appId: string; itemType: string }>>(p.categories).map((cat) => ({
		appId: cat.appId, itemType: cat.itemType,
		entryCount: released.filter((m) => m.app_id === cat.appId && m.item_key === cat.itemType).length,
	}));
}

function confirmOutcome(p: Payload): ConfirmOutcome {
	if ((p.releasedCount as number) > 0) return { kind: 'send' };
	const voice = p.voice as boolean;
	return { kind: 'empty', sendEmpty: voice, saveRejected: voice && (p.hasMessageId as boolean) };
}

function responseContent(p: Payload): string {
	const categories = json<ResponseCategory[] | null>(p.categories) ?? undefined;
	return JSON.stringify({
		type: 'app_settings_memories_response', user_message_id: p.userMessageId, action: p.action,
		categories: p.action === 'included' ? categories : undefined,
	});
}

function planPrivacyEntry(p: Payload): PrivacyEntryPlan {
	const data = json<Record<string, unknown> | null>(p.data);
	const defaults = json<Record<string, boolean>>(p.defaultCategories);
	const known = ['pii_detection_settings', 'location_settings', 'personal_data_entry'].includes(p.itemType as string);
	if (known && (data === null || typeof data !== 'object')) throw new Error('protocol');
	if (p.itemType === 'pii_detection_settings') {
		const categories = data!.categories && typeof data!.categories === 'object' ? data!.categories as Record<string, unknown> : {};
		return { kind: 'pii', masterEnabled: data!.masterEnabled ?? true, enhancedEnabled: data!.enhancedEnabled ?? true, categories: { ...defaults, ...categories } };
	}
	if (p.itemType === 'location_settings') return { kind: 'location', impreciseByDefault: data!.impreciseByDefault ?? true };
	if (p.itemType === 'personal_data_entry') {
		const plan: PrivacyEntryPlan = {
			kind: 'personal', type: data!.type || 'custom', title: data!.title || '', textToHide: data!.textToHide || '',
			replaceWith: data!.replaceWith || '', enabled: data!.enabled ?? true,
		};
		if (data!.addressLines !== undefined) plan.addressLines = data!.addressLines;
		return plan;
	}
	return { kind: 'other' };
}

const OPS: Record<string, (p: Payload) => unknown> = {
	categoryPlan, requestAnswered, buildRequestMessage, planSelectedKeys, responseCategories, confirmOutcome,
	responseContent, planPrivacyEntry,
	selectEntryIds: (p) => {
		const selection = json<string[] | null>(p.selection);
		return json<string[]>(p.entryIds).filter((id) => selection === null || selection.includes(id));
	},
};

export async function settingsCall<K extends keyof SettingsUnitProtocol & string>(
	op: K, payload: SettingsUnitProtocol[K]['request'],
): Promise<SettingsUnitProtocol[K]['response']> {
	rustSettingsStats.calls++;
	rustSettingsStats.ops[op] = (rustSettingsStats.ops[op] ?? 0) + 1;
	const handler = OPS[op];
	if (!handler) {
		const real = await vi.importActual<typeof import('../settings/settingsClient')>('../settings/settingsClient');
		return real.settingsCall(op, payload);
	}
	try {
		return handler(payload as unknown as Payload) as SettingsUnitProtocol[K]['response'];
	} catch (error) {
		rustSettingsStats.failures++;
		throw error;
	}
}
