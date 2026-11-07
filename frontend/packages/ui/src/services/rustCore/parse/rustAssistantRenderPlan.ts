/**
 * Flag-on (VITE_OPENMATES_RUST_CORE) assistant render plan: the shared Rust
 * `parse` unit decides blocks, ids and operations; the page only compiles the
 * markdown of blocks Rust marked as new (compileAssistantDisplayMessage stays on
 * the page: it calls parse_message and the TipTap embed preprocessing). There is
 * no TypeScript fallback for the block decisions: a refused call rejects.
 *
 * Callers must be async; the synchronous createAssistantRenderPlan remains the
 * flag-off implementation (message_parsing/streamingMessageBlocks.ts).
 */
import {
	compileAssistantDisplayMessage,
} from '../../../message_parsing/streamingMessageCompiler';
import type {
	AssistantRenderBlock,
	AssistantRenderPlan,
	CreateAssistantRenderPlanOptions,
} from '../../../message_parsing/streamingMessageBlocks';
import { parseCall } from './parseClient';
import type { ParsePrevious } from './parseProtocol';

function compile(markdown: string, options: CreateAssistantRenderPlanOptions): Record<string, unknown> {
	return compileAssistantDisplayMessage(markdown, { phase: options.phase, role: 'assistant', chatId: options.chatId }) as Record<string, unknown>;
}

function summarize(previous: AssistantRenderPlan | undefined): ParsePrevious | null {
	if (!previous) return null;
	return {
		phase: previous.phase,
		committed: previous.committed.map((b) => ({ id: b.id, markdown: b.markdown })),
		tail: previous.tail ? { id: previous.tail.id, markdown: previous.tail.markdown } : null,
	};
}

export async function createAssistantRenderPlanRust(
	markdown: string,
	options: CreateAssistantRenderPlanOptions,
): Promise<AssistantRenderPlan> {
	const { previous } = options;
	const planned = await parseCall('planBlocks', { markdown, phase: options.phase, previous: JSON.stringify(summarize(previous)) });
	const document = compile(markdown, options) as AssistantRenderPlan['document'];
	if (planned.failed && previous) {
		return {
			...previous,
			sourceMarkdown: markdown,
			phase: options.phase,
			document: {
				type: 'doc',
				content: [
					...previous.document.content,
					{ type: 'paragraph', content: [{ type: 'text', text: 'Message update could not be applied safely.' }] },
				],
			},
			operations: planned.operations,
		};
	}
	const committed: AssistantRenderBlock[] = planned.committed.map((block) => {
		const reused = block.reuse === null ? undefined : previous?.committed[block.reuse];
		return { id: block.id, markdown: block.markdown, document: reused ? reused.document : compile(block.markdown, options) };
	});
	const tail = planned.tail === null
		? null
		: { id: 'assistant-tail', markdown: planned.tail, document: compile(planned.tail, options) };
	return {
		sourceMarkdown: markdown,
		phase: options.phase,
		committed,
		tail,
		authoredDocument: document,
		document,
		operations: planned.operations,
	};
}
