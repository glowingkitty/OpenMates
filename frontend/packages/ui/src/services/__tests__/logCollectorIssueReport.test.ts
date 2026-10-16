import { afterEach, describe, expect, it } from 'vitest';
import { LogCollectorService } from '../logCollector';

describe('issue report log redaction', () => {
	let collector: LogCollectorService | undefined;

	afterEach(() => {
		collector?.destroy();
		collector = undefined;
	});

	// contract-test: supporting surface=gui.web assertions=issue-reporting.logs.authenticated-capture
	it('keeps neighboring entries while masking long quoted strings, visible chat, and share keys', () => {
		collector = new LogCollectorService();
		const visibleChat = 'Search on the web for ‘Berlin weather’';
		console.warn("An unmatched quote ' starts in this entry");
		console.warn('An unmatched quote " starts in this entry');
		console.warn('Another entry ' + 'x'.repeat(120));
		console.warn('[ReportIssueRedactionProbe]', visibleChat, 'https://app.example/share/chat/example#key=secret-report-share-key-material');
		const longQuotedSecret = `s ${'word '.repeat(25)}`;
		console.warn('Single line secret', `'${longQuotedSecret}'`);
		console.warn('Double quoted secret', `"${longQuotedSecret}"`);

		const report = collector.getIssueReportLogsAsText(100, [visibleChat]);
		expect(report).toContain('[ReportIssueRedactionProbe]');
		expect(report).toContain('[CHAT-CONTENT-REDACTED]');
		expect(report).toContain('[SHARE-KEY-REDACTED]');
		expect(report).toContain('[LONG-STRING-REDACTED]');
		expect(report).not.toContain(visibleChat);
		expect(report).not.toContain('secret-report-share-key-material');
		expect(report).not.toContain(longQuotedSecret);
	});
});
