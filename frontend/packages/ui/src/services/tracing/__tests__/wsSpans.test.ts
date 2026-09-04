/**
 * Contract tests for active WebSocket trace propagation.
 * Verifies that transport sends run inside an active span, record the trace for
 * issue correlation, and end the span even when the send callback fails.
 * Contract: architecture.ai-request-observability@1.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SpanStatusCode } from '@opentelemetry/api';

const mocks = vi.hoisted(() => {
	const span = {
		spanContext: vi.fn(() => ({ traceId: '1234567890abcdef1234567890abcdef' })),
		setStatus: vi.fn(),
		end: vi.fn()
	};
	return {
		span,
		startActiveSpan: vi.fn(async (_name: string, callback: (activeSpan: unknown) => unknown) => callback(span)),
		startSpan: vi.fn(() => span)
	};
});

vi.mock('../setup', () => ({
	getTracer: () => ({
		startActiveSpan: mocks.startActiveSpan,
		startSpan: mocks.startSpan
	})
}));

import { getRecentTraceIds, withActiveWsSpan } from '../wsSpans';

describe('withActiveWsSpan', () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	// contract-test: direct surface=gui.web assertions=ai-request-observability.propagation.complete
	it('runs the send in an active span and records its trace ID', async () => {
		const send = vi.fn(async () => 'sent');

		await expect(withActiveWsSpan('send.chat_message_added', send)).resolves.toBe('sent');

		expect(mocks.startActiveSpan).toHaveBeenCalledWith(
			'ws.send.chat_message_added',
			expect.any(Function)
		);
		expect(send).toHaveBeenCalledOnce();
		expect(mocks.span.end).toHaveBeenCalledOnce();
		expect(getRecentTraceIds()).toContain('1234567890abcdef1234567890abcdef');
	});

	// contract-test: supporting surface=gui.web assertions=ai-request-observability.propagation.complete
	it('ends the span when the send fails', async () => {
		const send = vi.fn(async () => {
			throw new Error('send failed');
		});

		await expect(withActiveWsSpan('send.chat_message_added', send)).rejects.toThrow('send failed');
		expect(mocks.span.setStatus).toHaveBeenCalledWith({ code: SpanStatusCode.ERROR });
		expect(mocks.span.end).toHaveBeenCalledOnce();
	});
});
