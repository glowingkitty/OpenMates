/**
 * Preview mock data for SheetEmbedPreview.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/sheets/SheetEmbedPreview
 */

const sampleTable = `| Name | Role | Department | Start Date |
|------|------|------------|------------|
| Alice Johnson | Senior Engineer | Engineering | 2023-01-15 |
| Bob Smith | Product Manager | Product | 2022-06-01 |
| Carol Williams | Designer | Design | 2024-03-10 |
| David Brown | DevOps Lead | Engineering | 2021-11-20 |
| Eva Martinez | QA Engineer | Engineering | 2023-08-05 |`;

/** Default props — shows a finished sheet/table embed card */
const defaultProps = {
	id: 'preview-sheet-1',
	title: 'Team Directory',
	rowCount: 5,
	colCount: 4,
	status: 'finished' as const,
	tableContent: sampleTable,
	isMobile: false,
	onFullscreen: () => console.log('[Preview] Fullscreen clicked')
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
	/** Processing state — shows loading animation */
	processing: {
		id: 'preview-sheet-processing',
		status: 'processing' as const,
		isMobile: false
	},

	/** Error state */
	error: {
		id: 'preview-sheet-error',
		status: 'error' as const,
		isMobile: false
	},

	/** Large table */
	largeTable: {
		id: 'preview-sheet-large',
		title: 'Sales Report Q4 2025',
		rowCount: 150,
		colCount: 8,
		status: 'finished' as const,
		tableContent: sampleTable,
		isMobile: false
	},

	/** Mobile view */
	mobile: {
		...defaultProps,
		id: 'preview-sheet-mobile',
		isMobile: true
	}
};
