/**
 * Preview fixtures for one Business company financial result card.
 * The data is synthetic-but-realistic public-company filing metadata.
 * This keeps the embed gallery deterministic and free of private data.
 * Fullscreen fixtures live beside the fullscreen component.
 */

const defaultProps = {
  id: 'preview-business-financial-calm',
  company: 'Cal-Maine Foods, Inc.',
  ticker: 'CALM',
  fiscalYear: 2025,
  periodType: 'annual',
  currency: 'USD',
  revenue: 4_261_885_000,
  netIncome: 1_220_048_000,
  filed: '2025-07-18',
  form: '10-K',
  status: 'finished' as const,
  isMobile: false,
  onFullscreen: () => {},
};

export default defaultProps;

export const variants = {
  quarterly: {
    ...defaultProps,
    id: 'preview-business-financial-vitl-quarter',
    company: 'Vital Farms, Inc.',
    ticker: 'VITL',
    fiscalYear: 2026,
    fiscalQuarter: 'Q1',
    periodType: 'quarter',
    revenue: 187_155_000,
    netIncome: -1_522_000,
    filed: '2026-05-07',
    form: '10-Q',
  },
  mobile: { ...defaultProps, id: 'preview-business-financial-calm-mobile', isMobile: true },
};
