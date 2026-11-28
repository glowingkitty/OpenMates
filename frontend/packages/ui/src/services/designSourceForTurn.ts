/** UI glue for the shared core's explicit Design attachment and private context. */
import { whenSharedRustCore } from './rustCore/host/sharedCoreRegistry';
import { rustEmbedData } from './rustCore/embeds/embedDataClient';

async function selectedDesign(markdown: string) {
	if (import.meta.env.VITE_OPENMATES_RUST_CORE !== '1' || !markdown.includes('"design-document"')) return null;
	await whenSharedRustCore({ timeoutMs: 10_000 });
	return await rustEmbedData()?.designTurnReference(markdown) ?? null;
}

export async function withoutDesignReference(markdown: string): Promise<string> {
	return (await selectedDesign(markdown))?.text ?? markdown;
}

export async function collectDesignSource(markdown: string, chatId: string) {
	const selected = await selectedDesign(markdown);
	if (!selected) return null;
	const { resolveEmbed } = await import('./embedResolver');
	const head = await resolveEmbed(selected.embedId, { chatId });
	if (head?.type !== 'design-document' || head.status !== 'finished') return null;
	const version = head.version_number ?? 1;
	if (typeof version !== 'number') return null;
	return await rustEmbedData()?.designSourceContext(head.content, selected.embedId, version) ?? null;
}
