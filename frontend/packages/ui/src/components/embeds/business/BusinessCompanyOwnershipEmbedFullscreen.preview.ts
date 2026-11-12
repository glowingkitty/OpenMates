import { ownershipData, ukData, personData, ambiguousData, coverageGapData, mixedData, emptyData, errorData, germanRecord } from './BusinessCompanyOwnershipEmbedPreview.preview';
const props = { data: { decodedContent: ownershipData }, onClose: () => {} };
export default props;
export const variants = {
  uk: { ...props, data: { decodedContent: ukData } },
  person: { ...props, data: { decodedContent: personData } },
  ambiguous: { ...props, data: { decodedContent: ambiguousData } },
  coverage_gap: { ...props, data: { decodedContent: coverageGapData } },
  mixed: { ...props, data: { decodedContent: mixedData } },
  empty: { ...props, data: { decodedContent: emptyData } },
  error: { ...props, data: { decodedContent: errorData } },
  sparse: { ...props, data: { decodedContent: { ...ownershipData, records: [{ subject: { name: 'Example Robotics GmbH' }, owners: [{ name: 'Jane Example' }] }], result_count: 1 } } },
  long: { ...props, data: { decodedContent: { ...ownershipData, records: [{ ...germanRecord,
    subject: { ...germanRecord.subject, name: 'Example Robotics And Autonomous Systems Verwaltungsgesellschaft Mit Beschränkter Haftung Und Compagnie' },
    owners: [{ name: 'Jane Maria Example-Placeholder Of The Very Long Family Name Holding Company Limited', relation: 'shareholder', share_percent: 42.5, register_id: 'HRB 1234567890123456789' }] }] } } },
};
