/**
 * Preview fixtures for Business / Get company financials fullscreen embeds.
 * The fullscreen consumes data.decodedContent, so fixtures mirror persisted
 * parent app-skill-use payloads with embedded legacy result data.
 * Used by the web preview gallery and focused Playwright coverage.
 */

const results = [
  {
    embed_id: 'legacy-business-financial-calm',
    company: 'Cal-Maine Foods, Inc.',
    ticker: 'CALM',
    cik: '0000016160',
    period_type: 'annual',
    fiscal_year: 2025,
    period_start: '2024-06-02',
    period_end: '2025-05-31',
    filed: '2025-07-18',
    form: '10-K',
    currency: 'USD',
    revenue: 4_261_885_000,
    gross_profit: 1_799_800_000,
    operating_income: 1_446_200_000,
    net_income: 1_220_048_000,
    operating_cash_flow: 1_260_000_000,
    assets: 3_451_000_000,
    liabilities: 602_000_000,
    equity: 2_849_000_000,
    source_url: 'https://www.sec.gov/ixviewer/doc/action?doc=/Archives/edgar/data/16160/000001616025000050/calm-20250531.htm',
    accession_number: '0000016160-25-000050',
    notes: ['Normalized from SEC companyfacts and filing metadata.'],
  },
  {
    embed_id: 'legacy-business-financial-mu',
    company: 'Micron Technology, Inc.',
    ticker: 'MU',
    cik: '0000723125',
    period_type: 'annual',
    fiscal_year: 2025,
    period_start: '2024-08-30',
    period_end: '2025-08-28',
    filed: '2025-10-03',
    form: '10-K',
    currency: 'USD',
    revenue: 37_378_000_000,
    gross_profit: 14_212_000_000,
    operating_income: 9_411_000_000,
    net_income: 8_539_000_000,
    operating_cash_flow: 15_840_000_000,
    assets: 82_120_000_000,
    liabilities: 26_300_000_000,
    equity: 55_820_000_000,
    source_url: 'https://www.sec.gov/ixviewer/doc/action?doc=/Archives/edgar/data/723125/000072312525000120/mu-20250828.htm',
    accession_number: '0000723125-25-000120',
  },
];

const decodedContent = {
  query: 'Compare CALM and MU latest annual financials',
  provider: 'SEC EDGAR',
  period: 'latest_annual',
  metric_group: 'summary',
  status: 'finished' as const,
  result_count: results.length,
  results,
};

const defaultProps = {
  embedId: 'preview-business-company-financials',
  data: {
    decodedContent,
    embedData: { status: 'finished' },
    attrs: { app_id: 'business', skill_id: 'company_financials' },
  },
  onClose: () => {},
  hasPreviousEmbed: false,
  hasNextEmbed: false,
};

export default defaultProps;

export const variants = {
  quarterly: {
    ...defaultProps,
    embedId: 'preview-business-company-financials-quarterly',
    data: {
      ...defaultProps.data,
      decodedContent: {
        ...decodedContent,
        query: 'Show VITL latest quarter financials',
        period: 'latest_quarter',
        metric_group: 'income',
        result_count: 1,
        results: [
          {
            ...results[0],
            embed_id: 'legacy-business-financial-vitl-quarter',
            company: 'Vital Farms, Inc.',
            ticker: 'VITL',
            cik: '0001579733',
            period_type: 'quarter',
            fiscal_year: 2026,
            fiscal_quarter: 'Q1',
            period_start: '2025-12-29',
            period_end: '2026-03-28',
            filed: '2026-05-07',
            revenue: 187_155_000,
            net_income: -1_522_000,
            source_url: 'https://www.sec.gov/ixviewer/doc/action?doc=/Archives/edgar/data/1579733/000157973326000042/vitl-20260328.htm',
            accession_number: '0001579733-26-000042',
          },
        ],
      },
    },
  },
};
