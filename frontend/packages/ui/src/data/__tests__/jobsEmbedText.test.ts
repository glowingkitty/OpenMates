import { describe, it, expect } from 'vitest';
import { renderJobResult, renderJobsSearch } from '../../components/embeds/jobs/jobsEmbedText';

describe('Jobs detail copy', () => {
	// contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence
	it('retains full source details for one listing while keeping parent summaries bounded', () => {
		const job = { title: 'Product Designer', provider: 'ExampleJobsC', sector: 'Healthcare',
			description: 'Requirements\nAccessible product design.\nBenefits\n30 days annual leave.',
			url: 'https://example.com/fixture', apply_url: 'https://example.com/apply' };
		const detail = renderJobResult(job);
		expect(detail).toContain('Sector: Healthcare');
		expect(detail).toContain(job.description);
		expect(detail).toContain('Source: ExampleJobsC');
		expect(detail).toContain('Apply: https://example.com/apply');
		const parent = renderJobsSearch({ result_count: 1 }, [job]);
		expect(parent).toContain('Product Designer');
		expect(parent).toContain(job.url);
		expect(parent).not.toContain(job.description);
	});
});

