export const eventContent = {
  type: 'calendar_event', status: 'finished', openmatesType: 'calendar_event', schemaVersion: 1,
  primary_event: { title: 'FOSDEM 2027', start: '2027-01-30', end: '2027-02-01',
    description: 'A free conference for open source developers and communities.',
    location: 'ULB Solbosch, Brussels', source_url: 'https://fosdem.org/2027/' },
  context_events: [],
};
export const overlapContent = {
  ...eventContent,
  primary_event: { title: 'Open Source Workshop', start: '2027-03-15T10:00:00+01:00', end: '2027-03-15T12:00:00+01:00',
    timezone: 'Europe/Brussels', description: 'Build useful open source tools together.', location: 'Brussels' },
  context_events: [{ title: 'Team meeting', start: '2027-03-15T11:00:00+01:00', end: '2027-03-15T11:30:00+01:00', timezone: 'Europe/Brussels' }],
};

const defaultProps = { id: 'calendar-event-preview', content: eventContent, status: 'finished', resultContext: 'chat', onFullscreen: () => {} };
export default defaultProps;
export const variants = {
  overlap: { ...defaultProps, content: overlapContent },
  processing: { ...defaultProps, status: 'processing', content: { type: 'calendar_event', status: 'processing' } },
  error: { ...defaultProps, status: 'error', content: { type: 'calendar_event', status: 'error' } },
  cancelled: { ...defaultProps, status: 'cancelled' },
  mobile: { ...defaultProps },
  minimal: { ...defaultProps, content: { ...eventContent, primary_event: { title: 'Release day', start: '2027-03-20' } } },
  invalid: { ...defaultProps, content: { ...eventContent, primary_event: { title: 'Invalid date', start: '2027-02-30' } } },
  longTitle: { ...defaultProps, content: { ...eventContent, primary_event: { ...eventContent.primary_event, title: 'A long open source conference title that must stay within the shared preview bounds' } } },
};
