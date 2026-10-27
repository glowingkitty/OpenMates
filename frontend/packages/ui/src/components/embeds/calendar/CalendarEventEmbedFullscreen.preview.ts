import { eventContent, overlapContent } from './CalendarEventEmbedPreview.preview';

const defaultProps = { embedId: 'calendar-event-preview', data: { decodedContent: eventContent }, onClose: () => {} };
export default defaultProps;
export const variants = {
  overlap: { ...defaultProps, data: { decodedContent: overlapContent } },
  minimal: { ...defaultProps, data: { decodedContent: { ...eventContent, primary_event: { title: 'Release day', start: '2027-03-20' } } } },
  invalid: { ...defaultProps, data: { decodedContent: { ...eventContent, primary_event: { title: 'Invalid date', start: '2027-02-30' } } } },
};
