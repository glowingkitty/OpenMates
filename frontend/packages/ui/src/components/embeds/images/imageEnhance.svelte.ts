/**
 * View glue for the image fullscreen's Enhance button and version restore
 * (`embed-user-edits.enhance.button`, `.edit.next-version`,
 * `.restore.creates-version`; VITE_OPENMATES_RUST_CORE builds only).
 *
 * The Rust core runs Enhance and restore through the shared Worker
 * (services/rustCore/embeds/embedEditSession.ts). This module only picks the
 * save scope from where the fullscreen was opened (chat or Projects workspace),
 * turns core codes into messages and keeps the button state; after a save the
 * caller reloads the embed's head so the fullscreen and the chat card show it.
 */
import type { EmbedEditScope } from '../../../services/rustCore/embeds/embedEditProtocol';

/** Where the fullscreen was opened. */
export interface ImageEditPlace {
	/** Chat the image belongs to (null outside a chat). */
	chatId: string | null;
	/** Team of that chat, when it is a Team chat. */
	chatTeamId: string | null;
	/** Projects workspace: the Project and its Team, if any. */
	projectId?: string | null;
	projectTeamId?: string | null;
	/** Shared, public, example or otherwise read-only view. */
	readOnly: boolean;
}

export type ImageEditAvailability =
	| { kind: 'available'; scope: EmbedEditScope }
	| { kind: 'unavailable'; reason: 'read_only' | 'team' };

/** Project scope from the Projects workspace, chat scope from a chat; Teams and viewers cannot Enhance. */
export function imageEditAvailability(place: ImageEditPlace): ImageEditAvailability {
	if (place.projectId) {
		if (place.readOnly) return { kind: 'unavailable', reason: 'read_only' };
		if (place.projectTeamId) return { kind: 'unavailable', reason: 'team' };
		return { kind: 'available', scope: { kind: 'project', project_id: place.projectId } };
	}
	if (!place.chatId || place.readOnly) return { kind: 'unavailable', reason: 'read_only' };
	if (place.chatTeamId) return { kind: 'unavailable', reason: 'team' };
	return { kind: 'available', scope: { kind: 'chat', chat_id: place.chatId } };
}

/** i18n key of a refused Enhance or restore (the core's stable code). */
export function imageEditErrorKey(code: string | undefined, action: 'enhance' | 'restore'): string {
	switch (code) {
		case 'insufficient_credits': return 'embed_user_edits.enhance_insufficient_credits';
		case 'team_enhance_unavailable': return 'embed_user_edits.enhance_unavailable_team';
		case 'embed_version_conflict': return 'embed_user_edits.version_conflict';
		default: return action === 'enhance' ? 'embed_user_edits.enhance_failed' : 'embed_user_edits.restore_failed';
	}
}

function errorCode(error: unknown): string | undefined {
	const code = (error as { code?: unknown } | null)?.code;
	return typeof code === 'string' ? code : undefined;
}

export interface ImageEnhanceDeps {
	enhance(embedId: string, scope: EmbedEditScope): Promise<{ version: number }>;
	running(embedId: string): Promise<unknown | null>;
	translate(key: string): string;
	/** Reload the embed's head after a save (or a conflict) and show `version` when it is known. */
	reloadHead(version: number | null): Promise<void>;
}

/** Button state of one opened image. `start` is a no-op while a run is going. */
export function createImageEnhance(embedId: () => string | undefined, scope: () => EmbedEditScope | null, deps: ImageEnhanceDeps) {
	let state = $state<'idle' | 'running' | 'failed'>('idle');
	let error = $state<string | undefined>(undefined);

	async function follow(id: string, run: Promise<{ version: number }>): Promise<void> {
		state = 'running';
		error = undefined;
		let saved: { version: number };
		try {
			saved = await run;
		} catch (failure) {
			const code = errorCode(failure);
			console.error('[imageEnhance] Enhance did not save a version:', id, code ?? failure);
			error = deps.translate(imageEditErrorKey(code, 'enhance'));
			state = 'failed';
			// A newer version exists: show it instead of the stale one.
			if (code === 'embed_version_conflict') await deps.reloadHead(null);
			return;
		}
		state = 'idle';
		// The version is saved (and billed): a failed reload is a display problem, never "Enhance failed".
		try {
			await deps.reloadHead(saved.version);
		} catch (failure) {
			console.error('[imageEnhance] Saved version could not be shown yet:', id, saved.version, failure);
		}
	}

	return {
		get state() { return state; },
		get error() { return error; },
		start(): void {
			const id = embedId();
			const target = scope();
			if (!id || !target || state === 'running') return;
			void follow(id, deps.enhance(id, target));
		},
		/** On open: join an Enhance of this image the Worker is still running (e.g. started before a reload). */
		async resume(): Promise<void> {
			const id = embedId();
			const target = scope();
			if (!id || !target || state === 'running') return;
			if (await deps.running(id)) await follow(id, deps.enhance(id, target));
		}
	};
}
