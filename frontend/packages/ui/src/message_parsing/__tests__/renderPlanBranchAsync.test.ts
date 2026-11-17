// Flag-on render plan branch: a reset (another chat view torn down, a chat
// reloaded) while a plan is in flight must not leave the message empty.
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../data/modelsMetadata', () => ({ modelsMetadata: [] }));
vi.mock('../../data/matesMetadata', () => ({ matesMetadata: [] }));
vi.mock('../../data/providersMetadata', () => ({ providersMetadata: {} }));
vi.mock('../../stores/appSettingsMemoriesStore', () => ({
	appSettingsMemoriesStore: { subscribe: () => () => undefined },
}));
vi.mock('../../stores/appSkillsStore', () => ({
	appSkillsStore: { apps: {}, subscribe: () => () => undefined },
}));

const OPTIONS = { phase: 'streaming', chatId: 'c1' } as const;

async function loadFlagOnBranch(planFor: (markdown: string, call: number) => Promise<unknown>) {
	vi.stubEnv('VITE_OPENMATES_RUST_CORE', '1');
	vi.resetModules();
	let calls = 0;
	vi.doMock('../../services/rustCore/parse/rustAssistantRenderPlan', () => ({
		createAssistantRenderPlanRust: (markdown: string) => planFor(markdown, ++calls),
	}));
	const branch = await import('../../services/rustCore/parse/renderPlanBranch');
	const ready: string[] = [];
	branch.onRenderPlanReady((id) => ready.push(id));
	return { branch, ready, calls: () => calls };
}

afterEach(() => {
	vi.unstubAllEnvs();
	vi.doUnmock('../../services/rustCore/parse/rustAssistantRenderPlan');
});

describe('renderPlanBranch (flag on)', () => {
	// contract-test: direct surface=gui.web assertions=chats.rendering.assistant-document-convergence
	it('asks the page to remap when a reset lands while the plan resolves, and the remap gets the plan', async () => {
		let release: () => void = () => undefined;
		const gate = new Promise<void>((resolve) => { release = resolve; });
		const { branch, ready, calls } = await loadFlagOnBranch(async (markdown, call) => {
			if (call === 1) await gate;
			return { blocks: [markdown] };
		});
		expect(branch.renderPlansAreAsync()).toBe(true);
		const plans = new Map();
		expect(branch.resolveAssistantRenderPlan('m3', 'long reply', OPTIONS, plans)).toBeNull();
		await vi.waitFor(() => expect(calls()).toBe(1));

		branch.resetRenderPlanState();
		release();

		await vi.waitFor(() => expect(ready).toEqual(['m3']));
		expect(plans.has('m3')).toBe(false);
		// The page remaps the message: a fresh request in the new generation resolves.
		expect(branch.resolveAssistantRenderPlan('m3', 'long reply', OPTIONS, plans)).toBeNull();
		await vi.waitFor(() => expect(ready).toEqual(['m3', 'm3']));
		expect(branch.resolveAssistantRenderPlan('m3', 'long reply', OPTIONS, plans)).toEqual({ blocks: ['long reply'] });
	});

	// contract-test: direct surface=gui.web assertions=chats.rendering.assistant-document-convergence
	it('asks the page to remap when a reset lands before the queued request starts', async () => {
		const { branch, ready, calls } = await loadFlagOnBranch(async (markdown) => ({ blocks: [markdown] }));
		const plans = new Map();
		expect(branch.resolveAssistantRenderPlan('m4', 'reply', OPTIONS, plans)).toBeNull();
		branch.resetRenderPlanState();

		await vi.waitFor(() => expect(ready).toEqual(['m4']));
		expect(calls()).toBe(0);
		expect(branch.resolveAssistantRenderPlan('m4', 'reply', OPTIONS, plans)).toBeNull();
		await vi.waitFor(() => expect(ready).toEqual(['m4', 'm4']));
		expect(plans.get('m4')).toEqual({ blocks: ['reply'] });
	});
});
