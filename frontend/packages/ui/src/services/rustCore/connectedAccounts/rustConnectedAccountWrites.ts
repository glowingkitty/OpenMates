/**
 * Flag-on (VITE_OPENMATES_RUST_CORE) connected-account write paths: the page
 * adapter for the OAuth handoff row and the CLI transfer command, over the
 * connected-account ops of the shared Rust core Worker's pre-bind `settings`
 * unit. Loaded only through the guarded branches of
 * connectedAccountOAuthService.ts and connectedAccountCliTransfer.ts, which
 * default builds drop.
 *
 * Rust (web_connected_accounts_oauth.rs / _transfer.rs) decides every
 * plaintext, field source and guard. The page keeps the IO and secrets:
 * master-key encryption/decryption, SHA-256, the passcode and AES-GCM
 * transfer encryption, the clock, and the refresh-token bundle, which never
 * enters the Worker. Await order matches the TypeScript services, so the
 * first error thrown is the same; there is no TypeScript fallback.
 */
import type { OAuthHandoffClaimResponse } from '../../connectedAccountOAuthService';
import type { ConnectedAccountCliTransferPayload } from '../../connectedAccountCliTransfer';
import type {
	EncryptedConnectedAccountCreateInput,
	EncryptedConnectedAccountRow
} from '../../connectedAccountStorageService';
import { settingsCall } from '../settings/settingsClient';
import { failure, type DecryptConnectedAccountField } from './rustConnectedAccounts';

type EncryptWithMasterKey = (value: string) => Promise<string | null | undefined>;
type ComputeSha256 = (value: string) => Promise<string>;
type EncryptTransferPayload = (payload: ConnectedAccountCliTransferPayload, passcode: string) => Promise<string>;

export async function rustBuildEncryptedConnectedAccountRow(
	params: { connectedAccountId: string; handoff: OAuthHandoffClaimResponse; capabilitiesOverride?: string[] },
	encrypt: EncryptWithMasterKey,
	sha256: ComputeSha256
): Promise<EncryptedConnectedAccountCreateInput> {
	const hint: unknown = params.handoff.account_hint;
	const bundle: unknown = params.handoff.refresh_token_bundle;
	// Only the bundle's scopes (never its tokens) cross, as JSON text so their key order survives.
	const scopesOf = (owner: unknown) =>
		owner == null ? undefined : JSON.stringify((owner as { scopes?: unknown }).scopes);
	const plan = await settingsCall('oauthRowPlan', {
		input: JSON.stringify({
			connectedAccountId: params.connectedAccountId,
			providerId: params.handoff.provider_id,
			hint,
			capabilitiesOverride: params.capabilitiesOverride,
			hintScopes: scopesOf(hint),
			bundleScopes: scopesOf(bundle),
			bundleNullish: bundle == null
		})
	});
	if (plan.kind === 'error') throw failure(plan);
	const row: Record<string, unknown> = { id: params.connectedAccountId };
	for (const step of plan.steps) {
		if ('hash' in step) {
			row[step.field] = await sha256(step.hash);
			continue;
		}
		const plaintext = 'bundle' in step ? JSON.stringify(params.handoff.refresh_token_bundle) : step.encrypt;
		const encrypted = await encrypt(plaintext);
		if (!encrypted) throw new Error(step.failure);
		row[step.field] = encrypted;
	}
	if (plan.malformed) throw failure({ code: 'malformed' });
	const guard = await settingsCall('storageGuard', { serialized: JSON.stringify(row) });
	if (guard.kind === 'error') throw failure(guard);
	return row as unknown as EncryptedConnectedAccountCreateInput;
}

export async function rustBuildConnectedAccountCliImportCommand(
	params: { row: EncryptedConnectedAccountRow; passcode: string },
	decrypt: DecryptConnectedAccountField,
	encryptPayload: EncryptTransferPayload
): Promise<string> {
	const row = params.row;
	const [providerId, label, capabilities, permissions, directoryHint, refreshTokenBundle] = await Promise.all([
		decrypt(row.encrypted_provider_type, 'encrypted_provider_type'),
		decrypt(row.encrypted_account_label, 'encrypted_account_label'),
		decrypt(row.encrypted_capabilities, 'encrypted_capabilities'),
		decrypt(row.encrypted_app_permissions, 'encrypted_app_permissions'),
		row.encrypted_account_directory_hint
			? decrypt(row.encrypted_account_directory_hint, 'encrypted_account_directory_hint')
			: Promise.resolve(undefined),
		decrypt(row.encrypted_refresh_token_bundle, 'encrypted_refresh_token_bundle')
	]);
	// The bundle stays on the page: only whether it carries a token crosses
	// (a nullish bundle throws the TypeError the TypeScript service throws).
	const token = (refreshTokenBundle as Record<string, unknown>).refresh_token;
	const plan = await settingsCall('transferPlan', {
		input: JSON.stringify({
			facts: { provider: providerId, label, capabilities, permissions, hint: directoryHint },
			refreshTokenPresent: typeof token === 'string' && token !== ''
		})
	});
	if (plan.kind === 'error') throw failure(plan);
	const hint = directoryHint as Record<string, unknown> | undefined;
	const appId = 'value' in plan.app_id
		? plan.app_id.value
		: plan.app_id.from === 'permissions'
			? (permissions as Record<string, unknown>).app_id
			: providerId;
	const payload = {
		version: 1,
		provider_id: providerId,
		app_id: appId,
		label: plan.label === 'hint' ? hint?.label : label,
		...(plan.account_ref ? { account_ref: hint?.account_ref } : {}),
		capabilities: plan.capabilities,
		runtime_modes: plan.runtime_modes === 'hint' ? hint?.runtime_modes : Object.fromEntries(plan.runtime_modes),
		refresh_token_bundle: refreshTokenBundle,
		created_at: new Date().toISOString()
	} as unknown as ConnectedAccountCliTransferPayload;
	const encryptedPayload = await encryptPayload(payload, params.passcode);
	const command = await settingsCall('transferCommand', { payload: encryptedPayload });
	if (command.kind === 'error') throw failure(command);
	return command.command;
}
