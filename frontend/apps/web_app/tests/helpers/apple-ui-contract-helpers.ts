/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Rendered web UI contract helpers for Apple parity tests.
 * Captures stable DOM/test-id structure and normalized computed styles from the
 * browser. Generated artifacts are runtime evidence; promoted fixtures live in
 * apple/OpenMatesUITests/Fixtures/WebUIContracts/.
 * Architecture context: docs/specs/apple-ui-contracts/spec.yml
 */
export {};

const fs = require('fs');
const path = require('path');
const { expect } = require('@playwright/test');

const CONTRACT_SCHEMA_VERSION = 1;
const CONTRACT_ARTIFACT_DIR = path.resolve(process.cwd(), 'test-results', 'apple-ui-contracts');

type ContractSeverity = 'fail' | 'warn';

type ContractElementDefinition = {
	testId: string;
	semanticId?: string;
	severity?: ContractSeverity;
	required?: boolean;
};

type ContractStateDefinition = {
	id: string;
	description: string;
	elements: ContractElementDefinition[];
};

const STYLE_PROPERTIES = [
	'display',
	'position',
	'width',
	'min-width',
	'max-width',
	'height',
	'min-height',
	'align-items',
	'justify-content',
	'gap',
	'margin-top',
	'margin-right',
	'margin-bottom',
	'margin-left',
	'padding-top',
	'padding-right',
	'padding-bottom',
	'padding-left',
	'border-radius',
	'background-color',
	'color',
	'font-family',
	'font-size',
	'font-weight',
	'line-height',
	'box-shadow',
	'opacity'
];

const COMPOSER_EMBED_STYLE_PROPERTIES = [
	'display',
	'position',
	'width',
	'min-width',
	'max-width',
	'height',
	'min-height',
	'margin-top',
	'margin-right',
	'margin-bottom',
	'margin-left',
	'padding-top',
	'padding-right',
	'padding-bottom',
	'padding-left',
	'border-radius',
	'background-color',
	'box-shadow',
	'overflow',
	'vertical-align'
];

async function waitForStableBox(page: any, locator: any): Promise<void> {
	await expect(locator).toBeVisible({ timeout: 20000 });
	let previous = await locator.boundingBox();
	for (let attempt = 0; attempt < 5; attempt++) {
		await page.waitForTimeout(100);
		const current = await locator.boundingBox();
		if (
			previous && current &&
			Math.abs(previous.x - current.x) < 0.5 &&
			Math.abs(previous.y - current.y) < 0.5 &&
			Math.abs(previous.width - current.width) < 0.5 &&
			Math.abs(previous.height - current.height) < 0.5
		) {
			return;
		}
		previous = current;
	}
}

function roundNumber(value: number | undefined): number | null {
	if (typeof value !== 'number' || Number.isNaN(value)) return null;
	return Math.round(value * 100) / 100;
}

async function captureElement(page: any, definition: ContractElementDefinition): Promise<any> {
	const locator = page.getByTestId(definition.testId).first();
	if (definition.required !== false) {
		await waitForStableBox(page, locator);
	}

	const exists = await locator.count().then((count: number) => count > 0).catch(() => false);
	if (!exists) {
		return {
			semanticId: definition.semanticId ?? definition.testId,
			testId: definition.testId,
			required: definition.required !== false,
			severity: definition.severity ?? 'fail',
			exists: false,
			structure: { childTestIds: [] },
			computedStyle: {},
			boundingBox: null
		};
	}

	const box = await locator.boundingBox();
	const data = await locator.evaluate((element: HTMLElement, styleProperties: string[]) => {
		const computed = window.getComputedStyle(element);
		const style: Record<string, string> = {};
		for (const property of styleProperties) {
			style[property] = computed.getPropertyValue(property);
		}
		const childTestIds = Array.from(element.querySelectorAll('[data-testid]'))
			.map((child) => child.getAttribute('data-testid'))
			.filter((value): value is string => Boolean(value));
		return {
			tagName: element.tagName.toLowerCase(),
			role: element.getAttribute('role'),
			ariaLabel: element.getAttribute('aria-label'),
			classList: Array.from(element.classList).sort(),
			childTestIds,
			computedStyle: style
		};
	}, STYLE_PROPERTIES);

	return {
		semanticId: definition.semanticId ?? definition.testId,
		testId: definition.testId,
		required: definition.required !== false,
		severity: definition.severity ?? 'fail',
		exists: true,
		structure: {
			tagName: data.tagName,
			role: data.role,
			ariaLabel: data.ariaLabel,
			classList: data.classList,
			childTestIds: data.childTestIds
		},
		computedStyle: data.computedStyle,
		boundingBox: box ? {
			x: roundNumber(box.x),
			y: roundNumber(box.y),
			width: roundNumber(box.width),
			height: roundNumber(box.height)
		} : null
	};
}

async function captureContractState(page: any, state: ContractStateDefinition): Promise<any> {
	const elements = [];
	for (const element of state.elements) {
		elements.push(await captureElement(page, element));
	}
	return {
		id: state.id,
		description: state.description,
		elements
	};
}

function createContract(surface: string, viewport: { width: number; height: number }, states: any[]): any {
	return {
		schemaVersion: CONTRACT_SCHEMA_VERSION,
		surface,
		generatedAt: new Date().toISOString(),
		viewport,
		states
	};
}

function writeContractArtifact(contract: any, filename = `${contract.surface}.json`): string {
	fs.mkdirSync(CONTRACT_ARTIFACT_DIR, { recursive: true });
	const outputPath = path.join(CONTRACT_ARTIFACT_DIR, filename);
	fs.writeFileSync(outputPath, `${JSON.stringify(contract, null, 2)}\n`, 'utf8');
	return outputPath;
}

async function captureComposerEmbedContract(
	page: any,
	options: { id: string; embedType?: string; screenshot?: boolean }
): Promise<any> {
	const editor = page.getByTestId('message-editor').last();
	const wrapperSelector = options.embedType
		? `[data-testid="embed-full-width-wrapper"][data-embed-type="${options.embedType}"]`
		: '[data-testid="embed-full-width-wrapper"]';
	const wrapper = editor.locator(wrapperSelector).first();
	await waitForStableBox(page, wrapper);

	const capture = await wrapper.evaluate((element: HTMLElement, styleProperties: string[]) => {
		const editorElement = element.closest('[data-testid="message-editor"]');
		const messageField = element.closest('[data-testid="message-field"]');
		const container = Array.from(element.children).find((child): child is HTMLElement => {
			return child instanceof HTMLElement && child.dataset.embedType === element.dataset.embedType;
		});
		const captureStyle = (target: HTMLElement | null) => {
			if (!target) return null;
			const computed = window.getComputedStyle(target);
			const style: Record<string, string> = {};
			for (const property of styleProperties) {
				style[property] = computed.getPropertyValue(property);
			}
			return style;
		};
		const rectToObject = (rect: DOMRect) => ({
			x: Math.round(rect.x * 100) / 100,
			y: Math.round(rect.y * 100) / 100,
			width: Math.round(rect.width * 100) / 100,
			height: Math.round(rect.height * 100) / 100
		});

		return {
			embedType: element.dataset.embedType ?? null,
			insideMessageEditor: Boolean(editorElement),
			insideMessageField: Boolean(messageField),
			wrapper: {
				tagName: element.tagName.toLowerCase(),
				classList: Array.from(element.classList).sort(),
				style: captureStyle(element),
				boundingBox: rectToObject(element.getBoundingClientRect())
			},
			container: container ? {
				tagName: container.tagName.toLowerCase(),
				classList: Array.from(container.classList).sort(),
				style: captureStyle(container),
				boundingBox: rectToObject(container.getBoundingClientRect())
			} : null,
			editor: editorElement ? {
				classList: Array.from(editorElement.classList).sort(),
				boundingBox: rectToObject(editorElement.getBoundingClientRect())
			} : null,
			messageField: messageField ? {
				classList: Array.from(messageField.classList).sort(),
				boundingBox: rectToObject(messageField.getBoundingClientRect())
			} : null
		};
	}, COMPOSER_EMBED_STYLE_PROPERTIES);

	expect(capture.insideMessageEditor, `${options.id}: embed must be inside message-editor`).toBe(true);
	expect(capture.insideMessageField, `${options.id}: embed must be inside message-field`).toBe(true);
	expect(capture.container, `${options.id}: embed container`).not.toBeNull();

	const contract = createContract('composer-pending-embed', await page.viewportSize(), [
		{
			id: options.id,
			description: 'Pending composer embed rendered inside the TipTap message editor',
			capture
		}
	]);
	const outputPath = writeContractArtifact(contract, `${options.id}.json`);
	console.log(`[APPLE_UI_CONTRACT] Saved composer pending embed contract to ${outputPath}`);

	if (options.screenshot) {
		const screenshotPath = path.join(CONTRACT_ARTIFACT_DIR, `${options.id}.png`);
		await page.getByTestId('message-field').last().screenshot({ path: screenshotPath });
		console.log(`[APPLE_UI_CONTRACT] Saved composer pending embed screenshot to ${screenshotPath}`);
	}

	return contract;
}

module.exports = {
	captureContractState,
	captureComposerEmbedContract,
	createContract,
	writeContractArtifact
};
