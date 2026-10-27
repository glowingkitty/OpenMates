const defaultProps = {
  id: 'preview-flight-track', flightNumber: 'OM123', departureDate: '2026-10-20', originIata: 'MUC', destinationIata: 'LHR',
  actualTakeoff: '2026-10-20T08:15:00Z', actualLanding: '2026-10-20T09:45:00Z', trackPointCount: 4,
  onFullscreen: () => console.info('[Preview] flight result expanded'),
};
export default defaultProps;
export const variants = {
  chat: { ...defaultProps, resultContext: 'chat' as const },
  noTrack: { ...defaultProps, trackPointCount: 0 },
  diverted: { ...defaultProps, diverted: true },
};
