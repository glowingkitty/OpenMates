/**
 * Flag branch for saved generated-image display recovery (ChatMessage.svelte).
 *
 * Flag off (default): returns the previous recoverGeneratedImageDocument promise
 * unchanged (no wrapper await; the Rust branch is statically dead and its
 * dynamic import is eliminated by the build).
 *
 * Flag on (VITE_OPENMATES_RUST_CORE=1): the shared Rust `parse` unit decides
 * which parent embeds are read and assembles the recovered document; the page
 * keeps the awaited embed reads and the caller's cancellation. No TypeScript
 * fallback: a refused call rejects (the caller logs it and shows the original).
 *
 * spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
 */
import { recoverGeneratedImageDocument } from '../../../message_parsing/generatedImageRecovery';
import type { AssistantDocument } from '../../../message_parsing/assistantActivityRuns';

const RUST_PARSE_BUILD: boolean = import.meta.env.VITE_OPENMATES_RUST_CORE === '1';

async function recoverWithRust(
	source: AssistantDocument,
	resolveParent: (id: string) => Promise<Record<string, unknown> | null>,
): Promise<AssistantDocument | null> {
	const { parseCall } = await import('./parseClient');
	const json = JSON.stringify(source);
	const ids = await parseCall('imageRecoveryParents', { source: json });
	if (!ids.length) return null;
	const parents = await Promise.all(ids.map((id) => resolveParent(id)));
	return (await parseCall('recoverGeneratedImages', { source: json, parents: JSON.stringify(parents) })) as AssistantDocument | null;
}

/** Recover display of a saved image answer from its retained authorized parents. */
export function recoverGeneratedImages(
	source: AssistantDocument,
	resolveParent: (id: string) => Promise<Record<string, unknown> | null>,
): Promise<AssistantDocument | null> {
	if (!RUST_PARSE_BUILD) return recoverGeneratedImageDocument(source, resolveParent);
	return recoverWithRust(source, resolveParent);
}
