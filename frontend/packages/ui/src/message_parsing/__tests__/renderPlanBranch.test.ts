// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest';

vi.mock('../../data/modelsMetadata', () => ({ modelsMetadata: [] }));
vi.mock('../../data/matesMetadata', () => ({ matesMetadata: [] }));
vi.mock('../../data/providersMetadata', () => ({ providersMetadata: {} }));
vi.mock('../../stores/appSettingsMemoriesStore', () => ({
	appSettingsMemoriesStore: { subscribe: () => () => undefined },
}));
vi.mock('../../stores/appSkillsStore', () => ({
	appSkillsStore: { apps: {}, subscribe: () => () => undefined },
}));
import {
	createAssistantRenderPlan,
	type AssistantRenderPlan,
} from '../streamingMessageBlocks';
import {
	renderPlansAreAsync,
	resolveAssistantRenderPlan,
} from '../../services/rustCore/parse/renderPlanBranch';

describe('renderPlanBranch (flag off)', () => {
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('is synchronous and equals createAssistantRenderPlan, chaining previous plans', () => {
		expect(renderPlansAreAsync()).toBe(false);
		const plans = new Map<string, AssistantRenderPlan>();
		let reference: AssistantRenderPlan | undefined;
		for (const markdown of ['Hello', 'Hello\n\nWorld', 'Hello\n\nWorld\n\n- a\n- b']) {
			const branched = resolveAssistantRenderPlan('m1', markdown, { phase: 'streaming', chatId: 'c1' }, plans);
			reference = createAssistantRenderPlan(markdown, { phase: 'streaming', chatId: 'c1', previous: reference });
			expect(branched).toEqual(reference);
			expect(plans.get('m1')).toBe(branched);
		}
	});
});
