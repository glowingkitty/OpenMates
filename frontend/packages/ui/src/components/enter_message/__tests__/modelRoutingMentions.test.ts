/**
 * Contract tests for composer model mention resolution.
 * Exact model and alias mentions must become one stable provider/model choice.
 * The message input uses the same resolver before persisting the selection.
 * Contract: feature.ai-model-routing@1.
 */

import { describe, expect, it } from 'vitest';
import {
    resolveModelAliasSelection,
    resolveModelMentionSelection,
    type ModelMentionResult,
} from '../services/mentionSearchService';
import { canonicalizeAiModelSelection, isAiModelSelectionUsable } from '../../../utils/aiModelSelection';

const EXACT_MODEL_RESULT: ModelMentionResult = {
    id: 'claude-fable-5',
    type: 'model',
    displayName: 'Claude Fable 5',
    mentionDisplayName: 'Claude Fable 5',
    subtitle: 'Anthropic',
    icon: '',
    mentionSyntax: '@ai-model:claude-fable-5:anthropic',
    searchTerms: ['claude', 'fable'],
    providerId: 'anthropic',
    providerName: 'Anthropic',
    tier: 'premium',
};

describe('composer model mention routing', () => {
    // contract-test: direct surface=gui.web assertions=ai-model-routing.composer.mention-to-exact-selection
    it('keeps an exact model mention as one provider/model selection', () => {
        expect(resolveModelMentionSelection(EXACT_MODEL_RESULT)).toBe('anthropic/claude-fable-5');
    });

    // contract-test: direct surface=gui.web assertions=ai-model-routing.composer.mention-to-exact-selection
    it('resolves best and fast aliases to concrete provider/model selections', () => {
        expect(resolveModelAliasSelection('best')).toBe('openai/gpt-6-astra');
        expect(resolveModelAliasSelection('fast')).toBe('alibaba/qwen3-235b-a22b-2507');
    });

    // contract-test: supporting surface=gui.web assertions=ai-model-routing.composer.mention-to-exact-selection
    it('rejects an unknown symbolic alias', () => {
        expect(resolveModelAliasSelection('unknown')).toBeNull();
    });

    // contract-test: direct surface=gui.web assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope,ai-model-routing.precedence.chat-over-tier-over-auto
    it('normalizes deployed server-prefixed values to stable model-provider identity', () => {
        expect(canonicalizeAiModelSelection('cerebras/qwen3-235b-a22b-2507')).toBe(
            'alibaba/qwen3-235b-a22b-2507',
        );
    });

    // contract-test: direct surface=gui.web assertions=ai-model-routing.unavailable.notify-reset-auto
    it('requires at least one enabled healthy hosting route', () => {
        const selection = 'alibaba/qwen3-235b-a22b-2507';
        expect(isAiModelSelectionUsable(selection, {}, (serverId) => serverId === 'cerebras')).toBe(true);
        expect(isAiModelSelectionUsable(
            selection,
            { disabledServers: { 'qwen3-235b-a22b-2507': ['cerebras'] } },
            (serverId) => serverId === 'cerebras',
        )).toBe(false);
    });
});
