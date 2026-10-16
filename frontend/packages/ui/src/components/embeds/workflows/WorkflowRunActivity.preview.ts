const defaultProps = {
  workflowId: '998a335e-741f-582c-885c-bf61d12ace93',
  runId: '118a335e-741f-582c-885c-bf61d12ace93',
  title: 'Upcoming events',
  description: 'Find relevant events and send a short summary.',
  startedAt: 1791745200,
  allowLookup: false,
  onFullscreen: () => { document.body.dataset.workflowRunOpened = 'true'; },
};

export default defaultProps;

export const variants = {
  legacy: { ...defaultProps, title: undefined, description: undefined, startedAt: undefined },
};
