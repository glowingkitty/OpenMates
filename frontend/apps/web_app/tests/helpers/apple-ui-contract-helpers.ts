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
	'align-items',
	'justify-content',
	'gap',
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

module.exports = {
	captureContractState,
	createContract,
	writeContractArtifact
};
