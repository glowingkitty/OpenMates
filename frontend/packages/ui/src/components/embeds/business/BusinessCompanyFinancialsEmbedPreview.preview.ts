/**
 * Preview fixtures for Business / Get company financials parent embeds.
 * These snapshots drive the web embed showcase and Playwright rendering tests.
 * Values are public SEC-style sample facts for stable display coverage.
 * The source URLs point at SEC resources, not private user data.
 */

const results = [
  {
    embed_id: 'legacy-business-financial-calm',
    company: 'Cal-Maine Foods, Inc.',
    ticker: 'CALM',
    cik: '0000016160',
    country: 'US',
    exchange: 'NASDAQ',
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
  },
  {
    embed_id: 'legacy-business-financial-mu',
    company: 'Micron Technology, Inc.',
    ticker: 'MU',
    cik: '0000723125',
    country: 'US',
    exchange: 'NASDAQ',
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

const defaultProps = {
  id: 'preview-business-company-financials',
  query: 'Compare CALM and MU latest annual financials',
  provider: 'SEC EDGAR',
  period: 'latest_annual',
  metricGroup: 'summary',
  status: 'finished' as const,
  results,
  resultCount: results.length,
  childEmbedIds: results.map((result) => result.embed_id),
  isMobile: false,
  onFullscreen: () => {},
};

export default defaultProps;

export const variants = {
  quarterly: {
    ...defaultProps,
    id: 'preview-business-company-financials-quarterly',
    query: 'Show VITL latest quarter financials',
    period: 'latest_quarter',
    metricGroup: 'income',
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
    resultCount: 1,
    childEmbedIds: ['legacy-business-financial-vitl-quarter'],
  },
  noResults: {
    ...defaultProps,
    id: 'preview-business-company-financials-empty',
    query: 'Private company with no SEC filing',
    results: [],
    resultCount: 0,
    childEmbedIds: [],
  },
  mobile: { ...defaultProps, id: 'preview-business-company-financials-mobile', isMobile: true },
};
