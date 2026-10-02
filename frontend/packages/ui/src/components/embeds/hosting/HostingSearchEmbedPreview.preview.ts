import { parentContent } from './hostingPreviewFixtures';

const defaultProps = {
  id: 'preview-hosting-search', content: parentContent, status: 'finished' as const,
  presentationOnly: true, onFullscreen: () => {},
};
export default defaultProps;
export const variants = {
  processing: { ...defaultProps, status: 'processing' as const, content: { ...parentContent, result_count: 0, checked_count: 0, available_count: 0, unavailable_count: 0, unknown_count: 0, preview_starting_registration: null } },
  cancelled: { ...defaultProps, status: 'cancelled' as const, content: { ...parentContent, result_count: 0, checked_count: 0, available_count: 0, unavailable_count: 0, unknown_count: 0, preview_starting_registration: null } },
  empty: { ...defaultProps, content: { ...parentContent, result_count: 0, checked_count: 0, available_count: 0, unavailable_count: 0, unknown_count: 0, preview_starting_registration: null } },
  error: { ...defaultProps, status: 'error' as const, content: { ...parentContent, error: 'Domain provider unavailable', result_count: 0, checked_count: 0, available_count: 0, unavailable_count: 0, unknown_count: 0, preview_starting_registration: null } },
  partial: { ...defaultProps, content: { ...parentContent, partial: true, warnings: ['One domain check failed'] } },
  mobile: { ...defaultProps, isMobile: true },
};
