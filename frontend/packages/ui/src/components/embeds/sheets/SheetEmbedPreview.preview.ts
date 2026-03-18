/**
 * Preview mock data for SheetEmbedPreview.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/sheets/SheetEmbedPreview
 */

const teamDirectoryTable = `| Name | Role | Department | Start Date |
|------|------|------------|------------|
| Alice Johnson | Senior Engineer | Engineering | 2023-01-15 |
| Bob Smith | Product Manager | Product | 2022-06-01 |
| Carol Williams | Designer | Design | 2024-03-10 |
| David Brown | DevOps Lead | Engineering | 2021-11-20 |
| Eva Martinez | QA Engineer | Engineering | 2023-08-05 |`;

// Real 8-column sales data so the "largeTable" variant exercises wide-table column capping
const salesReportTable = `| Region | Product | Q1 | Q2 | Q3 | Q4 | Total | Growth |
|--------|---------|----|----|----|----|-------|--------|
| North | Widget A | 12400 | 15800 | 18200 | 21500 | 67900 | +14% |
| North | Widget B | 8900 | 9400 | 11200 | 13600 | 43100 | +18% |
| South | Widget A | 9200 | 10500 | 12800 | 15400 | 47900 | +22% |
| South | Widget B | 6700 | 7200 | 8900 | 10100 | 32900 | +12% |
| East | Widget A | 14200 | 16700 | 19400 | 23100 | 73400 | +8% |
| East | Widget B | 10400 | 11800 | 13200 | 15900 | 51300 | +16% |
| West | Widget A | 11600 | 13200 | 15700 | 18900 | 59400 | +20% |
| West | Widget B | 7800 | 8600 | 10200 | 12400 | 39000 | +11% |`;

// Narrow columns — tests that short-content tables fill the card width
const budgetTable = `| Category | Budget | Spent | Remaining |
|----------|--------|-------|-----------|
| Marketing | $50,000 | $32,400 | $17,600 |
| Engineering | $120,000 | $98,750 | $21,250 |
| Design | $35,000 | $28,100 | $6,900 |
| Sales | $80,000 | $71,200 | $8,800 |`;

// Two wide-text columns — tests that long content gets sensible max-width
const feedbackTable = `| Reviewer | Score | Summary |
|----------|-------|---------|
| Alice Johnson | 9/10 | Outstanding performance this quarter, great leadership |
| Bob Smith | 7/10 | Solid delivery, could improve cross-team communication |
| Carol Williams | 8/10 | Excellent design work, very attentive to user feedback |
| David Brown | 9/10 | Reliable and proactive, keeps infrastructure running smoothly |`;

/** Default props — shows a finished sheet/table embed card */
const defaultProps = {
	id: 'preview-sheet-1',
	title: 'Team Directory',
	rowCount: 5,
	colCount: 4,
	status: 'finished' as const,
	tableContent: teamDirectoryTable,
	isMobile: false,
	onFullscreen: () => {}
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

	/** Wide table (8 cols) — exercises column capping: shows readable columns + "+N" indicator */
	largeTable: {
		id: 'preview-sheet-large',
		title: 'Sales Report Q4 2025',
		rowCount: 150,
		colCount: 8,
		status: 'finished' as const,
		tableContent: salesReportTable,
		isMobile: false
	},

	/** Budget table — narrow even columns, tests min-width floor */
	budget: {
		id: 'preview-sheet-budget',
		title: 'Q4 Budget Overview',
		rowCount: 4,
		colCount: 4,
		status: 'finished' as const,
		tableContent: budgetTable,
		isMobile: false
	},

	/** Long-text columns — tests max-width cap + ellipsis */
	feedback: {
		id: 'preview-sheet-feedback',
		title: 'Performance Reviews',
		rowCount: 4,
		colCount: 3,
		status: 'finished' as const,
		tableContent: feedbackTable,
		isMobile: false
	},

	/** Mobile view */
	mobile: {
		...defaultProps,
		id: 'preview-sheet-mobile',
		isMobile: true
	},

	/** Mobile wide table */
	mobileWide: {
		id: 'preview-sheet-mobile-wide',
		title: 'Sales Report Q4 2025',
		rowCount: 8,
		colCount: 8,
		status: 'finished' as const,
		tableContent: salesReportTable,
		isMobile: true
	}
};
