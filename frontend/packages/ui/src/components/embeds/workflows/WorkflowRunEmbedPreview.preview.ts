const defaultProps = {
  runId: '00000000-0000-4000-8000-000000000001',
  title: 'Upcoming events',
  description: 'Find relevant events and send a short summary.',
  startedAt: 1791745200,
  onFullscreen: () => { document.body.dataset.workflowRunOpened = 'true'; },
};

export default defaultProps;

export const variants = {
  legacy: { ...defaultProps, title: undefined, description: undefined, startedAt: undefined },
};
