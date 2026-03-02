/**
 * Preview mock data for SheetEmbedFullscreen.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/sheets/SheetEmbedFullscreen
 */

const sampleTable = `| Name | Role | Department | Start Date | Location | Salary |
|------|------|------------|------------|----------|--------|
| Alice Johnson | Senior Engineer | Engineering | 2023-01-15 | Munich | €85,000 |
| Bob Smith | Product Manager | Product | 2022-06-01 | Berlin | €92,000 |
| Carol Williams | Lead Designer | Design | 2024-03-10 | Munich | €78,000 |
| David Brown | DevOps Lead | Engineering | 2021-11-20 | Remote | €88,000 |
| Eva Martinez | QA Engineer | Engineering | 2023-08-05 | Barcelona | €72,000 |
| Frank Lee | Frontend Developer | Engineering | 2024-01-08 | Munich | €76,000 |
| Grace Kim | Data Analyst | Analytics | 2023-05-22 | Berlin | €68,000 |
| Henry Davis | Backend Developer | Engineering | 2022-09-15 | Munich | €82,000 |`;

/** Default props — shows a fullscreen sheet/table view */
const defaultProps = {
	title: 'Team Directory',
	rowCount: 8,
	colCount: 6,
	tableContent: sampleTable,
	onClose: () => console.log('[Preview] Close clicked'),
	hasPreviousEmbed: false,
	hasNextEmbed: false
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
	/** With navigation arrows */
	withNavigation: {
		...defaultProps,
		hasPreviousEmbed: true,
		hasNextEmbed: true,
		onNavigatePrevious: () => console.log('[Preview] Navigate previous'),
		onNavigateNext: () => console.log('[Preview] Navigate next')
	},

	/** Minimal — no title */
	minimal: {
		tableContent: `| A | B | C |\n|---|---|---|\n| 1 | 2 | 3 |`,
		rowCount: 1,
		colCount: 3,
		onClose: () => console.log('[Preview] Close clicked')
	}
};
