// frontend/packages/ui/src/components/__tests__/activeChatUtils.test.ts
// Focused tests for pure ActiveChat helper contracts.
// These helpers are extracted from the large Svelte component so regression
// coverage can assert routing decisions without mounting the full chat UI.
// Keep this file narrow: component rendering belongs in Playwright specs.

import { describe, expect, it } from 'vitest';
import { shouldSkipLegacyAIResponsePersistenceForRecovery } from '../activeChatUtils';

describe('shouldSkipLegacyAIResponsePersistenceForRecovery', () => {
    it('skips legacy persistence for epoch-one recovery completions', () => {
        expect(
            shouldSkipLegacyAIResponsePersistenceForRecovery({
                recovery_job_id: 'job-1',
                recovery_protocol_version: 1,
            }),
        ).toBe(true);
    });

    it('keeps legacy persistence for non-recovery completions', () => {
        expect(shouldSkipLegacyAIResponsePersistenceForRecovery({})).toBe(false);
        expect(
            shouldSkipLegacyAIResponsePersistenceForRecovery({
                recovery_job_id: null,
                recovery_protocol_version: 1,
            }),
        ).toBe(false);
        expect(
            shouldSkipLegacyAIResponsePersistenceForRecovery({
                recovery_job_id: 'job-1',
                recovery_protocol_version: 2,
            }),
        ).toBe(false);
    });
});
