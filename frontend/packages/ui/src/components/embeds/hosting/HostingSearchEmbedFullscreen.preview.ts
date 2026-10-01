import { checkedChildren, domainFixtures, parentContent } from './hostingPreviewFixtures';

const defaultProps = {
  embedId: 'preview-hosting-search',
  data: { decodedContent: parentContent, embedData: { status: 'finished' } },
  previewChildren: checkedChildren,
  onClose: () => {},
};
export default defaultProps;
export const variants = {
  partial: { ...defaultProps, data: { decodedContent: { ...parentContent, partial: true, warnings: ['One check failed'] }, embedData: { status: 'finished' } } },
  empty: { ...defaultProps, data: { decodedContent: { ...parentContent, embed_ids: [], selected_embed_ids: [], result_count: 0, checked_count: 0, available_count: 0, unavailable_count: 0, unknown_count: 0 }, embedData: { status: 'finished' } }, previewChildren: [] },
  error: { ...defaultProps, data: { decodedContent: { ...parentContent, error: 'Domain availability could not be checked', selected_embed_ids: [], result_count: 0, checked_count: 1, available_count: 0, unavailable_count: 0, unknown_count: 1 }, embedData: { status: 'error' } }, previewChildren: [domainFixtures.unknown] },
  processing: { ...defaultProps, data: { decodedContent: { ...parentContent, embed_ids: [], selected_embed_ids: [], result_count: 0, checked_count: 0 }, embedData: { status: 'processing' } }, previewChildren: [] },
  cancelled: { ...defaultProps, data: { decodedContent: { ...parentContent, embed_ids: [], selected_embed_ids: [], result_count: 0, checked_count: 0 }, embedData: { status: 'cancelled' } }, previewChildren: [] },
  availableOnly: { ...defaultProps, data: { decodedContent: { ...parentContent, availability: 'available_only', selected_embed_ids: [domainFixtures.com.embed_id, domainFixtures.net.embed_id] }, embedData: { status: 'finished' } } },
  mobile: { ...defaultProps },
};
