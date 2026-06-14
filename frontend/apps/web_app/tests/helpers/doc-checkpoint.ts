/**
 * Documentation checkpoint helper for Playwright user-guide flows.
 *
 * Links real E2E steps to user-guide sections so docs can be validated against
 * tested behavior. Normal runs write checkpoint manifests to test artifacts;
 * repository screenshots are only updated with UPDATE_DOC_SCREENSHOTS=1.
 *
 * Architecture: docs/contributing/guides/docs-writing-guidelines.md
 * Validator: scripts/docs_guide_verify.py
 */

export {};

import * as fs from 'fs';
import * as path from 'path';

type DocCheckpointOptions = {
	id: string;
	guide: string;
	title: string;
	screenshot?: string;
};

type PageLike = {
	screenshot: (options: Record<string, unknown>) => Promise<unknown>;
};

type DocAssertion = () => unknown | Promise<unknown>;

const CHECKPOINT_ARTIFACT_DIR = path.resolve(process.cwd(), 'artifacts', 'doc-checkpoints');
const SHOULD_UPDATE_DOC_SCREENSHOTS = process.env.UPDATE_DOC_SCREENSHOTS === '1';

async function docCheckpoint(page: PageLike, options: DocCheckpointOptions): Promise<void> {
	fs.mkdirSync(CHECKPOINT_ARTIFACT_DIR, { recursive: true });

	const artifactScreenshot = path.join(CHECKPOINT_ARTIFACT_DIR, `${options.id}.jpg`);
	await page.screenshot({ path: artifactScreenshot, type: 'jpeg', quality: 85, fullPage: false });

	if (SHOULD_UPDATE_DOC_SCREENSHOTS && options.screenshot) {
		const repoScreenshot = path.resolve(process.cwd(), options.screenshot);
		fs.mkdirSync(path.dirname(repoScreenshot), { recursive: true });
		fs.copyFileSync(artifactScreenshot, repoScreenshot);
	}

	const manifestPath = path.join(CHECKPOINT_ARTIFACT_DIR, `${options.id}.json`);
	fs.writeFileSync(
		manifestPath,
		JSON.stringify(
			{
				...options,
				artifactScreenshot,
				repoScreenshotUpdated: SHOULD_UPDATE_DOC_SCREENSHOTS && Boolean(options.screenshot),
				timestamp: new Date().toISOString()
			},
			null,
			2
		),
		'utf8'
	);
}

async function docAssert(id: string, assertion: DocAssertion): Promise<unknown> {
	try {
		return await assertion();
	} catch (error) {
		if (error instanceof Error) {
			error.message = `[doc-assert:${id}] ${error.message}`;
		}
		throw error;
	}
}

module.exports = { docAssert, docCheckpoint };
