/**
 * Preview fixtures for Business company financial result fullscreen embeds.
 * Fullscreen receives persisted embed data through data.decodedContent.
 * The sample covers SEC source metadata and multiple metric rows.
 * Values are public-style test data and contain no user secrets.
 */

const decodedContent = {
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
};

const defaultProps = {
  embedId: 'preview-business-financial-calm',
  data: {
    decodedContent,
    embedData: { status: 'finished' },
    attrs: { app_id: 'business', skill_id: 'company_financial_result' },
  },
  onClose: () => {},
  hasPreviousEmbed: false,
  hasNextEmbed: false,
};

export default defaultProps;

export const variants = {
  quarterly: {
    ...defaultProps,
    embedId: 'preview-business-financial-vitl-quarter',
    data: {
      ...defaultProps.data,
      decodedContent: {
        ...decodedContent,
        company: 'Vital Farms, Inc.',
        ticker: 'VITL',
        cik: '0001579733',
        period_type: 'quarter',
        fiscal_year: 2026,
        fiscal_quarter: 'Q1',
        period_start: '2025-12-29',
        period_end: '2026-03-28',
        filed: '2026-05-07',
        form: '10-Q',
        revenue: 187_155_000,
        net_income: -1_522_000,
        source_url: 'https://www.sec.gov/ixviewer/doc/action?doc=/Archives/edgar/data/1579733/000157973326000042/vitl-20260328.htm',
        accession_number: '0001579733-26-000042',
      },
    },
  },
};
