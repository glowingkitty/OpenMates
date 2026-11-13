/** Synthetic app-store examples for business.company_ownership; no real companies or people. */
import { germanRecord, ukRecord, personRecord, ambiguousError, coverageGapError } from './BusinessCompanyOwnershipEmbedPreview.preview';
const limitation = 'Official register data only; ownership may be incomplete, and registers can lag behind recent changes.';
const german = { query: 'Example Robotics GmbH', providers: ['my_provider'], provider: 'my_provider', result_count: 1,
  records: [germanRecord], errors: [], warnings: [], limitation };
const uk = { query: 'Example Analytics Ltd', providers: ['my_provider'], provider: 'my_provider', result_count: 1,
  records: [ukRecord], errors: [], warnings: [], limitation };
const person = { query: 'Jane Example', providers: ['my_provider'], provider: 'my_provider', result_count: 1,
  records: [personRecord], errors: [], warnings: [], limitation };
const ambiguous = { query: 'Example Holding', providers: ['my_provider'], provider: 'my_provider', result_count: 0,
  records: [], errors: [ambiguousError], warnings: [], limitation };
const coverageGap = { query: 'Example Oy', providers: ['my_provider'], provider: 'my_provider', result_count: 0,
  records: [], errors: [coverageGapError], warnings: [], limitation };
const examples = [
  { id: 'store-example-business-company-ownership-1', query_translation_key: 'settings.app_store_examples.business.company_ownership.1',
    status: 'finished' as const, ...german, content: german },
  { id: 'store-example-business-company-ownership-2', query_translation_key: 'settings.app_store_examples.business.company_ownership.2',
    status: 'finished' as const, ...uk, content: uk },
  { id: 'store-example-business-company-ownership-3', query_translation_key: 'settings.app_store_examples.business.company_ownership.3',
    status: 'finished' as const, ...person, content: person },
  { id: 'store-example-business-company-ownership-4', query_translation_key: 'settings.app_store_examples.business.company_ownership.4',
    status: 'finished' as const, ...ambiguous, content: ambiguous },
  { id: 'store-example-business-company-ownership-5', query_translation_key: 'settings.app_store_examples.business.company_ownership.5',
    status: 'finished' as const, ...coverageGap, content: coverageGap },
];
export default examples;
