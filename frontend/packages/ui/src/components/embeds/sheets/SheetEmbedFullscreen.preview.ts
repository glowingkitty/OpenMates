/**
 * Preview mock data for SheetEmbedFullscreen.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/sheets/SheetEmbedFullscreen
 */

const teamDirectoryTable = `| Name | Role | Department | Start Date | Location | Salary |
|------|------|------------|------------|----------|--------|
| Alice Johnson | Senior Engineer | Engineering | 2023-01-15 | Munich | €85,000 |
| Bob Smith | Product Manager | Product | 2022-06-01 | Berlin | €92,000 |
| Carol Williams | Lead Designer | Design | 2024-03-10 | Munich | €78,000 |
| David Brown | DevOps Lead | Engineering | 2021-11-20 | Remote | €88,000 |
| Eva Martinez | QA Engineer | Engineering | 2023-08-05 | Barcelona | €72,000 |
| Frank Lee | Frontend Developer | Engineering | 2024-01-08 | Munich | €76,000 |
| Grace Kim | Data Analyst | Analytics | 2023-05-22 | Berlin | €68,000 |
| Henry Davis | Backend Developer | Engineering | 2022-09-15 | Munich | €82,000 |`;

// 8-column sales table — exercises auto column widths on wide data
const salesReportTable = `| Region | Product | Q1 | Q2 | Q3 | Q4 | Total | Growth |
|--------|---------|----|----|----|----|-------|--------|
| North | Widget A | $12,400 | $15,800 | $18,200 | $21,500 | $67,900 | +14% |
| North | Widget B | $8,900 | $9,400 | $11,200 | $13,600 | $43,100 | +18% |
| South | Widget A | $9,200 | $10,500 | $12,800 | $15,400 | $47,900 | +22% |
| South | Widget B | $6,700 | $7,200 | $8,900 | $10,100 | $32,900 | +12% |
| East | Widget A | $14,200 | $16,700 | $19,400 | $23,100 | $73,400 | +8% |
| East | Widget B | $10,400 | $11,800 | $13,200 | $15,900 | $51,300 | +16% |
| West | Widget A | $11,600 | $13,200 | $15,700 | $18,900 | $59,400 | +20% |
| West | Widget B | $7,800 | $8,600 | $10,200 | $12,400 | $39,000 | +11% |
| Central | Widget A | $10,800 | $12,400 | $14,600 | $17,200 | $55,000 | +17% |
| Central | Widget B | $5,900 | $6,700 | $8,100 | $9,800 | $30,500 | +15% |`;

// Mixed short/long columns — tests that narrow numeric cols don't expand and text cols don't wrap
const inventoryTable = `| SKU | Product Name | Category | Stock | Unit Price | Reorder Point | Supplier | Last Updated |
|-----|-------------|----------|-------|------------|---------------|----------|--------------|
| A001 | Wireless Bluetooth Headphones | Electronics | 245 | $89.99 | 50 | TechSupply Co | 2025-03-01 |
| A002 | USB-C Charging Cable (2m) | Accessories | 1203 | $12.99 | 200 | CableWorld | 2025-03-10 |
| A003 | Mechanical Keyboard | Electronics | 87 | $149.00 | 30 | KeyCraft | 2025-02-28 |
| A004 | Laptop Stand | Accessories | 412 | $45.00 | 100 | DeskPro | 2025-03-05 |
| A005 | Noise Cancelling Earbuds | Electronics | 156 | $199.00 | 40 | TechSupply Co | 2025-03-12 |
| A006 | HDMI Cable (1m) | Accessories | 890 | $8.99 | 300 | CableWorld | 2025-03-08 |
| A007 | Ergonomic Mouse | Electronics | 334 | $59.99 | 80 | KeyCraft | 2025-03-03 |`;

// Two-column — tests that wide 2-col tables look clean
const glossaryTable = `| Term | Definition |
|------|-----------|
| API | Application Programming Interface — a contract that defines how software components communicate |
| REST | Representational State Transfer — an architectural style for designing networked applications |
| JWT | JSON Web Token — a compact, URL-safe means of representing claims to be transferred between parties |
| OAuth | Open Authorization — an open standard for access delegation commonly used for token-based auth |
| CORS | Cross-Origin Resource Sharing — a browser mechanism that controls cross-origin HTTP requests |
| CDN | Content Delivery Network — a geographically distributed network of servers for fast content delivery |
| SLA | Service Level Agreement — a commitment between a service provider and a client on service quality |`;

/** Default props — shows a fullscreen sheet/table view */
const defaultProps = {
	title: 'Team Directory',
	rowCount: 8,
	colCount: 6,
	tableContent: teamDirectoryTable,
	onClose: () => {},
	hasPreviousEmbed: false,
	hasNextEmbed: false
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
	/** Wide 8-column sales table — exercises auto col widths on numeric data */
	salesReport: {
		title: 'Sales Report Q4 2025',
		rowCount: 10,
		colCount: 8,
		tableContent: salesReportTable,
		onClose: () => {},
		hasPreviousEmbed: true,
		hasNextEmbed: true,
		onNavigatePrevious: () => {},
		onNavigateNext: () => {}
	},

	/** 8-column inventory — mixed short IDs and long product names */
	inventory: {
		title: 'Inventory Status',
		rowCount: 7,
		colCount: 8,
		tableContent: inventoryTable,
		onClose: () => {}
	},

	/** 2-column glossary — tests that wide text columns size cleanly */
	glossary: {
		title: 'Technical Glossary',
		rowCount: 7,
		colCount: 2,
		tableContent: glossaryTable,
		onClose: () => {}
	},

	/** With navigation arrows */
	withNavigation: {
		...defaultProps,
		hasPreviousEmbed: true,
		hasNextEmbed: true,
		onNavigatePrevious: () => {},
		onNavigateNext: () => {}
	},

	/** Minimal — no title */
	minimal: {
		tableContent: `| A | B | C |\n|---|---|---|\n| 1 | 2 | 3 |`,
		rowCount: 1,
		colCount: 3,
		onClose: () => {}
	}
};
