// frontend/packages/ui/src/components/embeds/code/__tests__/notebookContent.test.ts
//
// Regression coverage for Jupyter notebook content normalization.
// Notebook embeds must render as readable cells instead of raw nbformat JSON,
// and non-Python kernels must remain read-only for the v1 execution boundary.
// Architecture: docs/specs/code-notebook-embed/spec.yml

import { describe, expect, it } from 'vitest';

import { normalizeNotebookContent, renderNotebookText } from '../notebookContent';

const pythonNotebook = {
	nbformat: 4,
	nbformat_minor: 5,
	metadata: {
		kernelspec: { name: 'python3', language: 'python', display_name: 'Python 3' },
		language_info: { name: 'python' }
	},
	cells: [
		{
			cell_type: 'markdown',
			metadata: {},
			source: ['# Forecast notebook\n', 'Plan a bike ride from weather data.']
		},
		{
			cell_type: 'code',
			metadata: {},
			execution_count: null,
			outputs: [],
			source: 'print("notebook smoke")\n'
		}
	]
};

describe('notebookContent helpers', () => {
	it('normalizes Python nbformat content with cell counts and filename metadata', () => {
		const normalized = normalizeNotebookContent({
			type: 'notebook',
			filename: 'weather.ipynb',
			notebook: pythonNotebook
		});

		expect(normalized.filename).toBe('weather.ipynb');
		expect(normalized.language).toBe('python');
		expect(normalized.isPython).toBe(true);
		expect(normalized.cellCount).toBe(2);
		expect(normalized.markdownCellCount).toBe(1);
		expect(normalized.codeCellCount).toBe(1);
	});

	it('renders notebook text as cells instead of raw JSON', () => {
		const text = renderNotebookText({
			filename: 'weather.ipynb',
			notebook: pythonNotebook
		});

		expect(text).toContain('**weather.ipynb**');
		expect(text).toContain('2 cells, Notebook');
		expect(text).toContain('Cell 1 (markdown)');
		expect(text).toContain('Forecast notebook');
		expect(text).toContain('Cell 2 (code)');
		expect(text).toContain('print("notebook smoke")');
		expect(text).not.toContain('"nbformat"');
	});

	it('marks non-Python notebooks as read-only for v1 execution', () => {
		const normalized = normalizeNotebookContent({
			filename: 'analysis.ipynb',
			notebook: {
				...pythonNotebook,
				metadata: {
					kernelspec: { name: 'ir', language: 'R', display_name: 'R' },
					language_info: { name: 'R' }
				}
			}
		});

		expect(normalized.language).toBe('r');
		expect(normalized.isPython).toBe(false);
	});
});
